# Engineering Modules - Comprehensive Guide

## Overview

The engineering modules provide robust, production-ready components for building resilient multi-agent systems with observability, evaluation, and RAG capabilities. These modules are designed specifically for vendor risk onboarding but are applicable to any deep-research multi-agent system.

## Modules

### 1. Loop Engineering (`loop_engine.py`)

**Purpose**: Implement resilient feedback loops, retry logic, and iterative refinement patterns.

#### Key Components

- **FeedbackLoop**: Implements iterative refinement with convergence checking
- **LoopChain**: Chains multiple feedback loops together
- **RetryConfig**: Configuration for retry strategies
- **BackoffCalculator**: Calculates backoff delays with various strategies

#### Features

- Multiple retry strategies: exponential backoff, linear, constant, Fibonacci
- Jitter support to prevent thundering herd
- Convergence detection with custom functions
- Loop state tracking with metrics
- Error accumulation and threshold-based termination

#### Example: Vendor Risk Refinement

```python
from src.engineering.loop_engine import FeedbackLoop, LoopConfig

async def refine_assessment(state):
    # Iteratively improve assessment
    score = await llm.assess_vendor_risk(state.data)
    return {"score": score, "confidence": state.iteration / max_iterations}

loop = FeedbackLoop(
    name="risk_refinement",
    loop_func=refine_assessment,
    convergence_func=lambda r: r["confidence"],
    config=LoopConfig(max_iterations=5, convergence_threshold=0.8)
)

result = await loop.execute()
print(f"Converged at iteration {result.iteration}")
```

#### Use Cases

- Multi-turn LLM refinement
- Iterative document analysis
- Risk score convergence
- A/B testing refinement loops

---

### 2. Graph Engineering (`graph_engine.py`)

**Purpose**: Build robust workflow graphs with state management, error handling, and execution tracking.

#### Key Components

- **WorkflowGraph**: Core graph implementation with nodes and edges
- **GraphNode**: Represents an agent or processing step
- **GraphEdge**: Connections between nodes with conditional logic
- **GraphBuilder**: Fluent API for constructing graphs
- **GraphState**: State object for workflow execution

#### Features

- Conditional flow logic
- Error recovery paths
- Automatic retry on node failure
- Comprehensive execution metrics
- Path tracking and node performance stats

#### Example: Vendor Onboarding Workflow

```python
from src.engineering.graph_engine import GraphBuilder, GraphState, END

builder = GraphBuilder("vendor_onboarding", "wf_001")

# Add nodes
builder.add_agent_node("doc_processor", document_processor_agent)
builder.add_agent_node("kyc_validator", kyc_validator_agent)
builder.add_agent_node("risk_assessor", risk_assessor_agent)
builder.add_agent_node("report_generator", report_generator_agent)

# Add edges
builder.connect("start", "doc_processor")
builder.connect("doc_processor", "kyc_validator")
builder.connect("kyc_validator", "risk_assessor")
builder.connect("risk_assessor", "report_generator")

# Add conditional error path
builder.add_error_path("kyc_validator", "error_handler")

graph = builder.build()
final_state = await graph.execute()
```

#### Node Types

- **AGENT**: Executes agent logic
- **DECISION**: Makes conditional decisions
- **AGGREGATOR**: Combines multiple inputs
- **ERROR_HANDLER**: Handles errors
- **VALIDATOR**: Validates data
- **TRANSFORMER**: Transforms data

#### Edge Types

- **NORMAL**: Standard flow
- **CONDITIONAL**: Conditional execution
- **ERROR**: Error recovery path
- **RETRY**: Retry path
- **BYPASS**: Skip nodes

---

### 3. RAG Engine (`rag_engine.py`)

**Purpose**: Implement Retrieval-Augmented Generation with multiple vector stores.

#### Key Components

- **RAGEngine**: Main orchestrator for RAG operations
- **DocumentProcessor**: Chunks and prepares documents
- **ChromaVectorStore**: Chroma-based vector storage
- **FAISSVectorStore**: FAISS-based vector storage (CPU)
- **RAGContext**: Context with retrieved documents and metrics

#### Features

- Multiple vector store backends
- Configurable chunking strategies
- Similarity-based retrieval
- Relevance scoring
- Retrieval metrics and history
- Batch document ingestion

#### Example: RAG for Vendor Documents

```python
from src.engineering.rag_engine import RAGEngine, ChromaVectorStore
from src.engineering.rag_engine import DocumentProcessor
from langchain_core.documents import Document

# Initialize RAG
processor = DocumentProcessor(chunk_size=1000, chunk_overlap=200)
vector_store = ChromaVectorStore("vendor_docs")
rag = RAGEngine(vector_store, processor)

# Load documents
docs = [
    Document(page_content="...", metadata={"vendor": "ABC"}),
    # ... more documents
]
await rag.ingest_documents(docs)

# Retrieve context for query
context = await rag.retrieve(
    query="What are ABC's compliance certifications?",
    k=5,
    threshold=0.5
)

print(f"Retrieved {len(context.retrieved_docs)} documents")
print(f"Context:\n{context.get_context_string()}")
```

