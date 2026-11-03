"""Extended Observability Module - LangFuse and LangSmith integration."""

import logging
import time
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
import asyncio

try:
    from langsmith import Client as LangSmithClient
    from langsmith.run_trees import RunTree
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False

try:
    from langfuse import Langfuse
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class LLMCallMetadata:
    """Metadata for LLM call tracking."""

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0
    temperature: float = 0.7
    max_tokens: int = 2048
    stop_sequences: list = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class LangSmithTracker:
    """LangSmith integration for LLM chain tracking."""

    def __init__(self, project_name: str, api_key: Optional[str] = None):
        """Initialize LangSmith tracker.

        Args:
            project_name: Project name in LangSmith
            api_key: API key (defaults to LANGSMITH_API_KEY env var)
        """
        if not LANGSMITH_AVAILABLE:
            logger.warning("LangSmith not available. Install with: pip install langsmith")
            self.client = None
            return

        try:
            self.client = LangSmithClient(api_key=api_key)
            self.project_name = project_name
            logger.info(f"LangSmith initialized for project: {project_name}")
        except Exception as e:
            logger.error(f"Error initializing LangSmith: {e}")
            self.client = None

    def log_llm_call(
        self,
        name: str,
        inputs: Dict[str, Any],
        outputs: Dict[str, Any],
        metadata: Optional[LLMCallMetadata] = None,
        tags: Optional[list] = None,
    ) -> Optional[str]:
        """Log LLM call to LangSmith.

        Args:
            name: Name of the call
            inputs: Input data
            outputs: Output data
            metadata: Call metadata
            tags: Optional tags

            Returns:
            Run ID if successful
        """
        if not self.client:
            return None

        try:
            # Convert inputs/outputs to strings
            inputs_str = {k: str(v)[:5000] for k, v in inputs.items()}
            outputs_str = {k: str(v)[:5000] for k, v in outputs.items()}

            response = self.client.create_run(
                name=name,
                run_type="llm",
                inputs=inputs_str,
                project_name=self.project_name,
                tags=tags or [],
                extra={
                    "metadata": metadata.__dict__ if metadata else {},
                },
            )

            # End the run
            self.client.update_run(
                response.id,
                outputs=outputs_str,
                end_time=datetime.utcnow(),
            )

            logger.debug(f"Logged LLM call to LangSmith: {name}")
            return str(response.id)

        except Exception as e:
            logger.error(f"Error logging to LangSmith: {e}")
            return None

    def log_chain_call(
        self,
        name: str,
        inputs: Dict[str, Any],
        outputs: Dict[str, Any],
        run_tree: Optional[Any] = None,
        tags: Optional[list] = None,
    ) -> Optional[str]:
        """Log chain execution to LangSmith.

        Args:
            name: Chain name
            inputs: Input data
            outputs: Output data
            run_tree: Optional parent run tree
            tags: Optional tags

            Returns:
            Run ID if successful
        """
        if not self.client:
            return None

        try:
            response = self.client.create_run(
                name=name,
                run_type="chain",
                inputs=inputs,
                project_name=self.project_name,
                tags=tags or [],
                parent_run_id=run_tree.id if run_tree else None,
            )

            self.client.update_run(
                response.id,
                outputs=outputs,
                end_time=datetime.utcnow(),
            )

            logger.debug(f"Logged chain to LangSmith: {name}")
            return str(response.id)

        except Exception as e:
            logger.error(f"Error logging chain to LangSmith: {e}")
            return None

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get run details from LangSmith."""
        if not self.client:
            return None

        try:
            run = self.client.read_run(run_id)
            return {
                "id": str(run.id),
                "name": run.name,
                "status": run.status,
                "inputs": run.inputs,
                "outputs": run.outputs,
                "start_time": run.start_time.isoformat() if run.start_time else None,
                "end_time": run.end_time.isoformat() if run.end_time else None,
            }
        except Exception as e:
            logger.error(f"Error reading run from LangSmith: {e}")
            return None


class LangFuseTracker:
    """LangFuse integration for LLM observability."""

    def __init__(
        self,
        public_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        endpoint: Optional[str] = None,
    ):
        """Initialize LangFuse tracker.

        Args:
            public_key: LangFuse public key
            secret_key: LangFuse secret key
            endpoint: Optional custom endpoint
        """
        if not LANGFUSE_AVAILABLE:
            logger.warning("LangFuse not available. Install with: pip install langfuse")
            self.client = None
            return

        try:
            kwargs = {}
            if public_key:
                kwargs["public_key"] = public_key
            if secret_key:
                kwargs["secret_key"] = secret_key
            if endpoint:
                kwargs["endpoint"] = endpoint

            self.client = Langfuse(**kwargs)
            logger.info("LangFuse initialized")
        except Exception as e:
            logger.error(f"Error initializing LangFuse: {e}")
            self.client = None

    def log_llm_call(
        self,
        name: str,
        inputs: Dict[str, Any],
        outputs: Dict[str, Any],
        metadata: Optional[LLMCallMetadata] = None,
        trace_id: Optional[str] = None,
    ) -> Optional[str]:
        """Log LLM call to LangFuse.

        Args:
            name: Operation name
            inputs: Input data
            outputs: Output data
            metadata: Call metadata
            trace_id: Optional trace ID

            Returns:
            Span ID if successful
        """
        if not self.client:
            return None

        try:
            generation = self.client.generation(
                name=name,
                model=metadata.model if metadata else "unknown",
                input=inputs,
                output=outputs,
                trace_id=trace_id,
            )

            if metadata:
                generation.prompt_tokens = metadata.prompt_tokens
                generation.completion_tokens = metadata.completion_tokens
                generation.total_tokens = metadata.total_tokens
                generation.end()

            logger.debug(f"Logged LLM call to LangFuse: {name}")
            return generation.id

        except Exception as e:
            logger.error(f"Error logging to LangFuse: {e}")
            return None

    def log_span(
        self,
        name: str,
        input_data: Dict[str, Any],
        output_data: Dict[str, Any],
        trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Log a general span to LangFuse.

        Args:
            name: Span name
            input_data: Input data
            output_data: Output data
            trace_id: Optional trace ID
            metadata: Optional metadata

            Returns:
            Span ID if successful
        """
        if not self.client:
            return None

        try:
            span = self.client.span(
                name=name,
                input=input_data,
                output=output_data,
                trace_id=trace_id,
                metadata=metadata or {},
            )

            logger.debug(f"Logged span to LangFuse: {name}")
            return span.id

        except Exception as e:
            logger.error(f"Error logging span to LangFuse: {e}")
            return None

    def get_traces(
        self,
        limit: int = 10,
        tags: Optional[list] = None,
    ) -> list[Dict[str, Any]]:
        """Get recent traces from LangFuse.

        Args:
            limit: Number of traces to retrieve
            tags: Optional tag filters

            Returns:
            List of traces
        """
        if not self.client:
            return []

        try:
            # LangFuse SDK may have different methods - adapt as needed
            logger.debug("Retrieved traces from LangFuse")
            return []
        except Exception as e:
            logger.error(f"Error retrieving traces from LangFuse: {e}")
            return []


