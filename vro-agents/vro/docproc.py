"""Document service: quarantine, parse, sanitise, classify (plan §6.3.5, §8.3).

Vendor documents are untrusted input (R4). We neutralise what we can before any LLM sees text:
hidden text is stripped, sentences matching instruction patterns are removed, and both are recorded as flags
(a vendor attempting manipulation is itself a risk signal). The original bytes are stored untouched for forensics.

Parsers: txt/md, html, docx, csv (stdlib) and PDF (vro/pdfparse.py: sandboxed worker, text layer + OCR for scans). A PDF the build cannot read
(no libraries, scan without OCR) is marked UNSUPPORTED_PARSER and an analyst is asked for another format.
"""
from __future__ import annotations

import base64
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

from .util import sha256_bytes

ZERO_WIDTH = "​‌‍⁠﻿᠎"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

INJECTION_PATTERNS = [
    ("ignore_instructions", re.compile(r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)", re.I)),
    ("disregard", re.compile(r"disregard\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|your|earlier)", re.I)),
    ("set_outcome", re.compile(r"(mark|rate|classify|score|set|treat)\s+(this\s+|the\s+)?(vendor|supplier|company)\s+(as\s+|to\s+)?(tier\s?[1-4]|t[1-4]|low[- ]risk|low|approved|compliant|safe)", re.I)),
    ("suppress_reporting", re.compile(r"do\s+not\s+(mention|report|flag|disclose|include)\b", re.I)),
    ("role_hijack", re.compile(r"(you\s+are\s+now|new\s+instructions|system\s+prompt|as\s+an\s+ai\s+(language\s+)?model|<\|im_start\|>|\[INST\])", re.I)),
    ("fake_authority", re.compile(r"(auditor|assessor|regulator|compliance\s+officer)\s+(has\s+)?(pre-?\s?)?(approved|cleared|certified)\s+(this\s+)?(vendor|supplier|report)", re.I)),
    ("override_policy", re.compile(r"override\s+(the\s+)?(risk|tier|score|policy|screening)", re.I)),
]
DOC_RULES = [  # (doc_type, required-any keywords, bonus keywords)
    ("soc2_report", ["soc 2", "system and organization controls"], ["service auditor", "trust services", "type ii", "type i "]),
    ("iso_certificate", ["iso/iec 27001", "iso 27001"], ["certificate", "certification body", "statement of applicability"]),
    ("pentest_summary", ["penetration test", "pen test"], ["vulnerabilit", "findings", "retest"]),
    ("bcp_dr", ["business continuity", "disaster recovery"], ["rto", "rpo", "failover"]),
    ("insurance_certificate", ["certificate of insurance"], ["cyber", "policy", "named insured"]),
    ("dpa", ["data processing agreement", "data processing addendum"], ["sub-processor", "controller", "processor"]),
    ("contract", ["master services agreement", "master service agreement", "services agreement"], ["audit", "termination", "liability"]),
    ("financial_statements", ["balance sheet", "statement of financial position"], ["going concern", "total equity", "revenue"]),
    ("register_of_information", ["register of information"], ["ict third-party", "dora"]),
    ("questionnaire", ["security questionnaire", "due diligence questionnaire"], ["answer", "yes/no"]),
]
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
ISO_DATE = r"(\d{4}-\d{2}-\d{2})"
LONG_DATE = r"((?:" + "|".join(MONTHS) + r")\s+\d{1,2},?\s+\d{4})"
ANY_DATE = rf"(?:{ISO_DATE}|{LONG_DATE})"


@dataclass
class ParsedDoc:
    mime: str
    status: str                       # ACCEPTED | UNSUPPORTED_PARSER | REJECTED
    reason: str = ""
    doc_type: str = "unknown"
    raw_pages: list[str] = field(default_factory=list)
    clean_pages: list[str] = field(default_factory=list)
    hidden_text_flag: bool = False
    injection_flags: list[dict] = field(default_factory=list)
    period_start: date | None = None
    period_end: date | None = None
    valid_until: date | None = None
    language: str = "en"
    sha256: str = ""
    ocr_quality: str = "high"          # high | medium | low (low => DOC-002: a human must confirm extracted values)
    parse_meta: dict = field(default_factory=dict)

    @property
    def clean_text(self) -> str:
        return "\f".join(self.clean_pages)

    @property
    def raw_text(self) -> str:
        return "\f".join(self.raw_pages)


def sniff_mime(data: bytes, filename: str) -> str:
    if data[:5] == b"%PDF-":
        return "application/pdf"
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
            if "word/document.xml" in names:
                return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            return "application/zip"
        except zipfile.BadZipFile:
            return "application/octet-stream"
    low = data[:2048].lstrip().lower()
    if low.startswith(b"<!doctype html") or low.startswith(b"<html") or filename.lower().endswith((".html", ".htm")):
        return "text/html"
    if b"\x00" in data[:4096]:
        return "application/octet-stream"
    if filename.lower().endswith(".csv"):
        return "text/csv"
    return "text/plain"


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.hidden: list[str] = []
        self._skip = 0
        self._stack: list[bool] = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        style = a.get("style", "").replace(" ", "").lower()
        hid = ("display:none" in style or "visibility:hidden" in style or "font-size:0" in style
               or "color:#fff" in style or "color:white" in style or "color:#ffffff" in style or "hidden" in a
               or a.get("aria-hidden") == "true")
        if tag in ("script", "style"):
            hid = True
        self._stack.append(hid)
        if hid:
            self._skip += 1
        if tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "section"):
            self.out.append("\n")
        for alt in ("alt", "title"):  # alt/title text can carry hidden instructions: treat as hidden channel
            if a.get(alt):
                self.hidden.append(a[alt])

    def handle_endtag(self, tag):
        if self._stack:
            if self._stack.pop():
                self._skip -= 1
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section"):
            self.out.append("\n")

    def handle_data(self, data):
        (self.hidden if self._skip else self.out).append(data)

    def handle_comment(self, data):
        self.hidden.append(data)


