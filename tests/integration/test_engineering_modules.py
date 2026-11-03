"""Integration tests for engineering modules."""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.engineering.loop_engine import (
    FeedbackLoop,
    LoopConfig,
    LoopState,
    RetryConfig,
    with_retry,
)
from src.engineering.graph_engine import (
    WorkflowGraph,
    GraphBuilder,
    GraphState,
    GraphNode,
    NodeType,
)
from src.engineering.evaluation_pipeline import (
    EvaluationPipeline,
    RelevanceEvaluator,
    AccuracyEvaluator,
    EvaluationResult,
)


class TestLoopEngineering:
    """Tests for loop engineering module."""

    @pytest.mark.asyncio
    async def test_feedback_loop_convergence(self):
        """Test feedback loop with convergence."""
        iteration_count = 0

        async def loop_func(state):
            nonlocal iteration_count
            iteration_count += 1
            return {"score": 0.5 + (iteration_count * 0.15)}

        def convergence_func(result):
            return min(result["score"], 1.0)

        loop = FeedbackLoop(
            name="test_loop",
            loop_func=loop_func,
            convergence_func=convergence_func,
            config=LoopConfig(
                max_iterations=5,
                convergence_threshold=0.7,
            ),
        )

        result = await loop.execute()

        assert result.iteration > 0
        assert result.convergence_score >= 0.7
        assert not result.is_error_state()

    @pytest.mark.asyncio
    async def test_loop_with_errors(self):
        """Test loop handles errors gracefully."""
        call_count = 0

        async def failing_loop_func(state):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ValueError("Test error")
            return {"status": "ok"}

        loop = FeedbackLoop(
            name="failing_loop",
            loop_func=failing_loop_func,
            config=LoopConfig(max_iterations=5, error_threshold=2),
        )

        result = await loop.execute()

        assert len(result.errors) > 0
        assert result.iteration <= 5

    @pytest.mark.asyncio
    async def test_retry_decorator(self):
        """Test retry decorator with exponential backoff."""
        call_count = 0

        @with_retry(
            config=RetryConfig(
                max_retries=3,
                initial_delay=0.01,
                strategy="exponential_backoff",
            )
        )
        async def flaky_function():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Connection failed")
            return "success"

        result = await flaky_function()

        assert result == "success"
        assert call_count == 3


class TestGraphEngineering:
    """Tests for graph engineering module."""

    @pytest.mark.asyncio
    async def test_graph_execution(self):
        """Test basic graph execution."""
        execution_order = []

        async def node1(state):
            execution_order.append("node1")
            state.data["step1"] = True
            return state

        async def node2(state):
            execution_order.append("node2")
            state.data["step2"] = True
            return state

        builder = GraphBuilder("test_graph", "graph_001")
        builder.add_agent_node("node1", node1)
        builder.add_agent_node("node2", node2)
        builder.connect("start", "node1")
        builder.connect("node1", "node2")

        graph = builder.build()
        state = await graph.execute()

        assert state.status == "completed"
        assert state.data["step1"] is True
        assert state.data["step2"] is True
        assert execution_order == ["node1", "node2"]

    @pytest.mark.asyncio
    async def test_graph_with_error_handling(self):
        """Test graph error handling."""

        async def failing_node(state):
            raise ValueError("Node error")

        async def error_handler(state, error):
            state.data["error_handled"] = True
            return state

        node = GraphNode(
            node_id="failing_node",
            node_type=NodeType.AGENT,
            execute_func=failing_node,
            error_handler=error_handler,
        )

        graph = WorkflowGraph("error_test", "graph_002")
        graph.add_node(node)

        result = await node.execute(GraphState(graph_id="graph_002"))

        assert result.data["error_handled"] is True

    @pytest.mark.asyncio
    async def test_conditional_flow(self):
        """Test conditional edge traversal."""

        async def decider(state):
            state.data["decision"] = "high_risk"
            return state

        async def high_risk_handler(state):
            state.data["handled"] = "high_risk"
            return state

        builder = GraphBuilder("conditional_test", "graph_003")
        builder.add_agent_node("decider", decider)
        builder.add_agent_node("high_risk_handler", high_risk_handler)

        builder.connect(
            "start",
            "decider",
        )
        builder.connect(
            "decider",
            "high_risk_handler",
            condition=lambda s: s.data.get("decision") == "high_risk",
        )

        graph = builder.build()
        state = await graph.execute()

        assert state.data["handled"] == "high_risk"