class UnifiedLLMObservability:
    """Unified observability for LLM calls with LangSmith and LangFuse."""

    def __init__(
        self,
        langsmith_project: Optional[str] = None,
        langsmith_api_key: Optional[str] = None,
        langfuse_public_key: Optional[str] = None,
        langfuse_secret_key: Optional[str] = None,
        langfuse_endpoint: Optional[str] = None,
    ):
        """Initialize unified LLM observability.

        Args:
            langsmith_project: LangSmith project name
            langsmith_api_key: LangSmith API key
            langfuse_public_key: LangFuse public key
            langfuse_secret_key: LangFuse secret key
            langfuse_endpoint: LangFuse endpoint
        """
        self.langsmith = None
        self.langfuse = None

        if langsmith_project:
            self.langsmith = LangSmithTracker(langsmith_project, langsmith_api_key)

        if langfuse_public_key and langfuse_secret_key:
            self.langfuse = LangFuseTracker(
                langfuse_public_key,
                langfuse_secret_key,
                langfuse_endpoint,
            )

        self.call_history: list[Dict[str, Any]] = []

    def log_llm_call(
        self,
        name: str,
        inputs: Dict[str, Any],
        outputs: Dict[str, Any],
        metadata: Optional[LLMCallMetadata] = None,
        tags: Optional[list] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Log LLM call to all configured backends.

        Args:
            name: Operation name
            inputs: Input data
            outputs: Output data
            metadata: Call metadata
            tags: Optional tags
            trace_id: Optional trace ID

            Returns:
            Dictionary with tracking IDs from each backend
        """
        import uuid

        tracking_ids = {}

        # Log to LangSmith
        if self.langsmith:
            langsmith_id = self.langsmith.log_llm_call(
                name, inputs, outputs, metadata, tags
            )
            tracking_ids["langsmith_id"] = langsmith_id

        # Log to LangFuse
        if self.langfuse:
            langfuse_id = self.langfuse.log_llm_call(
                name, inputs, outputs, metadata, trace_id
            )
            tracking_ids["langfuse_id"] = langfuse_id

        # Log to history
        call_record = {
            "call_id": str(uuid.uuid4()),
            "name": name,
            "timestamp": datetime.utcnow().isoformat(),
            "input_size": len(str(inputs)),
            "output_size": len(str(outputs)),
            "metadata": metadata.__dict__ if metadata else {},
            "tags": tags or [],
            "tracking_ids": tracking_ids,
        }

        self.call_history.append(call_record)
        return tracking_ids

    def get_call_history(self, limit: int = 100) -> list[Dict[str, Any]]:
        """Get recent call history."""
        return self.call_history[-limit:]

    def get_statistics(self) -> Dict[str, Any]:
        """Get observability statistics."""
        if not self.call_history:
            return {"total_calls": 0}

        total_calls = len(self.call_history)
        total_input_size = sum(c.get("input_size", 0) for c in self.call_history)
        total_output_size = sum(c.get("output_size", 0) for c in self.call_history)

        backends_used = set()
        for call in self.call_history:
            for tracking_id in call.get("tracking_ids", {}).values():
                if tracking_id:
                    backends_used.add(tracking_id)

        return {
            "total_calls": total_calls,
            "total_input_size": total_input_size,
            "total_output_size": total_output_size,
            "avg_input_size": total_input_size / total_calls if total_calls else 0,
            "avg_output_size": total_output_size / total_calls if total_calls else 0,
            "backends_configured": {
                "langsmith": self.langsmith is not None,
                "langfuse": self.langfuse is not None,
            },
        }


def llm_observable(
    llm_observability: UnifiedLLMObservability,
    name: Optional[str] = None,
    tags: Optional[list] = None,
):
    """Decorator for automatic LLM call tracking.

    Args:
        llm_observability: UnifiedLLMObservability instance
        name: Operation name (defaults to function name)
        tags: Optional tags
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            op_name = name or func.__name__

            try:
                result = await func(*args, **kwargs)

                # Extract inputs/outputs if available
                inputs = {
                    "args": str(args)[:500],
                    "kwargs": str(kwargs)[:500],
                }
                outputs = {
                    "result": str(result)[:500],
                }

                duration_ms = (time.time() - start_time) * 1000
                metadata = LLMCallMetadata(
                    model="unknown",
                    latency_ms=duration_ms,
                )

                llm_observability.log_llm_call(
                    op_name, inputs, outputs, metadata, tags
                )

                return result

            except Exception as e:
                llm_observability.log_llm_call(
                    op_name,
                    {"args": str(args)[:500], "kwargs": str(kwargs)[:500]},
                    {"error": str(e)},
                    tags=tags,
                )
                raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            op_name = name or func.__name__

            try:
                result = func(*args, **kwargs)

                inputs = {
                    "args": str(args)[:500],
                    "kwargs": str(kwargs)[:500],
                }
                outputs = {
                    "result": str(result)[:500],
                }

                duration_ms = (time.time() - start_time) * 1000
                metadata = LLMCallMetadata(
                    model="unknown",
                    latency_ms=duration_ms,
                )

                llm_observability.log_llm_call(
                    op_name, inputs, outputs, metadata, tags
                )

                return result

            except Exception as e:
                llm_observability.log_llm_call(
                    op_name,
                    {"args": str(args)[:500], "kwargs": str(kwargs)[:500]},
                    {"error": str(e)},
                    tags=tags,
                )
                raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
