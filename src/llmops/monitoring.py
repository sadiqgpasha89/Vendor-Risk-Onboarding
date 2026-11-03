"""LLMOps Monitoring and Observability Infrastructure."""

import logging
import json
import time
from typing import Optional, Dict, Any
from datetime import datetime
from functools import wraps
from contextlib import contextmanager
import structlog
try:
    from opentelemetry import trace, metrics
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    HAS_OTEL = True
except ImportError:
    trace = None
    metrics = None
    TracerProvider = None
    BatchSpanProcessor = None
    MeterProvider = None
    SERVICE_NAME = "service.name"
    Resource = None
    HAS_OTEL = False

try:
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
except ImportError:
    JaegerExporter = None

try:
    from langsmith import traceable
except ImportError:
    def traceable(*args, **kwargs):
        def decorator(f):
            return f
        return decorator

try:
    import wandb
except ImportError:
    wandb = None

from src.config.settings import settings


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


class OpenTelemetryMonitor:
    """OpenTelemetry monitoring infrastructure."""

    def __init__(self, service_name: str = "vendor-risk-onboarding"):
        """Initialize OpenTelemetry monitoring."""
        self.service_name = service_name
        self.tracer_provider = None
        self.tracer = None
        self.meter = None
        self._setup_tracing()

    def _setup_tracing(self) -> None:
        """Setup tracing with Jaeger."""
        if not HAS_OTEL or not settings.llmops.opentelemetry_enabled:
            return

        if not JaegerExporter:
            return

        resource = Resource(attributes={SERVICE_NAME: self.service_name})

        # Setup Jaeger exporter
        jaeger_exporter = JaegerExporter(
            agent_host_name=settings.llmops.jaeger_agent_host,
            agent_port=settings.llmops.jaeger_agent_port,
        )

        self.tracer_provider = TracerProvider(resource=resource)
        self.tracer_provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
        trace.set_tracer_provider(self.tracer_provider)
        self.tracer = trace.get_tracer(__name__)

        # Setup metrics
        self.meter = metrics.get_meter(__name__)

    def record_span(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        """Create a span for tracing."""
        if self.tracer is None:
            return None

        span = self.tracer.start_span(name)
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        return span

    def shutdown(self) -> None:
        """Shutdown OpenTelemetry."""
        if self.tracer_provider:
            self.tracer_provider.force_flush()


class PerformanceMonitor:
    """Monitor performance metrics of agents and models."""

    def __init__(self):
        """Initialize performance monitor."""
        self.metrics: Dict[str, list] = {}

    @contextmanager
    def track_operation(self, operation_name: str):
        """Context manager to track operation performance."""
        start_time = time.time()
        start_memory = self._get_memory_usage()

        try:
            yield
        finally:
            elapsed_time = time.time() - start_time
            end_memory = self._get_memory_usage()
            memory_delta = end_memory - start_memory

            metric = {
                "timestamp": datetime.utcnow().isoformat(),
                "operation": operation_name,
                "duration_seconds": elapsed_time,
                "memory_delta_mb": memory_delta / 1024 / 1024,
            }

            if operation_name not in self.metrics:
                self.metrics[operation_name] = []

            self.metrics[operation_name].append(metric)
            logger.info(
                "operation_completed",
                operation=operation_name,
                duration=elapsed_time,
                memory_delta=metric["memory_delta_mb"],
            )

    @staticmethod
    def _get_memory_usage() -> int:
        """Get current process memory usage in bytes."""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss
        except ImportError:
            return 0

    def get_metrics(self, operation_name: Optional[str] = None) -> Dict[str, Any]:
        """Get collected metrics."""
        if operation_name:
            return {"operation": operation_name, "metrics": self.metrics.get(operation_name, [])}
        return {"all_metrics": self.metrics}

    def get_summary(self) -> Dict[str, Dict[str, float]]:
        """Get summary statistics for all operations."""
        summary = {}
        for operation, metrics_list in self.metrics.items():
            if not metrics_list:
                continue

            durations = [m["duration_seconds"] for m in metrics_list]
            summary[operation] = {
                "count": len(metrics_list),
                "avg_duration": sum(durations) / len(durations),
                "min_duration": min(durations),
                "max_duration": max(durations),
                "total_duration": sum(durations),
            }
        return summary


class LLMCostMonitor:
    """Monitor and track LLM API costs."""

    # Approximate token costs (update based on current pricing)
    TOKEN_COSTS = {
        "gpt-4": {"input": 0.03 / 1000, "output": 0.06 / 1000},
        "gpt-3.5-turbo": {"input": 0.0005 / 1000, "output": 0.0015 / 1000},
        "claude-3-opus": {"input": 0.015 / 1000, "output": 0.075 / 1000},
        "claude-3-sonnet": {"input": 0.003 / 1000, "output": 0.015 / 1000},
    }

    def __init__(self):
        """Initialize cost monitor."""
        self.total_cost = 0.0
        self.cost_by_model: Dict[str, float] = {}
        self.usage_by_model: Dict[str, Dict[str, int]] = {}

    def record_usage(
        self,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Record token usage and calculate cost."""
        # Normalize model name
        base_model = model_name.split("/")[-1]
        cost_info = self.TOKEN_COSTS.get(base_model, self.TOKEN_COSTS.get("gpt-3.5-turbo"))

        cost = (
            input_tokens * cost_info["input"] + output_tokens * cost_info["output"]
        )

        self.total_cost += cost
        self.cost_by_model[model_name] = self.cost_by_model.get(model_name, 0.0) + cost

        if model_name not in self.usage_by_model:
            self.usage_by_model[model_name] = {"input": 0, "output": 0}

        self.usage_by_model[model_name]["input"] += input_tokens
        self.usage_by_model[model_name]["output"] += output_tokens

        logger.info(
            "llm_usage_recorded",
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
        )

        return cost

    def get_cost_summary(self) -> Dict[str, Any]:
        """Get cost summary."""
        return {
            "total_cost": self.total_cost,
            "cost_by_model": self.cost_by_model,
            "usage_by_model": self.usage_by_model,
        }


class WorkflowLogger:
    """Log workflow execution for audit and debugging."""

    def __init__(self):
        """Initialize workflow logger."""
        self.workflows: Dict[str, list] = {}

    def log_event(
        self,
        workflow_id: str,
        event_type: str,
        agent_name: str,
        data: Optional[Dict[str, Any]] = None,
        status: str = "success",
    ) -> None:
        """Log a workflow event."""
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "agent": agent_name,
            "status": status,
            "data": data or {},
        }

        if workflow_id not in self.workflows:
            self.workflows[workflow_id] = []

        self.workflows[workflow_id].append(event)

        logger.info(
            "workflow_event",
            workflow_id=workflow_id,
            event_type=event_type,
            agent=agent_name,
            status=status,
        )

    def get_workflow_log(self, workflow_id: str) -> list:
        """Get complete workflow log."""
        return self.workflows.get(workflow_id, [])

    def export_workflow_log(self, workflow_id: str, format: str = "json") -> str:
        """Export workflow log in specified format."""
        log = self.get_workflow_log(workflow_id)
        if format == "json":
            return json.dumps(log, indent=2, default=str)
        return json.dumps(log, default=str)


def monitor_llm_call(func):
    """Decorator to monitor LLM calls."""

    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            duration = time.time() - start_time
            logger.info(
                "llm_call_completed",
                function=func.__name__,
                duration=duration,
                status="success",
            )
            return result
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                "llm_call_failed",
                function=func.__name__,
                duration=duration,
                error=str(e),
            )
            raise

    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            logger.info(
                "llm_call_completed",
                function=func.__name__,
                duration=duration,
                status="success",
            )
            return result
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                "llm_call_failed",
                function=func.__name__,
                duration=duration,
                error=str(e),
            )
            raise

    # Return appropriate wrapper based on function type
    if hasattr(func, "__await__"):
        return async_wrapper
    return sync_wrapper


# Global monitoring instances
otel_monitor = OpenTelemetryMonitor()
performance_monitor = PerformanceMonitor()
cost_monitor = LLMCostMonitor()
workflow_logger = WorkflowLogger()
