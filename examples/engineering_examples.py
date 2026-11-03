"""Example integrations showing how to use the engineering modules."""

import asyncio
from typing import Dict, Any, List

from src.engineering.loop_engine import (
    FeedbackLoop,
    LoopChain,
    LoopConfig,
    LoopState,
    RetryConfig,
    with_retry,
)
from src.engineering.graph_engine import (
    WorkflowGraph,
    GraphBuilder,
    GraphNode,
    GraphState,
    NodeType,
)
from src.engineering.rag_engine import (
    RAGEngine,
    DocumentProcessor,
    ChromaVectorStore,
)
from src.engineering.observability import (
    ObservabilityManager,
    AgentCallTracker,
    trace_operation,
)
from src.engineering.evaluation_pipeline import (
    EvaluationPipeline,
    RelevanceEvaluator,
    create_vendor_risk_eval_pipeline,
)


# ============================================================================
# EXAMPLE 1: Loop Engineering - Vendor Risk Refinement Loop
# ============================================================================


async def vendor_risk_refinement_loop_example():
    """Example: Iterative refinement of vendor risk assessment."""
    print("=" * 80)
    print("EXAMPLE 1: Loop Engineering - Vendor Risk Refinement Loop")
    print("=" * 80)

    # Define the loop function
    async def refine_risk_assessment(state: LoopState) -> Dict[str, Any]:
        """Iteratively refine vendor risk assessment."""
        # Simulate risk assessment with convergence
        risk_score = 0.5 - (state.iteration * 0.1)  # Converges to lower score
        return {"risk_score": risk_score, "confidence": min(0.9, state.iteration * 0.2)}

    # Define convergence function
    def convergence_check(result: Dict[str, Any]) -> float:
        """Check convergence based on confidence."""
        return result.get("confidence", 0.0)

    # Create and execute loop
    loop_config = LoopConfig(max_iterations=5, convergence_threshold=0.7)
    loop = FeedbackLoop(
        name="vendor_risk_refinement",
        loop_func=refine_risk_assessment,
        convergence_func=convergence_check,
        config=loop_config,
    )

    result = await loop.execute()
    print(f"Loop completed in {result.get_duration():.2f}s")
    print(f"Iterations: {result.iteration}")
    print(f"Convergence score: {result.convergence_score:.2f}")
    print(f"Errors: {len(result.errors)}")
    print()


# ============================================================================
# EXAMPLE 2: Graph Engineering - Vendor Onboarding Workflow
# ============================================================================


async def vendor_onboarding_graph_example():
    """Example: Multi-agent vendor onboarding workflow using graphs."""
    print("=" * 80)
    print("EXAMPLE 2: Graph Engineering - Vendor Onboarding Workflow")
    print("=" * 80)

    # Define agent nodes
    async def document_processor(state: GraphState) -> GraphState:
        """Process vendor documents."""
        state.data["documents_processed"] = True
        state.data["document_count"] = 5
        return state

    async def kyc_validator(state: GraphState) -> GraphState:
        """Validate KYC information."""
        state.data["kyc_verified"] = True
        state.data["risk_flags"] = ["minor_flag"]
        return state

    async def risk_assessor(state: GraphState) -> GraphState:
        """Assess vendor risk."""
        state.data["risk_score"] = 0.35
        state.data["risk_level"] = "LOW"
        return state

    async def compliance_checker(state: GraphState) -> GraphState:
        """Check compliance requirements."""
        state.data["compliance_passed"] = True
        return state

    # Build workflow graph
    builder = GraphBuilder("vendor_onboarding", "workflow_001")
    builder.add_agent_node("document_processor", document_processor)
    builder.add_agent_node("kyc_validator", kyc_validator)
    builder.add_agent_node("risk_assessor", risk_assessor)
    builder.add_agent_node("compliance_checker", compliance_checker)

    # Connect nodes
    builder.connect("start", "document_processor")
    builder.connect("document_processor", "kyc_validator")
    builder.connect("kyc_validator", "risk_assessor")
    builder.connect("risk_assessor", "compliance_checker")

    graph = builder.build()

    # Execute workflow
    final_state = await graph.execute()

    print(f"Workflow completed with status: {final_state.status}")
    print(f"Visited nodes: {final_state.visited_nodes}")
    print(f"Final data: {final_state.data}")
    print(f"Errors: {len(final_state.errors)}")
    print()


# ============================================================================
# EXAMPLE 3: RAG Engine - Document Retrieval
# ============================================================================


async def rag_engine_example():
    """Example: RAG engine for document retrieval and context."""
    print("=" * 80)
    print("EXAMPLE 3: RAG Engine - Document Retrieval and Context")
    print("=" * 80)

    from langchain_core.documents import Document

    # Initialize RAG components
    doc_processor = DocumentProcessor(chunk_size=500, chunk_overlap=50)
    vector_store = ChromaVectorStore(collection_name="vendor_documents")
    rag_engine = RAGEngine(vector_store, doc_processor)

    # Create sample documents
    sample_docs = [
        Document(
            page_content="Vendor ABC is a leading technology provider with 20 years of experience.",
            metadata={"vendor_id": "abc_001", "doc_type": "overview"},
        ),
        Document(
            page_content="Risk assessment shows low financial risk with strong cash flow.",
            metadata={"vendor_id": "abc_001", "doc_type": "financial"},
        ),
        Document(
            page_content="Compliance certifications: ISO 27001, SOC 2 Type II approved.",
            metadata={"vendor_id": "abc_001", "doc_type": "compliance"},
        ),
    ]

    # Ingest documents
    await rag_engine.ingest_documents(sample_docs)

    # Retrieve relevant documents
    query = "What are the compliance certifications?"
    context = await rag_engine.retrieve(query, k=2)

    print(f"Query: {query}")
    print(f"Retrieved {len(context.retrieved_docs)} documents")
    print(f"Retrieval time: {context.metrics.retrieval_time:.2f}s")
    print(f"Average relevance: {context.metrics.avg_relevance:.2f}")
    print("\nContext:")
    print(context.get_context_string()[:500])
    print()