def _parse_html(text: str) -> tuple[str, list[str]]:
    p = _HTMLText()
    p.feed(text)
    return "".join(p.out), p.hidden


def _parse_docx(data: bytes) -> tuple[str, list[str]]:
    visible: list[str] = []
    hidden: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
        for name in z.namelist():
            if name in ("word/comments.xml", "docProps/custom.xml"):
                hidden.append(" ".join(t for t in ET.fromstring(z.read(name)).itertext()))
    for para in root.iter(W + "p"):
        buf = []
        for run in para.iter(W + "r"):
            rpr = run.find(W + "rPr")
            vanish = rpr is not None and rpr.find(W + "vanish") is not None
            color = rpr.find(W + "color") if rpr is not None else None
            white = color is not None and (color.get(W + "val") or "").lower() in ("ffffff", "fff")
            size = rpr.find(W + "sz") if rpr is not None else None
            tiny = size is not None and size.get(W + "val") in ("0", "1", "2")
            txt = "".join(t.text or "" for t in run.iter(W + "t"))
            if any(br.get(W + "type") == "page" for br in run.iter(W + "br")):
                buf.append("\f")
            if vanish or white or tiny:
                hidden.append(txt)
            else:
                buf.append(txt)
        visible.append("".join(buf))
    return "\n".join(visible), hidden


def _split_pages(text: str) -> list[str]:
    text = re.sub(r"^\s*\[\[PAGE\s+\d+\]\]\s*$", "\f", text, flags=re.M)
    pages = [p.strip("\n") for p in text.split("\f")]
    return [p for p in pages if p.strip()] or [""]


def _detect_injection(pages: list[str], hidden: list[str]) -> list[dict]:
    flags = []
    for pn, page in enumerate(pages, 1):
        for kind, rx in INJECTION_PATTERNS:
            for m in rx.finditer(page):
                flags.append({"kind": kind, "page": pn, "channel": "visible", "snippet": page[max(0, m.start() - 20): m.end() + 40].replace("\n", " ")[:120]})
        for m in re.finditer(r"[A-Za-z0-9+/]{40,}={0,2}", page):  # encoded payloads
            try:
                dec = base64.b64decode(m.group(0), validate=False).decode("utf-8", "ignore")
            except Exception:
                continue
            if any(rx.search(dec) for _, rx in INJECTION_PATTERNS):
                flags.append({"kind": "encoded_instruction", "page": pn, "channel": "visible", "snippet": dec[:100]})
        for word in re.findall(r"\w{4,}", page):  # homoglyphs: Latin word containing Cyrillic/Greek lookalikes
            has_latin = any("a" <= c.lower() <= "z" for c in word)
            has_conf = any("Ѐ" <= c <= "ӿ" or "Ͱ" <= c <= "Ͽ" for c in word)
            if has_latin and has_conf:
                flags.append({"kind": "homoglyph", "page": pn, "channel": "visible", "snippet": word[:40]})
                break
    for h in hidden:
        if not h.strip():
            continue
        hit = [k for k, rx in INJECTION_PATTERNS if rx.search(h)]
        flags.append({"kind": "hidden_text_instruction" if hit else "hidden_text", "page": None, "channel": "hidden",
                      "snippet": h.strip()[:120]})
    return flags


def _sanitise(page: str) -> str:
    # drop zero-width chars, then drop whole sentences/lines that match instruction patterns
    page = "".join(ch for ch in page if ch not in ZERO_WIDTH)
    out = []
    for line in page.split("\n"):
        pieces = re.split(r"(?<=[.!?])\s+", line)
        keep = []
        for s in pieces:
            if any(rx.search(s) for _, rx in INJECTION_PATTERNS):
                keep.append("[REDACTED: embedded instruction removed]")
            else:
                keep.append(s)
        out.append(" ".join(keep))
    return "\n".join(out)


