"""Small shared helpers: ids, hashing, canonical JSON, injectable clock."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone

_NOW_OVERRIDE: datetime | None = None


def now() -> datetime:
    """Current UTC time; tests can freeze/advance it with set_now()."""
    return _NOW_OVERRIDE or datetime.now(timezone.utc)


def set_now(dt: datetime | None) -> None:
    global _NOW_OVERRIDE
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _NOW_OVERRIDE = dt


def today() -> date:
    return now().date()


def iso(dt: datetime | date | None) -> str | None:
    return dt.isoformat() if dt else None


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:16]}"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_text(s: str) -> str:
    return sha256_bytes(s.encode("utf-8"))


def canonical_json(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def add_days(d: date, n: int) -> date:
    return d + timedelta(days=n)


_WS = re.compile(r"\s+")


def squash(s: str) -> str:
    return _WS.sub(" ", s).strip()


def word_count(s: str) -> int:
    return len(s.split())
