# LLMOps Guide

## Overview

LLMOps (Large Language Model Operations) is a comprehensive framework for managing, monitoring, and optimizing LLM-based applications. This guide covers all LLMOps components in the vendor risk onboarding system.

## 1. Model Registry

The Model Registry manages LLM versions, configurations, and lifecycle.

### Configuration Structure

```python
from src.llmops.config import ModelConfig, LLMProvider

config = ModelConfig(
    provider=LLMProvider.OPENAI,
    model_name="gpt-4",
    version="1.0.0",
    temperature=0.3,
    max_tokens=4096,
    top_p=0.95,
    frequency_penalty=0.0,
    presence_penalty=0.0,
    system_prompt="You are a vendor risk assessment expert...",
    tags={"use_case": "risk_assessment", "domain": "compliance"},
    metadata={"cost_optimized": True, "approved": True}
)
```

### Register Models

```python
from src.llmops.config import llmops_config

# Register model
llmops_config.register_model(config)

# Retrieve model
model = llmops_config.get_model(
    provider=LLMProvider.OPENAI,
    model_name="gpt-4",
    version="1.0.0"
)
```

### Model Versioning

Best practices for version management:

```
Semantic Versioning: MAJOR.MINOR.PATCH
- MAJOR: Breaking changes to model or configuration
- MINOR: Non-breaking improvements (new capabilities, better performance)
- PATCH: Bug fixes and minor optimizations
```

### Supported Providers

| Provider | Model Examples | Status |
|----------|---|---|
| OpenAI | gpt-4, gpt-3.5-turbo | ✅ Production |
| Azure OpenAI | Azure GPT-4, Azure GPT-3.5 | ✅ Production |
| Anthropic | claude-3-opus, claude-3-sonnet | ✅ Production |
| Ollama | llama2, mistral | ⚠️ Beta |
| HuggingFace | Any HF model | ⚠️ Development |

## 2. Prompt Management

Prompts are versioned templates that define LLM behavior for specific tasks.

### Prompt Structure

```python
from src.llmops.config import PromptConfig

prompt = PromptConfig(
    name="risk_assessment_prompt",
    version="2.0",
    template="""Analyze vendor risk:
    
Vendor: {vendor_name}
Industry: {industry}
Country: {country}
Financial Data: {financial_data}

Provide risk assessment with scores for:
1. KYC Risk (0-100)
2. Financial Risk (0-100)
3. Compliance Risk (0-100)
4. Operational Risk (0-100)

Format as JSON with scores and justification.""",
    description="Risk assessment prompt for vendor onboarding",
    variables=["vendor_name", "industry", "country", "financial_data"],
    tags={"domain": "compliance", "use_case": "risk_assessment"},
)

llmops_config.register_prompt(prompt)
```

### Prompt Optimization

**Template Variables**: Use {variable} syntax for dynamic content
```python
template = "Assess risk for {vendor_name} in {industry}..."
```

**Few-Shot Examples**: Include examples for better performance
```python
template = """Assess risk. Examples:
Example 1: [vendor] → [risk assessment]
Example 2: [vendor] → [risk assessment]

Now assess: {vendor_name}"""
```

**Chain-of-Thought**: Encourage reasoning
```python
template = """Think step by step:
1. What are the key risk factors?
2. How do they compare to benchmarks?
3. What is the overall risk level?

Vendor: {vendor_name}"""
```

### A/B Testing Prompts

```python
# Version 1.0: Original
prompt_v1 = PromptConfig(..., version="1.0", template="...")

# Version 1.1: Optimized
prompt_v1_1 = PromptConfig(..., version="1.1", template="...")

# Use in evaluation to compare
# Results stored in evaluation_results table
```

## 3. Evaluation Framework

The Evaluation Framework assesses quality of LLM outputs across multiple metrics.

### Evaluation Metrics

