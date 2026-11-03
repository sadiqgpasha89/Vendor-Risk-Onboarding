"""PDF ingestion front end: runs `pdfworker.py` in a sandboxed subprocess (timeout, memory/CPU limits, clean environment, own session) and turns
its output into what `docproc` needs. Scanned pages are OCR'd (tesseract + poppler) and the document gets an OCR quality grade:

  high  : no OCR, or mean word confidence >= 85 on every OCR'd page
  low   : any OCR'd page with mean confidence < 70 or fewer than 5 words, or unreadable pages  -> DOC-002 asks a human to confirm extracted values
  medium: otherwise

Hidden/active content is NOT executed: it becomes injection_flags (a manipulation signal, R4) like in the other formats.
Install: pip install pypdf pdfplumber ; apt-get install tesseract-ocr tesseract-ocr-<lang> poppler-utils
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

WORKER = Path(__file__).with_name("pdfworker.py")

ERRORS = {"encrypted": "the PDF is password-protected; ask the vendor for an unprotected copy",
          "too_many_pages": "the PDF has too many pages", "text_bomb": "the PDF expands to an implausible amount of text",
          "unreadable": "the PDF is corrupt or not a valid PDF", "timeout": "PDF parsing timed out", "memory_limit": "PDF parsing exceeded the memory limit",
          "parser_error": "PDF parsing failed", "parser_crashed": "the PDF parser crashed on this file", "no_parser": "PDF libraries (pypdf, pdfplumber) are not installed",
          "needs_ocr": "the PDF is a scan and OCR is unavailable (install tesseract + poppler or enable PDF_OCR)"}


@dataclass
class PdfResult:
    ok: bool
    status: str = "ACCEPTED"          # ACCEPTED | REJECTED | UNSUPPORTED_PARSER
    reason: str = ""
    pages: list[str] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)
    flags: list[dict] = field(default_factory=list)
    ocr_quality: str = "high"
    meta: dict = field(default_factory=dict)


def _env(cfg: dict) -> dict:
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin"), "LANG": "C.UTF-8", "OMP_THREAD_LIMIT": "1", "TESSDATA_PREFIX": os.environ.get("TESSDATA_PREFIX", ""),
            "PDF_MAX_PAGES": str(cfg.get("max_pages", 500)), "PDF_OCR": "1" if cfg.get("ocr", True) else "0", "OCR_LANGS": cfg.get("langs", "eng"),
            "PDF_OCR_DPI": str(cfg.get("dpi", 200)), "PDF_OCR_MAX_PAGES": str(cfg.get("ocr_max_pages", 60)), "PDF_MEM_MB": str(cfg.get("mem_mb", 2048)),
            "PDF_CPU_SECONDS": str(int(cfg.get("timeout", 300))), "PYTHONDONTWRITEBYTECODE": "1"}


def run_worker(data: bytes, cfg: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix="vro-pdfrun-") as cwd:
        try:
            p = subprocess.run([sys.executable, "-I", str(WORKER)], input=data, capture_output=True, timeout=cfg.get("timeout", 300), cwd=cwd,
                               env=_env(cfg), start_new_session=True)
        except subprocess.TimeoutExpired:
            return {"error": "timeout"}
    if p.returncode != 0 and not p.stdout:
        return {"error": "parser_crashed", "detail": f"exit {p.returncode}"}
    try:
        out = json.loads(p.stdout or b"{}")
    except ValueError:
        return {"error": "parser_crashed", "detail": "bad output"}
    if "error" not in out and "pages" not in out:
        return {"error": "parser_crashed"}
    if "ModuleNotFoundError" in p.stderr.decode("utf-8", "replace"):
        return {"error": "no_parser"}
    return out


def grade(pages: list[dict]) -> str:
    ocr = [p for p in pages if p["source"] == "ocr"]
    bad = [p for p in pages if p["source"] == "unreadable"]
    if bad or any((p.get("conf") is None) or p["conf"] < 70 or p.get("words", 0) < 5 for p in ocr):
        return "low"
    if any(p["conf"] < 85 for p in ocr):
        return "medium"
    return "high"


def parse_pdf(data: bytes, cfg: dict | None = None, injection_patterns: list | None = None) -> PdfResult:
    cfg = cfg or {}
    out = run_worker(data, cfg)
    if "error" in out:
        err = out["error"]
        status = "UNSUPPORTED_PARSER" if err in ("no_parser", "needs_ocr") else "REJECTED"
        return PdfResult(False, status, ERRORS.get(err, "PDF parsing failed"))
    pages = out["pages"]
    texts = [p["text"] for p in pages]
    if not any(t.strip() for t in texts):
        scanned = out["meta"].get("unreadable_pages", 0) > 0
        return PdfResult(False, "UNSUPPORTED_PARSER" if scanned else "REJECTED", ERRORS["needs_ocr"] if scanned else "the PDF contains no extractable text",
                         meta=out.get("meta", {}))
    hidden = [h for p in pages for h in p["hidden"] if h.strip()]
    flags: list[dict] = [{"kind": k, "page": None, "channel": "hidden", "snippet": ""} for k in out["active"]]
    for sc in out["side_channels"]:        # metadata/annotations: only a signal if they look like instructions or are suspiciously long
        t = sc["text"]
        if len(t) > 500 or (injection_patterns and any(rx.search(t) for _, rx in injection_patterns)):
            hidden.append(f"[{sc['source']}] {t}")
    meta = {**out["meta"], "warnings": out["warnings"],
            "ocr_pages_detail": [{"page": p["n"], "confidence": round(p["conf"], 1) if p.get("conf") is not None else None, "words": p.get("words")} for p in pages if p["source"] == "ocr"]}
    return PdfResult(True, "ACCEPTED", "", texts, hidden, flags, grade(pages), meta)
