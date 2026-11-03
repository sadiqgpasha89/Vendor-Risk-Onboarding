"""Observability: structured JSON logs with secret scrubbing, optional OpenTelemetry spans, and Prometheus-format metrics helpers.

Logs never contain request bodies, document text, prompts, tokens or Authorization headers (R10). OpenTelemetry is optional: with the
API package only, spans are no-ops; set OTEL_EXPORTER_OTLP_ENDPOINT and install opentelemetry-sdk + the OTLP exporter to ship traces.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from contextlib import contextmanager

from .util import iso, now

_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
_SECRET = re.compile(r"(?i)(authorization|api[-_]?key|password|secret|token)(\"?\s*[:=]\s*\"?)[^\s\",}]+")


def scrub(text: str) -> str:
    return _SECRET.sub(r"\1\2[redacted]", _JWT.sub("[jwt]", _BEARER.sub("Bearer [redacted]", text)))

logger = logging.getLogger("vro")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": iso(now()), "level": record.levelname, "msg": scrub(record.getMessage())}
        d.update(getattr(record, "fields", {}))
        if record.exc_info:
            d["exc"] = scrub(self.formatException(record.exc_info))[-2000:]
        return json.dumps(d, default=str)


def setup_logging(level: str = "INFO") -> None:
    if any(getattr(h, "_vro", False) for h in logger.handlers):
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    h._vro = True                                     # type: ignore[attr-defined]
    logger.addHandler(h)
    logger.setLevel(level.upper())
    logger.propagate = False


def log(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": fields})


# ---- tracing (optional)
try:
    from opentelemetry import trace as _otel
except ImportError:                                   # pragma: no cover
    _otel = None


def init_tracing(endpoint: str, service: str = "vro-agents") -> bool:
    """Wire an OTLP exporter if the SDK is installed. Returns False (and logs) if it cannot; the app keeps running without traces."""
    if not endpoint or _otel is None:
        return False
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        tp = TracerProvider(resource=Resource.create({"service.name": service}))
        tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")))
        _otel.set_tracer_provider(tp)
        return True
    except Exception as e:  # noqa: BLE001
        log("tracing_unavailable", logging.WARNING, error=type(e).__name__)
        return False


@contextmanager
def span(name: str, **attrs):
    """Span with attributes. Pass identifiers and counts only, never document text or personal data."""
    if _otel is None:
        yield None
        return
    with _otel.get_tracer("vro").start_as_current_span(name) as sp:
        for k, v in attrs.items():
            if isinstance(v, (str, int, float, bool)):
                sp.set_attribute(f"vro.{k}", v)
        yield sp


# ---- metrics
class Histogram:
    BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300)

    def __init__(self):
        self.counts: dict[tuple, list[int]] = {}
        self.sums: dict[tuple, float] = {}

    def observe(self, labels: tuple, v: float) -> None:
        c = self.counts.setdefault(labels, [0] * (len(self.BUCKETS) + 1))
        for i, b in enumerate(self.BUCKETS):
            if v <= b:
                c[i] += 1
        c[-1] += 1
        self.sums[labels] = self.sums.get(labels, 0.0) + v

    def render(self, name: str, label_names: tuple) -> list[str]:
        out = [f"# TYPE {name} histogram"]
        for labels, c in sorted(self.counts.items()):
            base = ",".join(f'{n}="{v}"' for n, v in zip(label_names, labels))
            for b, n in zip(self.BUCKETS, c):
                out.append(f'{name}_bucket{{{base},le="{b}"}} {n}')
            out.append(f'{name}_bucket{{{base},le="+Inf"}} {c[-1]}')
            out.append(f"{name}_sum{{{base}}} {round(self.sums[labels], 4)}")
            out.append(f"{name}_count{{{base}}} {c[-1]}")
        return out


def now_s() -> float:
    return time.perf_counter()