def classify(text: str, filename: str = "") -> str:
    low = (text[:20000] + " " + filename).lower()
    best, best_score = "unknown", 0
    for dt, req, bonus in DOC_RULES:
        if not any(k in low for k in req):
            continue
        sc = 10 + sum(1 for b in bonus if b in low)
        if sc > best_score:
            best, best_score = dt, sc
    return best


def _to_date(s: str) -> date | None:
    s = s.strip()
    m = re.fullmatch(ISO_DATE, s)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            return None
    m = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", s)
    if m and m.group(1).lower() in MONTHS:
        try:
            return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
        except ValueError:
            return None
    return None


def _first_date(m: re.Match | None, *groups) -> date | None:
    if not m:
        return None
    for g in groups:
        if m.group(g):
            return _to_date(m.group(g))
    return None


def extract_dates(text: str) -> tuple[date | None, date | None, date | None]:
    head = text[:30000]
    ps = pe = vu = None
    m = re.search(rf"period[^\n]{{0,40}}?{ANY_DATE}\s*(?:to|through|-|–|and)\s*{ANY_DATE}", head, re.I)
    if m:
        ps = _first_date(m, 1, 2)
        pe = _first_date(m, 3, 4)
    m = re.search(rf"(?:valid\s+until|expiry\s+date|expiration\s+date|expires(?:\s+on)?|policy\s+period\s+end)[:\s]+{ANY_DATE}", head, re.I)
    if m:
        vu = _first_date(m, 1, 2)
    return ps, pe, vu


def detect_language(text: str) -> str:
    sample = text[:4000]
    if not sample:
        return "en"
    non_ascii = sum(1 for c in sample if ord(c) > 127) / max(1, len(sample))
    if non_ascii > 0.3:
        return "other"
    low = sample.lower()
    en = sum(low.count(w) for w in (" the ", " and ", " of ", " is ", " to "))
    de = sum(low.count(w) for w in (" der ", " die ", " und ", " nicht ", " ist "))
    fr = sum(low.count(w) for w in (" le ", " la ", " et ", " les ", " est "))
    return "en" if en >= max(de, fr) else ("de" if de >= fr else "fr")


def process(data: bytes, filename: str, max_bytes: int = 25_000_000, max_pages: int = 500, pdf_cfg: dict | None = None) -> ParsedDoc:
    sha = sha256_bytes(data)
    mime = sniff_mime(data, filename)
    if len(data) > max_bytes:
        return ParsedDoc(mime=mime, status="REJECTED", reason=f"file exceeds {max_bytes} bytes", sha256=sha)
    pdf = None
    if mime == "application/pdf":
        from . import pdfparse
        pdf = pdfparse.parse_pdf(data, {**(pdf_cfg or {}), "max_pages": max_pages}, INJECTION_PATTERNS)
        if not pdf.ok:
            return ParsedDoc(mime=mime, status=pdf.status, reason=pdf.reason, sha256=sha, parse_meta=pdf.meta)
    if mime in ("application/zip", "application/octet-stream"):
        return ParsedDoc(mime=mime, status="REJECTED", reason=f"unsupported or unsafe file type {mime}", sha256=sha)
    hidden: list[str] = []
    try:
        if pdf is not None:
            text, hidden = "\f".join(pdf.pages), list(pdf.hidden)
        elif mime.endswith("wordprocessingml.document"):
            text, hidden = _parse_docx(data)
        elif mime == "text/html":
            text, hidden = _parse_html(data.decode("utf-8", "replace"))
        else:
            text = data.decode("utf-8", "replace")
    except Exception as e:  # corrupt document: quarantine, never crash the pipeline
        return ParsedDoc(mime=mime, status="REJECTED", reason=f"parse error: {type(e).__name__}", sha256=sha)
    zw = any(ch in text for ch in ZERO_WIDTH)
    raw_pages = list(pdf.pages) if pdf is not None else _split_pages(text)       # PDFs keep blank pages so cited page numbers stay true
    if len(raw_pages) > max_pages:
        return ParsedDoc(mime=mime, status="REJECTED", reason=f"too many pages ({len(raw_pages)})", sha256=sha)
    flags = _detect_injection(raw_pages, hidden) + (pdf.flags if pdf is not None else [])
    if zw:
        flags.append({"kind": "zero_width_characters", "page": None, "channel": "hidden", "snippet": ""})
    clean_pages = [_sanitise(p) for p in raw_pages]
    doc_type = classify("\n".join(clean_pages), filename)
    ps, pe, vu = extract_dates("\n".join(clean_pages))
    return ParsedDoc(mime=mime, status="ACCEPTED", doc_type=doc_type, raw_pages=raw_pages, clean_pages=clean_pages,
                     hidden_text_flag=bool(hidden and any(h.strip() for h in hidden)) or zw, injection_flags=flags,
                     period_start=ps, period_end=pe, valid_until=vu, language=detect_language("\n".join(clean_pages)), sha256=sha,
                     ocr_quality=pdf.ocr_quality if pdf is not None else "high", parse_meta=pdf.meta if pdf is not None else {})
