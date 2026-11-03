"""Observability Module - Comprehensive observability with Grafana, Tempo, and Prometheus."""

import logging
import time
from typing import Any, Dict, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from contextlib import contextmanager, asynccontextmanager
from functools import wraps
import asyncio
import uuid

try:
    from opentelemetry import trace, metrics
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.resources import Resource
    HAS_OTEL = True
except ImportError:
    trace = None
    metrics = None
    TracerProvider = None
    BatchSpanProcessor = None
    MeterProvider = None
    Resource = None
    HAS_OTEL = False

try:
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
except ImportError:
    JaegerExporter = None

try:
    from opentelemetry.exporter.prometheus import PrometheusMetricReader
except ImportError:
    PrometheusMetricReader = None

try:
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
except ImportError:
    OTLPMetricExporter = None
    PeriodicExportingMetricReader = None

try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
except ImportError:
    FastAPIInstrumentor = None

try:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
except ImportError:
    SQLAlchemyInstrumentor = None

try:
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
except ImportError:
    RequestsInstrumentor = None

try:
    from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor
except ImportError:
    AsyncioInstrumentor = None

logger = logging.getLogger(__name__)


@dataclass
class SpanContext:
    """Context for tracing spans."""

    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    span_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_span_id: Optional[str] = None
    operation_name: str = ""
    status: str = "unset"
    error: Optional[str] = None
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    def get_duration(self) -> float:
        """Get span duration in milliseconds."""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return 0.0

    def set_error(self, error: str) -> None:
        """Mark span as error."""
        self.status = "error"
        self.error = error


@dataclass
class MetricPoint:
    """Single metric point."""

    name: str
    value: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    attributes: Dict[str, Any] = field(default_factory=dict)