#### Vector Store Backends

| Store | Use Case | Advantages |
|-------|----------|-----------|
| **Chroma** | Production RAG | Persistent, distributed, multi-modal |
| **FAISS** | High-performance retrieval | CPU/GPU optimized, in-memory fast |

#### Configuration

```python
# Chroma with persistence
vector_store = ChromaVectorStore(
    collection_name="vendor_docs",
    persist_directory="/data/chroma"
)

# FAISS with index persistence
vector_store = FAISSVectorStore(
    store_name="vendor_docs",
    index_path="/data/faiss/vendor_docs.index"
)
```

---

### 4. Observability (`observability.py`)

**Purpose**: Comprehensive observability with distributed tracing, metrics, and logs using open-source standards.

#### Key Components

- **ObservabilityManager**: Central observability coordinator
- **AgentCallTracker**: Tracks agentic AI interactions
- **SpanContext**: Represents distributed trace spans
- **Instrumentors**: Auto-instrumentation for libraries

#### Features

- Distributed tracing with Jaeger/Tempo
- Prometheus metrics
- Structured logging with OpenTelemetry
- Auto-instrumentation for FastAPI, SQLAlchemy, requests
- Agent call history and statistics
- Span context management

#### Example: Setup and Tracking

```python
from src.engineering.observability import (
    ObservabilityManager,
    AgentCallTracker,
    trace_operation
)

# Initialize observability
obs = ObservabilityManager(
    app_name="vendor_risk_system",
    environment="production",
    jaeger_host="localhost",
    jaeger_port=6831,
    otlp_exporter_endpoint="localhost:4317"
)

# Instrument applications
obs.instrument_fastapi(app)
obs.instrument_sqlalchemy(db_engine)

# Track agent calls
tracker = AgentCallTracker(obs)

await tracker.track_agent_call(
    agent_id="kyc_001",
    agent_name="KYC Validator",
    input_data=vendor_data,
    output_data=validation_result,
    duration_ms=250
)

# Get statistics
stats = tracker.get_agent_stats("KYC Validator")
print(f"Success rate: {stats['success_rate']:.2%}")
print(f"Avg duration: {stats['avg_duration_ms']:.2f}ms")
```

#### Using Decorated Operations

```python
from src.engineering.observability import trace_operation

@trace_operation("assess_vendor_risk")
async def assess_vendor(vendor_id: str):
    # Operation is automatically traced
    return await risk_model.predict(vendor_id)
```

#### Observability Stack

```
Application
    ↓
OpenTelemetry (tracing, metrics, logs)
    ↓
    ├─→ Jaeger/Tempo (distributed traces)
    ├─→ Prometheus (metrics)
    └─→ Structured logs
    ↓
Grafana (visualization & dashboards)
```

#### Configuration

```yaml
# docker-compose.yml additions for observability
services:
  jaeger:
    image: jaegertracing/all-in-one
    ports:
      - "6831:6831/udp"  # Jaeger agent
      - "16686:16686"    # UI
  
  prometheus:
    image: prom/prometheus
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"
  
  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
    volumes:
      - grafana_storage:/var/lib/grafana
```

---

### 5. Evaluation Pipeline (`evaluation_pipeline.py`)

**Purpose**: Comprehensive quality metrics and evaluation framework for multi-agent systems.

#### Key Components

- **EvaluationPipeline**: Main evaluation orchestrator
- **MetricEvaluator**: Base class for metric implementations
- **Specific Evaluators**:
  - RelevanceEvaluator: Query-response relevance
  - AccuracyEvaluator: Prediction accuracy
  - HallucinationEvaluator: Unsupported claim detection
  - CoverageEvaluator: Topic coverage
  - LatencyEvaluator: Response time
- **EvaluationResult**: Result object with metrics

#### Features

- Pre-built evaluators for common metrics
- Batch evaluation with async execution
- Configurable pass/fail thresholds
- Metric history and reporting
- Export results in JSON/CSV

#### Example: Quality Evaluation

