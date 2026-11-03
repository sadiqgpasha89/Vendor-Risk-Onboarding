"""Quote location: exact or fuzzy (>=0.9) re-find of a cited quote inside document pages (GR-003, ST re-verification)."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_WS = re.compile(r"\s+")


def norm(s: str) -> str:
    return _WS.sub(" ", re.sub(r"[​‌‍﻿]", "", s)).strip().casefold()


def locate_quote(pages: list[str], quote: str, threshold: float = 0.9) -> tuple[float, int | None]:
    """Return (best_score, page_number 1-based). Exact normalised substring => 1.0."""
    q = norm(quote)
    if not q:
        return 0.0, None
    qw = q.split()
    best, best_page = 0.0, None
    for pn, page in enumerate(pages, 1):
        p = norm(page)
        if q in p:
            return 1.0, pn
        pw = p.split()
        n = len(qw)
        if n == 0 or len(pw) < max(1, n // 2):
            continue
        step = max(1, n // 6)
        for i in range(0, max(1, len(pw) - n + 1), step):
            window = " ".join(pw[i:i + n])
            if SequenceMatcher(None, q, window).quick_ratio() < threshold - 0.1:
                continue
            r = SequenceMatcher(None, q, window).ratio()
            if r > best:
                best, best_page = r, pn
    return round(best, 4), (best_page if best >= threshold else None)