class ObservabilityManager:
    """Manages observability infrastructure (traces, metrics, logs)."""

    def __init__(
        self,
        app_name: str,
        environment: str,
        jaeger_host: str = "localhost",
        jaeger_port: int = 6831,
        otlp_exporter_endpoint: Optional[str] = None,
        prometheus_port: int = 8000,
    ):
        """Initialize observability manager.

        Args:
            app_name: Application name
            environment: Environment (dev, prod, etc)
            jaeger_host: Jaeger agent host
            jaeger_port: Jaeger agent port
            otlp_exporter_endpoint: OTLP exporter endpoint for metrics
            prometheus_port: Prometheus metrics port
        """
        self.app_name = app_name
        self.environment = environment

        # Resource for all signals
        resource = Resource.create(
            {
                "service.name": app_name,
                "service.environment": environment,
            }
        ) if Resource and hasattr(Resource, "create") else None

        # Setup tracing with Jaeger/Tempo
        self._setup_tracing(resource, jaeger_host, jaeger_port)

        # Setup metrics
        self._setup_metrics(resource, otlp_exporter_endpoint)

        self.span_contexts: Dict[str, SpanContext] = {}
        self.metrics_points: list[MetricPoint] = []

        logger.info(f"Observability initialized for {app_name} in {environment}")

    def _setup_tracing(
        self,
        resource: Any,
        jaeger_host: str,
        jaeger_port: int,
    ) -> None:
        """Setup distributed tracing with Jaeger."""
        if not JaegerExporter or not TracerProvider or not trace:
            self.tracer = trace.get_tracer(__name__) if trace else None
            return

        try:
            jaeger_exporter = JaegerExporter(
                agent_host_name=jaeger_host,
                agent_port=jaeger_port,
            )

            tracer_provider = TracerProvider(resource=resource)
            tracer_provider.add_span_processor(
                BatchSpanProcessor(jaeger_exporter)
            )
            trace.set_tracer_provider(tracer_provider)
            self.tracer = trace.get_tracer(__name__)
            logger.info(
                f"Tracing configured with Jaeger at {jaeger_host}:{jaeger_port}"
            )
        except Exception as e:
            logger.warning(f"Failed to configure Jaeger exporter: {e}")
            self.tracer = trace.get_tracer(__name__) if trace else None

    def _setup_metrics(
        self,
        resource: Any,
        otlp_endpoint: Optional[str],
    ) -> None:
        """Setup metrics export."""
        if not MeterProvider or not metrics:
            self.meter = metrics.get_meter(__name__) if metrics else None
            return

        metric_readers = []

        # Add Prometheus reader for Grafana scraping if available
        if PrometheusMetricReader:
            try:
                prometheus_reader = PrometheusMetricReader()
                metric_readers.append(prometheus_reader)
            except Exception as e:
                logger.warning(f"Could not initialize PrometheusMetricReader: {e}")

        # Add OTLP reader if configured and available
        if otlp_endpoint and OTLPMetricExporter and PeriodicExportingMetricReader:
            try:
                otlp_reader = PeriodicExportingMetricReader(
                    OTLPMetricExporter(endpoint=otlp_endpoint)
                )
                metric_readers.append(otlp_reader)
            except Exception as e:
                logger.warning(f"Could not initialize OTLPMetricExporter: {e}")

        try:
            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=metric_readers,
            )
            metrics.set_meter_provider(meter_provider)
            self.meter = metrics.get_meter(__name__)
            logger.info("Metrics configured")
        except Exception as e:
            logger.warning(f"Could not set meter provider: {e}")
            self.meter = metrics.get_meter(__name__) if metrics else None

    def instrument_fastapi(self, app) -> None:
        """Instrument FastAPI application."""
        if FastAPIInstrumentor:
            FastAPIInstrumentor.instrument_app(app)
            logger.info("FastAPI instrumented")

    def instrument_sqlalchemy(self, engine) -> None:
        """Instrument SQLAlchemy."""
        if SQLAlchemyInstrumentor:
            try:
                SQLAlchemyInstrumentor().instrument(engine=engine)
                logger.info("SQLAlchemy instrumented")
            except Exception as e:
                logger.warning(f"Could not instrument SQLAlchemy: {e}")

    def instrument_requests(self) -> None:
        """Instrument requests library."""
        if RequestsInstrumentor:
            try:
                RequestsInstrumentor().instrument()
                logger.info("Requests instrumented")
            except Exception as e:
                logger.warning(f"Could not instrument Requests: {e}")

    def instrument_asyncio(self) -> None:
        """Instrument asyncio."""
        if AsyncioInstrumentor:
            try:
                AsyncioInstrumentor().instrument()
                logger.info("Asyncio instrumented")
            except Exception as e:
                logger.warning(f"Could not instrument Asyncio: {e}")
        logger.info("Asyncio instrumented")

    @contextmanager
    def create_span(
        self,
        operation_name: str,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        """Context manager for creating spans.

        Args:
            operation_name: Name of the operation
            attributes: Additional span attributes
        """
        span_id = str(uuid.uuid4())
        span_context = SpanContext(
            operation_name=operation_name,
            attributes=attributes or {},
        )
        self.span_contexts[span_id] = span_context

        start_time = time.time()

        with self.tracer.start_as_current_span(operation_name) as span:
            span.set_attribute("span_id", span_id)
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, value)

            try:
                yield span
                span_context.status = "ok"
            except Exception as e:
                span_context.set_error(str(e))
                span.set_attribute("error", True)
                span.set_attribute("error_message", str(e))
                raise
            finally:
                span_context.end_time = datetime.utcnow()
                span_context.duration_ms = (time.time() - start_time) * 1000

    @asynccontextmanager
    async def create_async_span(
        self,
        operation_name: str,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        """Async context manager for creating spans."""
        span_id = str(uuid.uuid4())
        span_context = SpanContext(
            operation_name=operation_name,
            attributes=attributes or {},
        )
        self.span_contexts[span_id] = span_context

        start_time = time.time()

        with self.tracer.start_as_current_span(operation_name) as span:
            span.set_attribute("span_id", span_id)
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, value)

            try:
                yield span
                span_context.status = "ok"
            except Exception as e:
                span_context.set_error(str(e))
                span.set_attribute("error", True)
                span.set_attribute("error_message", str(e))
                raise
            finally:
                span_context.end_time = datetime.utcnow()
                span_context.duration_ms = (time.time() - start_time) * 1000

    def record_metric(
        self,
        name: str,
        value: float,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a metric point."""
        point = MetricPoint(
            name=name,
            value=value,
            attributes=attributes or {},
        )
        self.metrics_points.append(point)

    def get_span_context(self, span_id: str) -> Optional[SpanContext]:
        """Get span context by ID."""
        return self.span_contexts.get(span_id)

    def get_recent_spans(self, limit: int = 100) -> list[SpanContext]:
        """Get recent spans."""
        return sorted(
            self.span_contexts.values(),
            key=lambda s: s.start_time,
            reverse=True,
        )[:limit]

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get metrics summary."""
        if not self.metrics_points:
            return {}

        summary = {}
        for point in self.metrics_points:
            if point.name not in summary:
                summary[point.name] = {
                    "count": 0,
                    "sum": 0,
                    "min": float("inf"),
                    "max": float("-inf"),
                    "last_value": 0,
                }

            summary[point.name]["count"] += 1
            summary[point.name]["sum"] += point.value
            summary[point.name]["min"] = min(summary[point.name]["min"], point.value)
            summary[point.name]["max"] = max(summary[point.name]["max"], point.value)
            summary[point.name]["last_value"] = point.value

        # Calculate averages
        for metric_name in summary:
            summary[metric_name]["avg"] = (
                summary[metric_name]["sum"] / summary[metric_name]["count"]
            )

        return summary

    def shutdown(self) -> None:
        """Shutdown observability manager."""
        trace.get_tracer_provider().force_flush()
        metrics.get_meter_provider().force_flush()
        logger.info("Observability shutdown complete")


def trace_operation(operation_name: Optional[str] = None):
    """Decorator for tracing operations.

    Args:
        operation_name: Name of the operation (defaults to function name)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            op_name = operation_name or func.__name__
            # Create a simple tracer for sync functions
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span(op_name) as span:
                span.set_attribute("function", func.__name__)
                return func(*args, **kwargs)

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            op_name = operation_name or func.__name__
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span(op_name) as span:
                span.set_attribute("function", func.__name__)
                return await func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


class AgentCallTracker:
    """Track agentic AI calls and interactions."""

    def __init__(self, observability_manager: ObservabilityManager):
        """Initialize agent call tracker.

        Args:
            observability_manager: Observability manager instance
        """
        self.observability = observability_manager
        self.call_history: list[Dict[str, Any]] = []

    async def track_agent_call(
        self,
        agent_id: str,
        agent_name: str,
        input_data: Dict[str, Any],
        output_data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        duration_ms: float = 0.0,
    ) -> str:
        """Track an agent call.

        Args:
            agent_id: Agent identifier
            agent_name: Agent name
            input_data: Input to agent
            output_data: Output from agent
            error: Any error that occurred
            duration_ms: Call duration

            Returns:
            Call trace ID
        """
        call_id = str(uuid.uuid4())
        call_record = {
            "call_id": call_id,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "timestamp": datetime.utcnow().isoformat(),
            "input_size": len(str(input_data)),
            "output_size": len(str(output_data)) if output_data else 0,
            "duration_ms": duration_ms,
            "status": "error" if error else "success",
            "error": error,
        }

        self.call_history.append(call_record)

        # Record metrics
        self.observability.record_metric(
            "agent_call_duration_ms",
            duration_ms,
            {"agent": agent_name},
        )

        self.observability.record_metric(
            "agent_call_count",
            1,
            {"agent": agent_name, "status": "error" if error else "success"},
        )

        logger.info(
            f"Agent call tracked: {agent_name} ({call_id}) "
            f"in {duration_ms:.2f}ms"
        )

        return call_id

    def get_agent_stats(self, agent_name: Optional[str] = None) -> Dict[str, Any]:
        """Get statistics for agent calls.

        Args:
            agent_name: Optional agent name to filter by

            Returns:
            Statistics dictionary
        """
        calls = self.call_history
        if agent_name:
            calls = [c for c in calls if c["agent_name"] == agent_name]

        if not calls:
            return {}

        total_calls = len(calls)
        successful_calls = sum(1 for c in calls if c["status"] == "success")
        failed_calls = total_calls - successful_calls

        total_duration = sum(c["duration_ms"] for c in calls)
        avg_duration = total_duration / total_calls

        return {
            "agent_name": agent_name or "all",
            "total_calls": total_calls,
            "successful_calls": successful_calls,
            "failed_calls": failed_calls,
            "success_rate": successful_calls / total_calls if total_calls > 0 else 0,
            "avg_duration_ms": avg_duration,
            "total_duration_ms": total_duration,
            "recent_calls": calls[-10:],
        }

    def get_call_history(self, limit: int = 100) -> list[Dict[str, Any]]:
        """Get recent call history."""
        return self.call_history[-limit:]

    def clear_history(self) -> None:
        """Clear call history."""
        self.call_history.clear()