```python
from src.engineering.evaluation_pipeline import (
    create_vendor_risk_eval_pipeline,
    EvaluationPipeline,
    RelevanceEvaluator,
    AccuracyEvaluator,
)

# Use pre-built pipeline for vendor risk
pipeline = create_vendor_risk_eval_pipeline()

# Or create custom pipeline
pipeline = EvaluationPipeline("custom_eval")
pipeline.register_evaluator(
    "relevance",
    RelevanceEvaluator(),
    threshold=0.7
)
pipeline.register_evaluator(
    "accuracy", 
    AccuracyEvaluator(),
    threshold=0.8
)

# Evaluate single test case
result = await pipeline.evaluate(
    test_case_id="test_001",
    predicted="The vendor is ISO 27001 certified",
    reference="Vendor has ISO 27001 certification",
    context={
        "query": "What certifications does the vendor have?",
        "latency_ms": 250,
        "required_topics": ["certification"]
    }
)

print(f"Test passed: {result.passed}")
for metric in result.metrics:
    print(f"  {metric.name}: {metric.value:.2f}")

# Evaluate batch
test_cases = [...]
batch_results = await pipeline.evaluate_batch(test_cases)

# Get summary
summary = pipeline.get_summary()
print(f"Pass rate: {summary['pass_rate']:.2%}")
```

#### Built-in Evaluators

| Evaluator | Purpose | Score Range |
|-----------|---------|------------|
| **Relevance** | Query-response relevance | 0-1 |
| **Accuracy** | Prediction accuracy | 0-1 |
| **Hallucination** | Unsupported claim rate | 0-1 (0=no hallucination) |
| **Coverage** | Topic coverage completeness | 0-1 |
| **Latency** | Response time performance | 0-1 |

#### Vendor Risk Assessment Metrics

```python
pipeline = create_vendor_risk_eval_pipeline()
# Registers:
# - relevance: threshold=0.7
# - accuracy: threshold=0.8
# - hallucination: threshold=0.3 (low is good)
# - coverage: threshold=0.8
# - latency: threshold=0.7 (target 2000ms)
```

---

## Integration with Agents

### Step 1: Update Orchestrator Agent

```python
from src.engineering.observability import AgentCallTracker
from src.engineering.graph_engine import GraphBuilder
from src.engineering.rag_engine import RAGEngine

class EnhancedOrchestratorAgent:
    def __init__(self, obs_manager, rag_engine):
        self.tracker = AgentCallTracker(obs_manager)
        self.rag = rag_engine
        
    async def orchestrate_vendor_onboarding(self, vendor_id, documents):
        # Use graph for workflow
        graph = self._build_workflow_graph()
        
        # Track agent calls
        await self.tracker.track_agent_call(
            agent_id="orchestrator",
            agent_name="Orchestrator",
            input_data={"vendor_id": vendor_id}
        )
        
        # Use RAG for document context
        context = await self.rag.retrieve(
            f"vendor {vendor_id} compliance requirements"
        )
        
        # Execute workflow graph
        return await graph.execute()
```

### Step 2: Add RAG to API

```python
from src.engineering.rag_engine import RAGEngine, ChromaVectorStore

@app.post("/vendors/{vendor_id}/documents")
async def ingest_vendor_documents(vendor_id: str, files: List[UploadFile]):
    docs = [Document(page_content=content) for content in files]
    await rag_engine.ingest_documents(docs)
    return {"status": "ingested", "count": len(docs)}

@app.get("/vendors/{vendor_id}/context")
async def get_vendor_context(vendor_id: str, query: str):
    context = await rag_engine.retrieve(f"{vendor_id} {query}", k=5)
    return {
        "documents": len(context.retrieved_docs),
        "relevance": context.metrics.avg_relevance,
        "context": context.get_context_string()
    }
```

### Step 3: Add Observability to API

```python
from fastapi import FastAPI
from src.engineering.observability import ObservabilityManager

app = FastAPI()
obs = ObservabilityManager("vendor_risk_api", "production")
obs.instrument_fastapi(app)

@app.middleware("http")
async def observability_middleware(request, call_next):
    with obs.create_span(
        operation_name=f"{request.method} {request.url.path}",
        attributes={"user": request.headers.get("x-user-id")}
    ):
        response = await call_next(request)
    return response
```

---

## Deployment with Docker Compose

```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - JAEGER_HOST=jaeger
      - PROMETHEUS_PUSHGATEWAY=prometheus:9091
    depends_on:
      - postgres
      - redis
      - jaeger
      - prometheus
      - grafana

  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "6831:6831/udp"
      - "16686:16686"

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards
      - ./monitoring/grafana/datasources:/etc/grafana/provisioning/datasources

  postgres:
    image: postgres:15
    environment:
      - POSTGRES_PASSWORD=postgres

  redis:
    image: redis:7-alpine
```

---

## Monitoring Dashboard in Grafana

### Key Metrics to Track

1. **Agent Performance**
   - Call count by agent
   - Success rate %
   - Average latency (ms)
   - Error rate

2. **Workflow Execution**
   - Graph node execution time
   - Path length distribution
   - Error recovery rate

3. **RAG System**
   - Retrieval latency
   - Average relevance score
   - Documents retrieved per query