class TestEvaluationPipeline:
    """Tests for evaluation pipeline."""

    @pytest.mark.asyncio
    async def test_single_evaluation(self):
        """Test single test case evaluation."""
        pipeline = EvaluationPipeline("test_pipeline")
        pipeline.register_evaluator(
            "relevance",
            RelevanceEvaluator(),
            threshold=0.5,
        )

        result = await pipeline.evaluate(
            test_case_id="test_001",
            predicted="Vendor has ISO 27001 certification",
            reference="Vendor has ISO certification",
            context={
                "query": "What certifications?",
                "required_topics": ["certification"],
            },
        )

        assert isinstance(result, EvaluationResult)
        assert result.test_case_id == "test_001"
        assert len(result.metrics) > 0

    @pytest.mark.asyncio
    async def test_batch_evaluation(self):
        """Test batch evaluation."""
        pipeline = EvaluationPipeline("batch_test")
        pipeline.register_evaluator(
            "accuracy",
            AccuracyEvaluator(),
            threshold=0.5,
        )

        test_cases = [
            {
                "id": f"test_{i}",
                "predicted": "Test response",
                "reference": "Test reference",
            }
            for i in range(3)
        ]

        results = await pipeline.evaluate_batch(test_cases)

        assert len(results) == 3
        assert all(isinstance(r, EvaluationResult) for r in results)

    @pytest.mark.asyncio
    async def test_pipeline_summary(self):
        """Test pipeline summary generation."""
        pipeline = EvaluationPipeline("summary_test")
        pipeline.register_evaluator(
            "relevance",
            RelevanceEvaluator(),
            threshold=0.5,
        )

        # Run an evaluation
        await pipeline.evaluate(
            test_case_id="test_001",
            predicted="Response text",
            context={"query": "Question"},
        )

        summary = pipeline.get_summary()

        assert "pipeline_name" in summary
        assert "total_evaluations" in summary
        assert "pass_rate" in summary
        assert summary["total_evaluations"] == 1


class TestIntegration:
    """Integration tests combining multiple modules."""

    @pytest.mark.asyncio
    async def test_loop_chain_execution(self):
        """Test chained loops."""
        from src.engineering.loop_engine import LoopChain

        async def loop1_func(state):
            return {"stage": 1, "progress": 0.5}

        async def loop2_func(state):
            return {"stage": 2, "progress": 1.0}

        loop1 = FeedbackLoop(
            name="loop1",
            loop_func=loop1_func,
            convergence_func=lambda r: r.get("progress", 0),
            config=LoopConfig(max_iterations=2),
        )

        loop2 = FeedbackLoop(
            name="loop2",
            loop_func=loop2_func,
            convergence_func=lambda r: r.get("progress", 0),
            config=LoopConfig(max_iterations=2),
        )

        chain = LoopChain("test_chain")
        chain.add_loop(loop1).add_loop(loop2)

        results = await chain.execute()

        assert "loop1" in results
        assert "loop2" in results
        assert results["loop1"].iteration >= 1

    @pytest.mark.asyncio
    async def test_graph_with_rag_context(self):
        """Test graph using RAG context."""
        from src.engineering.rag_engine import RAGContext

        rag_context = RAGContext(
            query="vendor compliance",
            retrieved_docs=[],
            retrieved_chunks=["Doc 1", "Doc 2"],
        )

        async def rag_aware_node(state):
            state.data["rag_context"] = rag_context
            return state

        builder = GraphBuilder("rag_graph", "graph_004")
        builder.add_agent_node("rag_aware", rag_aware_node)
        builder.connect("start", "rag_aware")

        graph = builder.build()
        state = await graph.execute()

        assert state.data["rag_context"].query == "vendor compliance"
        assert len(state.data["rag_context"].retrieved_chunks) == 2


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Run tests with: pytest tests/integration/test_engineering_modules.py -v