```python
from src.llmops.evaluator import (
    EvaluationMetricType,
    EvaluationCriteria,
    EvaluationFramework,
)

framework = EvaluationFramework()

# Define criteria
framework.add_criteria(EvaluationCriteria(
    metric_type=EvaluationMetricType.CORRECTNESS,
    threshold=0.85,
    weight=2.0,
))

framework.add_criteria(EvaluationCriteria(
    metric_type=EvaluationMetricType.FAITHFULNESS,
    threshold=0.80,
    weight=1.5,
))

framework.add_criteria(EvaluationCriteria(
    metric_type=EvaluationMetricType.RELEVANCE,
    threshold=0.75,
    weight=1.0,
))
```

### Available Metrics

| Metric | Description | Threshold |
|--------|-------------|-----------|
| CORRECTNESS | Output matches expected result | 0.85 |
| FAITHFULNESS | Output grounded in source | 0.80 |
| RELEVANCE | Output addresses query | 0.75 |
| COHERENCE | Output is logically consistent | 0.80 |
| CONSISTENCY | Output consistent across runs | 0.85 |
| LATENCY | Response time performance | <5s |
| COST | Token usage cost efficiency | Variable |
| COMPLETENESS | All required information present | 0.90 |

### Running Evaluations

```python
import asyncio

async def run_evaluation():
    framework = EvaluationFramework()
    
    # Add criteria
    framework.add_criteria(...)
    
    # Run evaluation
    results = await framework.evaluate(
        prediction="Risk Assessment: MEDIUM - Financial risk high...",
        reference="Expected assessment from expert...",
        query="What is the risk level for vendor X?"
    )
    
    print(results)
    # Output:
    # {
    #   "passed": True,
    #   "overall_score": 0.87,
    #   "metrics": [...]
    # }

asyncio.run(run_evaluation())
```

### Custom Evaluators

```python
from src.llmops.evaluator import Evaluator, EvaluationMetricType, EvaluationResult

class DomainExpertEvaluator(Evaluator):
    """Custom evaluator for domain-specific quality."""
    
    def __init__(self):
        super().__init__(EvaluationMetricType.CORRECTNESS)
    
    async def evaluate(self, prediction: str, reference: str, **kwargs):
        # Custom evaluation logic
        score = self._calculate_domain_score(prediction, reference)
        
        return EvaluationResult(
            metric_type=self.metric_type,
            score=score,
            passed=score >= 0.8,
            threshold=0.8,
            evidence=f"Domain assessment: {score}"
        )
    
    def _calculate_domain_score(self, pred, ref):
        # Custom scoring logic
        return 0.85

# Register custom evaluator
framework.register_evaluator(
    EvaluationMetricType.CORRECTNESS,
    DomainExpertEvaluator()
)
```

## 4. Monitoring & Observability

### Structured Logging

```python
from src.llmops.monitoring import logger

# Log structured events
logger.info(
    "vendor_assessment_completed",
    vendor_id="vendor-123",
    risk_level="MEDIUM",
    duration_seconds=45.2,
    model="gpt-4",
    cost=0.25
)
```

### Performance Tracking

```python
from src.llmops.monitoring import performance_monitor

with performance_monitor.track_operation("vendor_onboarding"):
    # Your operation code
    result = await orchestrate_workflow(vendor_id)
    
# Get metrics
summary = performance_monitor.get_summary()
# Output:
# {
#   "vendor_onboarding": {
#     "count": 10,
#     "avg_duration": 45.2,
#     "min_duration": 30.5,
#     "max_duration": 60.1,
#     "total_duration": 452.0
#   }
# }
```

### Cost Tracking

```python
from src.llmops.monitoring import cost_monitor

# Record LLM usage
cost = cost_monitor.record_usage(
    model_name="gpt-4",
    input_tokens=2000,
    output_tokens=500
)

# Get cost summary
summary = cost_monitor.get_cost_summary()
# Output:
# {
#   "total_cost": 12.50,
#   "cost_by_model": {"gpt-4": 10.25, "gpt-3.5-turbo": 2.25},
#   "usage_by_model": {...}
# }
```

### Distributed Tracing

Jaeger integration for distributed tracing:

```python
from src.llmops.monitoring import otel_monitor

span = otel_monitor.record_span(
    "vendor_assessment",
    attributes={
        "vendor_id": vendor_id,
        "model": "gpt-4",
        "risk_level": "MEDIUM"
    }
)
```

