"""Tests for LLMOps evaluation framework."""

import pytest
from src.llmops.evaluator import (
    EvaluationFramework,
    EvaluationCriteria,
    EvaluationMetricType,
    CorrectnessEvaluator,
    FaithfulnessEvaluator,
    RelevanceEvaluator,
)


@pytest.mark.unit
@pytest.mark.llmops
class TestEvaluationFramework:
    """Tests for evaluation framework."""

    @pytest.fixture
    def framework(self):
        """Create evaluation framework."""
        return EvaluationFramework()

    def test_framework_initialization(self, framework):
        """Test framework initialization."""
        assert framework is not None
        assert len(framework.evaluators) > 0
        assert len(framework.criteria) == 0

    def test_add_criteria(self, framework):
        """Test adding evaluation criteria."""
        criteria = EvaluationCriteria(
            metric_type=EvaluationMetricType.CORRECTNESS,
            threshold=0.8,
            weight=1.0,
        )

        framework.add_criteria(criteria)

        assert len(framework.criteria) == 1
        assert framework.criteria[0].metric_type == EvaluationMetricType.CORRECTNESS

    def test_register_evaluator(self, framework):
        """Test registering custom evaluator."""
        custom_evaluator = CorrectnessEvaluator()

        framework.register_evaluator(EvaluationMetricType.CORRECTNESS, custom_evaluator)

        assert framework.evaluators[EvaluationMetricType.CORRECTNESS] == custom_evaluator

    @pytest.mark.asyncio
    async def test_correctness_evaluation(self):
        """Test correctness evaluation."""
        evaluator = CorrectnessEvaluator()

        result = await evaluator.evaluate(
            prediction="Paris",
            reference="Paris",
        )

        assert result.passed
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_faithfulness_evaluation(self):
        """Test faithfulness evaluation."""
        evaluator = FaithfulnessEvaluator()

        source = "The capital of France is Paris."
        prediction = "Paris is the capital of France and has many museums."

        result = await evaluator.evaluate(
            prediction=prediction,
            source_context=source,
        )

        assert result.metric_type == EvaluationMetricType.FAITHFULNESS
        assert result.score >= 0.0

    @pytest.mark.asyncio
    async def test_relevance_evaluation(self):
        """Test relevance evaluation."""
        evaluator = RelevanceEvaluator()

        query = "What is the capital of France?"
        prediction = "Paris is the capital of France."

        result = await evaluator.evaluate(
            prediction=prediction,
            query=query,
        )

        assert result.metric_type == EvaluationMetricType.RELEVANCE
        assert result.score > 0.0

    @pytest.mark.asyncio
    async def test_evaluate_with_multiple_criteria(self, framework):
        """Test evaluation with multiple criteria."""
        framework.add_criteria(
            EvaluationCriteria(
                metric_type=EvaluationMetricType.CORRECTNESS,
                threshold=0.8,
            )
        )
        framework.add_criteria(
            EvaluationCriteria(
                metric_type=EvaluationMetricType.RELEVANCE,
                threshold=0.7,
            )
        )

        summary = await framework.evaluate(
            prediction="Test prediction",
            reference="Test prediction",
        )

        assert "metrics" in summary
        assert "overall_score" in summary
        assert "passed" in summary

    def test_get_summary(self, framework):
        """Test getting evaluation summary."""
        framework.add_criteria(
            EvaluationCriteria(
                metric_type=EvaluationMetricType.CORRECTNESS,
                threshold=0.8,
            )
        )

        summary = framework.get_summary()

        assert "passed" in summary
        assert "overall_score" in summary
        assert "metrics" in summary

    def test_export_results_json(self, framework):
        """Test exporting results as JSON."""
        json_export = framework.export_results(format="json")

        assert isinstance(json_export, str)
        assert "passed" in json_export