4. **Evaluation Metrics**
   - Pass/fail rate
   - Average metric scores
   - Metric distributions

---

## Best Practices

### Loop Engineering

1. **Always set max_iterations** to prevent infinite loops
2. **Use convergence functions** for early termination
3. **Monitor error accumulation** and set thresholds
4. **Test with different retry strategies** for your use case
5. **Add jitter** to retry delays to prevent thundering herd

### Graph Engineering

1. **Design modular nodes** with single responsibilities
2. **Add error handlers** for critical nodes
3. **Use conditional edges** for dynamic workflows
4. **Monitor node performance** metrics
5. **Test node ordering** for optimal execution

### RAG Engine

1. **Tune chunk_size and overlap** based on your documents
2. **Choose vector store** based on scale and latency needs
3. **Monitor retrieval quality** with relevance metrics
4. **Implement caching** for frequently retrieved documents
5. **Update document index** regularly with new data

### Observability

1. **Use span attributes** for filtering and analysis
2. **Sample traces** in high-throughput scenarios
3. **Set up alerts** for high error rates and latency
4. **Regularly review** observability data
5. **Use structured logging** consistently

### Evaluation

1. **Start with pre-built pipelines** then customize
2. **Set realistic thresholds** based on business requirements
3. **Evaluate both success and failure cases**
4. **Track metric trends** over time
5. **Automate evaluation** in CI/CD pipeline

---

## Common Patterns

### Self-Correcting Agent Loop

```python
# Use feedback loop for agent self-correction
loop = FeedbackLoop(
    name="agent_self_correction",
    loop_func=agent_generate_and_refine,
    convergence_func=evaluate_quality,
    config=LoopConfig(max_iterations=3)
)
```

### Resilient Multi-Step Workflow

```python
# Use graph for resilient multi-step workflows
graph = GraphBuilder("resilient_workflow", workflow_id)
for agent, next_agent in zip(agents, agents[1:]):
    graph.add_agent_node(agent.name, agent.execute)
    graph.connect(agent.name, next_agent.name)
    graph.add_error_path(agent.name, error_handler.name)
```

### Retrieval-Enhanced Agent

```python
# Enhance agent with RAG context
context = await rag_engine.retrieve(query)
agent_input = {
    "query": query,
    "context": context.get_context_string(),
    "retrieved_docs": len(context.retrieved_docs)
}
result = await agent.execute(agent_input)
```

### Traced Execution with Metrics

```python
@trace_operation("vendor_assessment")
async def assess_vendor(vendor_id):
    obs_manager.record_metric("assessment_start", 1)
    result = await orchestrator.assess(vendor_id)
    obs_manager.record_metric("assessment_duration", elapsed_ms)
    return result
```

---

## Troubleshooting

### Loop Not Converging

1. Check convergence function returns values between 0-1
2. Increase max_iterations if needed
3. Lower convergence_threshold for faster termination
4. Check loop_func is actually improving results

### Graph Execution Stalling

1. Check node connections are defined
2. Verify nodes complete and return state
3. Add timeout to prevent infinite waiting
4. Review node metrics for bottlenecks

### RAG Retrieval Quality Issues

1. Verify documents are properly ingested
2. Check chunk size and overlap settings
3. Review relevance threshold
4. Try different vector stores

### Observability Not Showing Data

1. Verify Jaeger/Prometheus are running
2. Check OTLP endpoint is reachable
3. Ensure instrumentation is initialized before app starts
4. Review OpenTelemetry debug logs

---

## Performance Optimization

### Caching

```python
from functools import lru_cache

@lru_cache(maxsize=1000)
async def cached_retrieval(query: str):
    return await rag_engine.retrieve(query)
```

### Batching

```python
# Batch multiple evaluations
results = await pipeline.evaluate_batch(test_cases)  # More efficient
```

### Parallelization

```python
# Use asyncio for concurrent operations
tasks = [
    agent1.execute(data),
    agent2.execute(data),
    agent3.execute(data),
]
results = await asyncio.gather(*tasks)
```

---

## Next Steps

1. Review the examples in `examples/engineering_examples.py`
2. Run the examples: `python -m examples.engineering_examples`
3. Integrate one module at a time into your system
4. Set up observability stack with Docker Compose
5. Configure Grafana dashboards for monitoring
6. Add evaluation tests to CI/CD pipeline

---

## Support & References

- **OpenTelemetry**: https://opentelemetry.io/
- **Jaeger**: https://www.jaegertracing.io/
- **Grafana**: https://grafana.com/
- **Prometheus**: https://prometheus.io/
- **Chroma**: https://docs.trychroma.com/
- **FAISS**: https://github.com/facebookresearch/faiss
- **LangChain**: https://python.langchain.com/
