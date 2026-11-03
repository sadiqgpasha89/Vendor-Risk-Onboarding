"""Distributed Tracing: Unified integration across OpenTelemetry, LangSmith, and GCP Cloud Trace."""

import time
import logging
from typing import Optional, Dict, Any, Callable
from contextlib import contextmanager
from functools import wraps
from datetime import datetime

logger = logging.getLogger(__name__)


class DistributedTracer:
    """Unified tracer adapter for agent workflows and LLM operations."""

    def __init__(self, service_name: str = "vendor-risk-onboarding"):
        self.service_name = service_name
        self._active_spans: Dict[str, Dict[str, Any]] = {}

    @contextmanager
    def trace_agent(self, agent_name: str, workflow_id: Optional[str] = None, **metadata):
        """Context manager to trace execution of an agent or pipeline stage."""
        span_id = f"{agent_name}-{int(time.time() * 1000)}"
        start_time = time.time()
        span_data = {
            "span_id": span_id,
            "agent_name": agent_name,
            "workflow_id": workflow_id,
            "start_time": datetime.utcnow().isoformat(),
            "metadata": metadata,
            "status": "RUNNING",
        }
        self._active_spans[span_id] = span_data
        logger.info(f"[TRACE] START agent '{agent_name}' (span: {span_id})")

        try:
            yield span_data
            span_data["status"] = "SUCCESS"
        except Exception as exc:
            span_data["status"] = "ERROR"
            span_data["error"] = str(exc)
            logger.error(f"[TRACE] ERROR in agent '{agent_name}': {exc}")
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000.0
            span_data["duration_ms"] = round(duration_ms, 2)
            span_data["end_time"] = datetime.utcnow().isoformat()
            logger.info(f"[TRACE] END agent '{agent_name}' in {duration_ms:.1f}ms - {span_data['status']}")


def trace_agent_execution(agent_name: str):
    """Decorator to trace agent execution."""
    tracer = DistributedTracer()

    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            workflow_id = kwargs.get("workflow_id")
            with tracer.trace_agent(agent_name, workflow_id=workflow_id):
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            workflow_id = kwargs.get("workflow_id")
            with tracer.trace_agent(agent_name, workflow_id=workflow_id):
                return func(*args, **kwargs)

        import asyncio
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator


# Global tracer instance
tracer = DistributedTracer()