Access Jaeger UI at `http://localhost:16686` for trace visualization.

### Workflow Logging

```python
from src.llmops.monitoring import workflow_logger

# Log workflow events
workflow_logger.log_event(
    workflow_id="wf-123",
    event_type="step_completed",
    agent_name="risk_assessor",
    data={"risk_score": 75.5},
    status="success"
)

# Get workflow log
log = workflow_logger.get_workflow_log("wf-123")
# Output: List of timestamped events

# Export for analysis
json_export = workflow_logger.export_workflow_log("wf-123", format="json")
```

## 5. Configuration Management

### YAML Configuration

```yaml
# config/llmops_config.yaml
models:
  - provider: openai
    model_name: gpt-4
    version: "1.0.0"
    temperature: 0.3
    max_tokens: 4096
    tags:
      use_case: risk_assessment
      domain: compliance

prompts:
  - name: risk_assessment_prompt
    version: "2.0"
    template: |
      Assess vendor risk...
    variables: [vendor_name, industry, country]

evaluations:
  correctness:
    metric: correctness
    threshold: 0.85
    weight: 2.0
  faithfulness:
    metric: faithfulness
    threshold: 0.80
    weight: 1.5

monitoring:
  enabled: true
  trace_sample_rate: 1.0
  metrics_enabled: true
  jaeger_enabled: true
  langsmith_enabled: true
```

Load configuration:

```python
from src.llmops.config import llmops_config

llmops_config.load_from_yaml("config/llmops_config.yaml")
```

## 6. Integration with CI/CD

### GitHub Actions Example

```yaml
# .github/workflows/llmops.yml
name: LLMOps

on: [push, pull_request]

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      
      - name: Run evaluations
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          LANGSMITH_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
        run: |
          make evals
      
      - name: Upload results
        uses: actions/upload-artifact@v2
        with:
          name: evaluation-results
          path: evals/results/
```

## 7. Best Practices

### Model Management
- ✅ Version all models systematically
- ✅ Tag models by use case and domain
- ✅ Document model capabilities and limitations
- ✅ Regular performance audits

### Prompt Optimization
- ✅ Use clear, specific instructions
- ✅ Include examples (few-shot learning)
- ✅ Test prompt variations systematically
- ✅ Version prompts independently from code

### Evaluation
- ✅ Evaluate before and after changes
- ✅ Use multiple metrics for holistic assessment
- ✅ Set realistic thresholds based on domain
- ✅ Track evaluation trends over time

### Monitoring
- ✅ Monitor cost continuously
- ✅ Track latency at p50, p95, p99
- ✅ Alert on quality degradation
- ✅ Log all decisions for audit trail

### Cost Optimization
- ✅ Use cheaper models when appropriate (GPT-3.5 vs GPT-4)
- ✅ Implement prompt caching
- ✅ Batch requests when possible
- ✅ Monitor token usage patterns

## 8. Troubleshooting

### Common Issues

**Issue**: High latency in model inference
- **Solution**: Check model queue, increase worker concurrency

**Issue**: Quality degradation after update
- **Solution**: Run evaluations before deployment, use staging environment

**Issue**: Unexpected cost increase
- **Solution**: Check token usage, review model selections, enable caching

**Issue**: Inconsistent results
- **Solution**: Lower temperature, fix prompt, use specific examples

## 9. Advanced Topics

### Multi-Model Ensembles
Combine outputs from multiple models:

```python
# Aggregate risk scores from multiple models
scores = []
for model in ["gpt-4", "claude-3-opus"]:
    score = await assess_risk_with_model(vendor, model)
    scores.append(score)

ensemble_score = sum(scores) / len(scores)
```

### Continuous Improvement
- Track metrics over time
- Identify declining performance
- Automatically retrain/reconfigure models
- A/B test new prompts

### Custom Metrics
Implement domain-specific evaluation metrics using the custom evaluator pattern.

## References

- [LangChain Documentation](https://python.langchain.com)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph)
- [OpenTelemetry Documentation](https://opentelemetry.io)
- [Jaeger Documentation](https://www.jaegertracing.io)
