"""PDF extraction worker. Runs as a SEPARATE, resource-limited process (`python -I vro/pdfworker.py`): PDF parsers and image decoders are a
classic attack surface, so a malicious file can crash, hang or exhaust memory in here without touching the API process.

stdin: PDF bytes.  stdout: one JSON document.  Self-contained on purpose (no `vro` imports) so it works under `python -I`.
Config via env: PDF_MAX_PAGES, PDF_OCR (1/0), OCR_LANGS, PDF_OCR_DPI, PDF_OCR_MAX_PAGES, PDF_MIN_TEXT_CHARS, PDF_CPU_SECONDS, PDF_MEM_MB.

Nothing in the PDF is ever executed or rendered for a human: we read text objects, annotations and metadata, and rasterise pages only for OCR.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

MAX_CHARS_PAGE = 200_000
MAX_CHARS_TOTAL = 5_000_000
ACTIVE_KEYS = {"/JavaScript": "pdf_javascript", "/JS": "pdf_javascript", "/Launch": "pdf_launch_action", "/SubmitForm": "pdf_submit_form",
               "/ImportData": "pdf_import_data", "/RichMedia": "pdf_rich_media", "/EmbeddedFile": "pdf_embedded_file", "/EmbeddedFiles": "pdf_embedded_file",
               "/FileAttachment": "pdf_embedded_file", "/XFA": "pdf_xfa_form"}


def _limits() -> None:
    try:
        import resource
        mem = int(os.environ.get("PDF_MEM_MB", "2048")) << 20
        cpu = int(os.environ.get("PDF_CPU_SECONDS", "240"))
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 5))
        resource.setrlimit(resource.RLIMIT_FSIZE, (400 << 20, 400 << 20))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except Exception:  # noqa: BLE001  (non-POSIX): the parent's timeout still applies
        pass


# ---------------------------------------------------------------------------------------------------- active content
def _walk(obj, found: set, depth=0, seen=None) -> None:
    """Find dangerous keys in the object graph with hard depth/size caps (cyclic or enormous graphs cannot hang us)."""
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject
    seen = seen if seen is not None else set()
    if depth > 12 or len(seen) > 20000:
        return
    if isinstance(obj, IndirectObject):
        key = (obj.idnum, obj.generation)
        if key in seen:
            return
        seen.add(key)
        try:
            obj = obj.get_object()
        except Exception:  # noqa: BLE001
            return
    if isinstance(obj, DictionaryObject):
        for k, v in obj.items():
            if k in ACTIVE_KEYS:
                found.add(ACTIVE_KEYS[k])
            if k == "/S" and str(v) in ACTIVE_KEYS:
                found.add(ACTIVE_KEYS[str(v)])
            if k not in ("/Parent", "/P", "/Prev", "/Next", "/Dest"):
                _walk(v, found, depth + 1, seen)
    elif isinstance(obj, ArrayObject):
        for v in obj[:5000]:
            _walk(v, found, depth + 1, seen)


def _active_content(reader, data: bytes) -> list[str]:
    found: set = set()
    try:
        root = reader.trailer["/Root"]
        for k in ("/OpenAction", "/AA", "/Names", "/AcroForm"):
            if k in root:
                _walk(root[k], found)
        for page in reader.pages[:2000]:
            if "/AA" in page:
                _walk(page["/AA"], found)
            for a in page.get("/Annots", []) or []:
                _walk(a, found)
    except Exception:  # noqa: BLE001
        pass
    for m in re.finditer(rb"/(JavaScript|JS|Launch|EmbeddedFile|RichMedia|SubmitForm)\b", data[:50_000_000]):   # catches non-compressed objects the walk missed
        found.add(ACTIVE_KEYS.get("/" + m.group(1).decode(), "pdf_active_content"))
    return sorted(found)


# ---------------------------------------------------------------------------------------------------- text + hidden text
def _is_white(c) -> bool:
    if c is None:
        return False
    if isinstance(c, (int, float)):
        c = (c,)
    c = tuple(c)
    if len(c) == 1:
        return c[0] >= 0.97
    if len(c) == 3:
        return min(c) >= 0.97 if max(c) <= 1.0 else min(c) >= 247
    if len(c) == 4:                        # CMYK
        return max(c) <= 0.03
    return False


def _page_text(page) -> tuple[str, str, int]:
    """Visible text, hidden text, image count. Hidden = tiny, off-page, or white text that is not on a coloured box or image."""
    W, H = float(page.width), float(page.height)
    boxes = []
    for r in page.rects:
        if r.get("fill") and not _is_white(r.get("non_stroking_color")):
            boxes.append((r["x0"], r["top"], r["x1"], r["bottom"]))
    imgs = [(i["x0"], i["top"], i["x1"], i["bottom"]) for i in page.images]
    covered = lambda cx, cy, bs: any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in bs)

    def hidden(ch) -> bool:
        if ch.get("text", " ").isspace():
            return False
        if ch.get("size", 10) < 2.0:
            return True
        if ch["x1"] < -1 or ch["x0"] > W + 1 or ch["bottom"] < -1 or ch["top"] > H + 1:
            return True
        if _is_white(ch.get("non_stroking_color")):
            cx, cy = (ch["x0"] + ch["x1"]) / 2, (ch["top"] + ch["bottom"]) / 2
            return not (covered(cx, cy, boxes) or covered(cx, cy, imgs))
        return False

    vis = page.filter(lambda o: o.get("object_type") != "char" or not hidden(o))
    hid = page.filter(lambda o: o.get("object_type") == "char" and hidden(o))
    return (vis.extract_text(x_tolerance=2, y_tolerance=3) or ""), (hid.extract_text(x_tolerance=2, y_tolerance=3) or "").strip(), len(page.images)


# ---------------------------------------------------------------------------------------------------- OCR
def _ocr_available() -> bool:
    return bool(shutil.which("tesseract") and shutil.which("pdftoppm"))


def _ocr_page(pdf_path: str, n: int, dpi: int, langs: str, tmp: str) -> tuple[str, float | None, int]:
    prefix = os.path.join(tmp, f"p{n}")
    subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(n), "-l", str(n), "-gray", "-png", pdf_path, prefix], check=True, capture_output=True, timeout=120)
    imgs = sorted(f for f in os.listdir(tmp) if f.startswith(f"p{n}-") and f.endswith(".png"))
    if not imgs:
        return "", None, 0
    img = os.path.join(tmp, imgs[0])
    try:
        out = subprocess.run(["tesseract", img, "stdout", "-l", langs, "--psm", "3", "tsv"], check=True, capture_output=True, timeout=180).stdout.decode("utf-8", "replace")
    finally:
        os.remove(img)
    lines: dict[tuple, list[str]] = {}
    confs: list[float] = []
    for row in out.splitlines()[1:]:
        c = row.split("\t")
        if len(c) < 12 or not c[11].strip():
            continue
        try:
            conf = float(c[10])
        except ValueError:
            continue
        if conf < 0:
            continue
        lines.setdefault((c[2], c[3], c[4]), []).append(c[11])
        confs.append(conf)
    text = "\n".join(" ".join(ws) for ws in lines.values())
    return text, (sum(confs) / len(confs) if confs else None), len(confs)


# ---------------------------------------------------------------------------------------------------- main
def parse(data: bytes) -> dict:
    cfg = {"max_pages": int(os.environ.get("PDF_MAX_PAGES", "500")), "ocr": os.environ.get("PDF_OCR", "1") == "1", "langs": os.environ.get("OCR_LANGS", "eng"),
           "dpi": int(os.environ.get("PDF_OCR_DPI", "200")), "ocr_max": int(os.environ.get("PDF_OCR_MAX_PAGES", "60")), "min_chars": int(os.environ.get("PDF_MIN_TEXT_CHARS", "20"))}
    import pdfplumber
    from pypdf import PdfReader
    warnings: list[str] = []
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
    except Exception as e:  # noqa: BLE001
        return {"error": "unreadable", "detail": type(e).__name__}
    if reader.is_encrypted:
        try:
            ok = reader.decrypt("")
        except Exception:  # noqa: BLE001
            ok = 0
        if not ok:
            return {"error": "encrypted"}
        warnings.append("owner-password encryption removed (empty user password)")
    n_pages = len(reader.pages)
    if n_pages > cfg["max_pages"]:
        return {"error": "too_many_pages", "detail": str(n_pages)}
    side: list[dict] = []
    try:
        for k, v in (reader.metadata or {}).items():
            if isinstance(v, str) and v.strip():
                side.append({"source": f"metadata:{k}", "text": v[:2000]})
    except Exception:  # noqa: BLE001
        pass
    for i, page in enumerate(reader.pages, 1):
        try:
            for a in page.get("/Annots", []) or []:
                a = a.get_object()
                t = a.get("/Contents")
                if isinstance(t, str) and t.strip():
                    side.append({"source": f"annotation:p{i}", "text": t[:2000]})
        except Exception:  # noqa: BLE001
            continue
    active = _active_content(reader, data)

    pages: list[dict] = []
    tmpdir = tempfile.mkdtemp(prefix="vro-pdf-")
    pdf_path = os.path.join(tmpdir, "in.pdf")
    try:
        with open(pdf_path, "wb") as f:
            f.write(data)
        ocr_ok = cfg["ocr"] and _ocr_available()
        ocr_done = unreadable = 0
        total = 0
        with pdfplumber.open(io.BytesIO(data)) as pl:
            for i in range(n_pages):
                try:
                    vis, hid, nimg = _page_text(pl.pages[i])
                except Exception as e:  # noqa: BLE001
                    warnings.append(f"p{i + 1}: layout extraction failed ({type(e).__name__}); used fallback")
                    try:
                        vis, hid, nimg = (reader.pages[i].extract_text() or ""), "", 0
                    except Exception:  # noqa: BLE001
                        vis, hid, nimg = "", "", 0
                rec = {"n": i + 1, "text": vis[:MAX_CHARS_PAGE], "source": "text", "conf": None, "hidden": [hid[:5000]] if hid else []}
                if len(re.sub(r"\s", "", vis)) < cfg["min_chars"] and (nimg > 0 or not vis.strip()):
                    if ocr_ok and ocr_done < cfg["ocr_max"] and nimg > 0:
                        try:
                            txt, conf, nw = _ocr_page(pdf_path, i + 1, cfg["dpi"], cfg["langs"], tmpdir)
                            rec.update(text=(vis + "\n" + txt).strip()[:MAX_CHARS_PAGE], source="ocr", conf=conf, words=nw)
                            ocr_done += 1
                        except Exception as e:  # noqa: BLE001
                            warnings.append(f"p{i + 1}: OCR failed ({type(e).__name__})")
                            rec["source"] = "unreadable"
                            unreadable += 1
                    elif nimg > 0:
                        rec["source"] = "unreadable"
                        unreadable += 1
                        if not ocr_ok:
                            warnings.append(f"p{i + 1}: scanned page but OCR is unavailable or disabled")
                        else:
                            warnings.append(f"p{i + 1}: scanned page beyond the OCR page budget ({cfg['ocr_max']})")
                total += len(rec["text"])
                if total > MAX_CHARS_TOTAL:
                    return {"error": "text_bomb", "detail": str(total)}
                pages.append(rec)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    try:
        fields = reader.get_fields() or {}
        lines = [f"{k}: {v.get('/V')}" for k, v in fields.items() if isinstance(v.get("/V"), str) and v.get("/V").strip()]
        if lines:
            pages.append({"n": n_pages + 1, "text": "[Form fields]\n" + "\n".join(lines)[:MAX_CHARS_PAGE], "source": "form", "conf": None, "hidden": []})
    except Exception:  # noqa: BLE001
        pass
    return {"pages": pages, "side_channels": side, "active": active, "warnings": warnings[:50],
            "meta": {"pdf_pages": n_pages, "ocr_pages": ocr_done, "unreadable_pages": unreadable, "ocr_available": ocr_ok,
                     "producer": str((reader.metadata or {}).get("/Producer", ""))[:80] if reader.metadata else ""}}


if __name__ == "__main__":
    _limits()
    try:
        out = parse(sys.stdin.buffer.read())
    except MemoryError:
        out = {"error": "memory_limit"}
    except Exception as e:  # noqa: BLE001
        out = {"error": "parser_error", "detail": type(e).__name__}
    sys.stdout.write(json.dumps(out))