# ============================================================================
# EXAMPLE 4: Observability & Agent Call Tracking
# ============================================================================


async def observability_example():
    """Example: Observability and agent call tracking."""
    print("=" * 80)
    print("EXAMPLE 4: Observability & Agent Call Tracking")
    print("=" * 80)

    # Initialize observability
    obs_manager = ObservabilityManager(
        app_name="vendor_risk_system",
        environment="development",
        jaeger_host="localhost",
        jaeger_port=6831,
    )

    # Create agent call tracker
    call_tracker = AgentCallTracker(obs_manager)

    # Track some agent calls
    for i in range(3):
        call_id = await call_tracker.track_agent_call(
            agent_id="kyc_validator_001",
            agent_name="KYC Validator",
            input_data={"vendor_id": f"vendor_{i}", "data": "test"},
            output_data={"verified": True, "risk_flags": []},
            duration_ms=150.0 + i * 50,
        )
        print(f"Tracked agent call: {call_id}")

    # Get statistics
    stats = call_tracker.get_agent_stats("KYC Validator")
    print(f"\nAgent Statistics:")
    print(f"  Total calls: {stats['total_calls']}")
    print(f"  Success rate: {stats['success_rate']:.2%}")
    print(f"  Average duration: {stats['avg_duration_ms']:.2f}ms")

    # Record metrics
    obs_manager.record_metric(
        "vendor_processing_time",
        150.0,
        {"vendor": "ABC", "step": "kyc"},
    )

    metrics_summary = obs_manager.get_metrics_summary()
    print(f"\nMetrics Summary:")
    for metric_name, metric_data in metrics_summary.items():
        print(f"  {metric_name}: avg={metric_data['avg']:.2f}, "
              f"min={metric_data['min']:.2f}, max={metric_data['max']:.2f}")

    obs_manager.shutdown()
    print()


# ============================================================================
# EXAMPLE 5: Evaluation Pipeline - Quality Metrics
# ============================================================================


async def evaluation_pipeline_example():
    """Example: Evaluation pipeline for quality metrics."""
    print("=" * 80)
    print("EXAMPLE 5: Evaluation Pipeline - Quality Metrics")
    print("=" * 80)

    # Create evaluation pipeline for vendor risk assessment
    pipeline = create_vendor_risk_eval_pipeline()

    # Define test cases
    test_cases = [
        {
            "id": "test_001",
            "predicted": "Vendor ABC has strong ISO 27001 certification and low financial risk",
            "reference": "Vendor has ISO 27001 and good financial standing",
            "context": {
                "query": "What is the vendor's compliance status?",
                "latency_ms": 250,
                "required_topics": ["certification", "financial"],
            },
        },
        {
            "id": "test_002",
            "predicted": "The vendor probably has good operational efficiency",
            "reference": "Vendor has proven operational efficiency",
            "context": {
                "query": "Is the vendor operationally efficient?",
                "latency_ms": 500,
                "required_topics": ["efficiency", "operations"],
            },
        },
    ]

    # Run batch evaluation
    results = await pipeline.evaluate_batch(test_cases)

    # Display results
    for result in results:
        print(f"\nTest Case: {result.test_case_id}")
        print(f"  Passed: {result.passed}")
        print(f"  Metrics:")
        for metric in result.metrics:
            print(f"    {metric.name}: {metric.value:.2f} "
                  f"({'PASS' if metric.is_passed else 'FAIL'})")

    # Get summary
    summary = pipeline.get_summary()
    print(f"\nPipeline Summary:")
    print(f"  Pass rate: {summary['pass_rate']:.2%}")
    print(f"  Total evaluations: {summary['total_evaluations']}")
    print()


# ============================================================================
# EXAMPLE 6: Retry Logic with Loop Engineering
# ============================================================================


@with_retry(
    config=RetryConfig(
        max_retries=3,
        initial_delay=0.5,
        strategy="exponential_backoff",
    )
)
async def fetch_vendor_data_with_retry(vendor_id: str) -> Dict[str, Any]:
    """Fetch vendor data with automatic retry on failure."""
    # Simulate occasional failures
    import random

    if random.random() < 0.3:  # 30% failure rate
        raise Exception(f"Failed to fetch data for {vendor_id}")

    return {"vendor_id": vendor_id, "status": "active", "data": "example"}


async def retry_example():
    """Example: Retry logic with exponential backoff."""
    print("=" * 80)
    print("EXAMPLE 6: Retry Logic with Exponential Backoff")
    print("=" * 80)

    try:
        result = await fetch_vendor_data_with_retry("vendor_001")
        print(f"Successfully fetched: {result}")
    except Exception as e:
        print(f"Failed after all retries: {e}")
    print()


# ============================================================================
# Main Example Runner
# ============================================================================


async def main():
    """Run all examples."""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "ENGINEERING MODULES EXAMPLES" + " " * 30 + "║")
    print("╚" + "=" * 78 + "╝")
    print()

    # Run examples
    await vendor_risk_refinement_loop_example()
    await vendor_onboarding_graph_example()
    await rag_engine_example()
    await observability_example()
    await evaluation_pipeline_example()
    await retry_example()

    print("\n" + "=" * 80)
    print("All examples completed!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
