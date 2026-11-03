# Observability & Monitoring Setup Guide

## Quick Start: 5-Minute Setup

### 1. Start Observability Stack

```bash
docker-compose -f docker-compose.observability.yml up -d
```

### 2. Configure Application

```python
from src.engineering.observability import ObservabilityManager

obs = ObservabilityManager(
    app_name="vendor_risk_system",
    environment="production",
    jaeger_host="localhost",
    jaeger_port=6831,
    otlp_exporter_endpoint="localhost:4317"
)

# Instrument FastAPI
obs.instrument_fastapi(app)
```

### 3. Access Dashboards

- **Jaeger Traces**: http://localhost:16686
- **Prometheus Metrics**: http://localhost:9090
- **Grafana Dashboards**: http://localhost:3000 (admin/admin)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Application (Vendor Risk)                │
│  - FastAPI endpoints                                         │
│  - Agent orchestration                                       │
│  - RAG retrieval                                             │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ↓              ↓              ↓
    ┌────────┐    ┌────────┐    ┌───────────┐
    │ Traces │    │Metrics │    │Structured │
    │        │    │        │    │Logs       │
    └───┬────┘    └───┬────┘    └─────┬─────┘
        │             │               │
        ├─────────────┼───────────────┤
        │             │               │
        ↓             ↓               ↓
    ┌─────────────────────────────────────┐
    │   OpenTelemetry Collection Layer    │
    └───┬──────────────┬──────────────┬───┘
        │              │              │
        ↓              ↓              ↓
    ┌───────┐  ┌────────────┐  ┌──────────┐
    │ Jaeger│  │Prometheus  │  │ Log Store│
    │(Tempo)│  │(Collector) │  │          │
    └───┬───┘  └──────┬─────┘  └──────────┘
        │             │
        └─────┬───────┘
              │
              ↓
        ┌────────────┐
        │  Grafana   │
        │ Dashboards │
        └────────────┘
```

---

## Docker Compose Configuration

### docker-compose.observability.yml

```yaml
version: '3.8'

services:
  # Jaeger for distributed tracing (compatible with Tempo)
  jaeger:
    image: jaegertracing/all-in-one:1.48
    environment:
      - COLLECTOR_ZIPKIN_HOST_PORT=:9411
      - COLLECTOR_OTLP_ENABLED=true
    ports:
      - "6831:6831/udp"     # Jaeger agent
      - "14268:14268"       # Collector
      - "14250:14250"       # OTLP gRPC
      - "16686:16686"       # UI
    volumes:
      - jaeger_data:/badger

  # Prometheus for metrics collection
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'

  # Grafana for visualization
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_SECURITY_ADMIN_USER=admin
      - GF_INSTALL_PLUGINS=grafana-piechart-panel
    volumes:
      - grafana_storage:/var/lib/grafana
      - ./monitoring/grafana/provisioning/datasources:/etc/grafana/provisioning/datasources
      - ./monitoring/grafana/provisioning/dashboards:/etc/grafana/provisioning/dashboards
    depends_on:
      - prometheus
      - jaeger

  # Redis for caching
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  # PostgreSQL for application data
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: vendor_risk
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  # Loki for log aggregation (optional, advanced)
  loki:
    image: grafana/loki:latest
    ports:
      - "3100:3100"
    volumes:
      - ./monitoring/loki-config.yml:/etc/loki/local-config.yaml
      - loki_data:/loki

  # Tempo for long-term trace storage (optional, advanced)
  tempo:
    image: grafana/tempo:latest
    ports:
      - "3200:3200"
      - "4317:4317"
    volumes:
      - ./monitoring/tempo-config.yml:/etc/tempo.yml
      - tempo_data:/var/tempo

volumes:
  jaeger_data:
  prometheus_data:
  grafana_storage:
  redis_data:
  postgres_data:
  loki_data:
  tempo_data:

networks:
  default:
    name: vendor_risk_network
```

---

## Prometheus Configuration

### monitoring/prometheus.yml

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    cluster: 'vendor_risk'
    environment: 'production'

scrape_configs:
  # Scrape Prometheus itself
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  # Scrape application metrics
  - job_name: 'vendor_risk_app'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 10s

  # Scrape Jaeger metrics
  - job_name: 'jaeger'
    static_configs:
      - targets: ['localhost:14269']

  # Scrape Redis metrics (if using redis-exporter)
  - job_name: 'redis'
    static_configs:
      - targets: ['localhost:6379']

alerting:
  alertmanagers:
    - static_configs:
        - targets: []

rule_files:
  - './monitoring/alert_rules.yml'
```

### monitoring/alert_rules.yml

```yaml
groups:
  - name: vendor_risk_alerts
    interval: 30s
    rules:
      - alert: HighErrorRate
        expr: rate(vendor_agent_errors_total[5m]) > 0.1
        for: 5m
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value | humanize }}%"

      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(vendor_operation_duration_ms_bucket[5m])) > 2000
        for: 5m
        annotations:
          summary: "High latency detected"
          description: "P95 latency is {{ $value | humanize }}ms"

      - alert: LowRAGRelevance
        expr: avg(rag_retrieval_relevance) < 0.6
        for: 10m
        annotations:
          summary: "Low RAG retrieval relevance"
          description: "Average relevance score is {{ $value }}"

      - alert: EvaluationFailureRate
        expr: rate(evaluation_failures_total[5m]) / rate(evaluation_total[5m]) > 0.2
        for: 5m
        annotations:
          summary: "High evaluation failure rate"
          description: "Failure rate is {{ $value | humanize }}%"
```

---

## Grafana Dashboard Setup

### 1. Add Data Sources

```bash
# Via API
curl -X POST http://localhost:3000/api/datasources \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Prometheus",
    "type": "prometheus",
    "url": "http://prometheus:9090",
    "access": "proxy",
    "isDefault": true
  }'

curl -X POST http://localhost:3000/api/datasources \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Jaeger",
    "type": "jaeger",
    "url": "http://jaeger:16686",
    "access": "proxy"
  }'
```

### 2. Key Metrics to Dashboard

```json
{
  "dashboard": {
    "title": "Vendor Risk Monitoring",
    "panels": [
      {
        "title": "Agent Success Rate",
        "targets": [
          {
            "expr": "sum(rate(vendor_agent_success_total[5m])) / sum(rate(vendor_agent_calls_total[5m]))"
          }
        ]
      },
      {
        "title": "Workflow Execution Time",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, rate(workflow_execution_duration_ms_bucket[5m]))"
          }
        ]
      },
      {
        "title": "RAG Retrieval Quality",
        "targets": [
          {
            "expr": "avg(rag_retrieval_relevance) by (collection)"
          }
        ]
      },
      {
        "title": "Evaluation Pass Rate",
        "targets": [
          {
            "expr": "sum(rate(evaluation_passed_total[5m])) / sum(rate(evaluation_total[5m]))"
          }
        ]
      }
    ]
  }
}
```

### 3. Jaeger Trace Queries

```
# Find traces by service
service.name = "vendor_risk_system"

# Find slow orchestrator calls
service.name = "vendor_risk_system" AND operation_name = "orchestrate_vendor_onboarding" AND duration > 5000000

# Find error traces
service.name = "vendor_risk_system" AND error = true

# Find traces by vendor
service.name = "vendor_risk_system" AND vendor_id = "abc_001"
```

---

## Metrics Reference

### Agent Metrics

```python
# Automatically collected
vendor_agent_calls_total          # Counter: Total agent calls
vendor_agent_success_total        # Counter: Successful calls
vendor_agent_errors_total         # Counter: Failed calls
vendor_agent_duration_ms          # Histogram: Call duration
vendor_agent_success_rate         # Gauge: Success rate (0-1)
```

### Workflow Metrics

```python
workflow_execution_total          # Counter: Total executions
workflow_nodes_executed           # Counter: Nodes executed
workflow_errors_total             # Counter: Workflow errors
workflow_execution_duration_ms    # Histogram: Execution time
workflow_avg_path_length          # Gauge: Average node count per execution
```

### RAG Metrics

```python
rag_retrieval_total               # Counter: Total retrievals
rag_retrieval_duration_ms         # Histogram: Retrieval time
rag_retrieval_relevance           # Gauge: Average relevance score
rag_documents_retrieved           # Histogram: Document count
rag_chunks_processed              # Counter: Chunks processed
```

### Evaluation Metrics

```python
evaluation_total                  # Counter: Total evaluations
evaluation_passed_total           # Counter: Passed evaluations
evaluation_failed_total           # Counter: Failed evaluations
evaluation_pass_rate              # Gauge: Pass rate (0-1)
evaluation_metric_{metric_name}   # Gauge: Individual metric scores
evaluation_duration_ms            # Histogram: Evaluation time
```

---

## Environment Variables

```bash
# Observability Configuration
JAEGER_HOST=localhost
JAEGER_PORT=6831
JAEGER_SAMPLER_TYPE=const
JAEGER_SAMPLER_PARAM=1

# OTLP Configuration (for Tempo)
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc

# Application Environment
APP_NAME=vendor_risk_system
APP_ENV=production
LOG_LEVEL=INFO

# Prometheus Configuration
PROMETHEUS_MULTIPROC_DIR=/tmp
PROMETHEUS_GATEWAY=localhost:9091
```

---

## Application Integration

### 1. Initialize Observability in Main App

```python
# main.py
from fastapi import FastAPI
from src.engineering.observability import ObservabilityManager
from src.config.settings import settings

# Initialize observability
obs = ObservabilityManager(
    app_name=settings.app_name,
    environment=settings.app_env,
    jaeger_host=settings.jaeger_host,
    jaeger_port=settings.jaeger_port,
    otlp_exporter_endpoint=settings.otlp_endpoint,
)

app = FastAPI()

# Instrument frameworks
obs.instrument_fastapi(app)
obs.instrument_sqlalchemy(db_engine)
obs.instrument_requests()
obs.instrument_asyncio()

@app.on_event("shutdown")
async def shutdown():
    obs.shutdown()
```

### 2. Track Agent Calls

```python
# orchestrator.py
from src.engineering.observability import AgentCallTracker

tracker = AgentCallTracker(obs)

async def run_kyc_validation(vendor_id):
    import time
    start = time.time()
    
    try:
        result = await kyc_agent.validate(vendor_id)
        await tracker.track_agent_call(
            agent_id="kyc_001",
            agent_name="KYC Validator",
            input_data={"vendor_id": vendor_id},
            output_data=result,
            duration_ms=(time.time() - start) * 1000
        )
        return result
    except Exception as e:
        await tracker.track_agent_call(
            agent_id="kyc_001",
            agent_name="KYC Validator",
            input_data={"vendor_id": vendor_id},
            error=str(e),
            duration_ms=(time.time() - start) * 1000
        )
        raise
```

### 3. Export Prometheus Metrics

```python
# api/main.py
from prometheus_client import REGISTRY

@app.get("/metrics")
async def metrics():
    from prometheus_client import generate_latest
    return Response(generate_latest(REGISTRY), media_type="text/plain")
```

---

## Troubleshooting

### Jaeger UI showing no traces

1. Check Jaeger container is running: `docker logs jaeger`
2. Verify application can reach Jaeger: `telnet localhost 6831`
3. Check OpenTelemetry is initialized before FastAPI startup
4. Verify span processor is added to tracer provider

### Prometheus not scraping metrics

1. Check Prometheus target health: http://localhost:9090/targets
2. Verify `/metrics` endpoint is accessible: `curl localhost:8000/metrics`
3. Check Prometheus scrape interval and timeout
4. Verify metrics are being recorded in application

### Grafana dashboards empty

1. Verify data sources are configured correctly
2. Check Prometheus has scraped data: http://localhost:9090/graph
3. Verify dashboard queries use correct metric names
4. Check time range includes when metrics were recorded

### High memory usage

1. Reduce Prometheus retention: `--storage.tsdb.retention.time=7d`
2. Enable sampling in Jaeger: `JAEGER_SAMPLER_PARAM=0.1`
3. Limit metric cardinality (number of label combinations)
4. Cleanup old data: `docker exec prometheus promtool tsdb admin`

---

## Performance Tuning

### Sampling (for high-traffic systems)

```python
os.environ['JAEGER_SAMPLER_TYPE'] = 'probabilistic'
os.environ['JAEGER_SAMPLER_PARAM'] = '0.1'  # 10% sample rate
```

### Batch Processing

```python
tracer_provider.add_span_processor(
    BatchSpanProcessor(
        jaeger_exporter,
        max_queue_size=10000,
        max_export_batch_size=1000,
        schedule_delay_millis=5000
    )
)
```

### Metric Cardinality Control

```python
# Avoid high-cardinality labels like user IDs
# Good: {"status": "success"}
# Bad: {"user_id": "1000000", "vendor_id": "vendor_xyz"}

# Use bounded labels
attributes = {
    "status": status,
    "vendor_tier": categorize_vendor(vendor_id),  # High/Medium/Low
    "region": region,
}
```

---

## Advanced Setup: Multi-Cluster

```yaml
# For multiple application instances
prometheus:
  scrape_configs:
    - job_name: 'vendor_risk_cluster'
      consul_sd_configs:
        - server: 'localhost:8500'
      relabel_configs:
        - source_labels: [__meta_consul_service]
          target_label: instance
```

---

## Alerting Setup

1. **Email Alerts**
   ```yaml
   alertmanager_config.yml:
     route:
       receiver: 'email'
     receivers:
       - name: 'email'
         email_configs:
           - to: 'team@example.com'
             from: 'alertmanager@example.com'
             smarthost: 'smtp.example.com:587'
   ```

2. **Slack Alerts**
   ```yaml
   receivers:
     - name: 'slack'
       slack_configs:
         - api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL'
           channel: '#alerts'
   ```

3. **PagerDuty Alerts**
   ```yaml
   receivers:
     - name: 'pagerduty'
       pagerduty_configs:
         - service_key: 'YOUR_SERVICE_KEY'
   ```

---

## Backup & Retention

### Prometheus Data Backup

```bash
# Backup Prometheus data
docker exec prometheus tar czf /prometheus/backup.tar.gz /prometheus/wal

# Restore
docker exec prometheus tar xzf /prometheus/backup.tar.gz
```

### Set Retention Policies

```yaml
# Keep metrics for 30 days
prometheus:
  command:
    - '--storage.tsdb.retention.time=30d'
    - '--storage.tsdb.retention.size=50GB'
```

---

## Next Steps

1. Deploy observability stack: `docker-compose up -d`
2. Add instrumentations to application
3. Configure Grafana dashboards
4. Set up alerting rules
5. Test trace collection: http://localhost:16686
6. Review metrics in Prometheus: http://localhost:9090
7. Monitor dashboards in Grafana: http://localhost:3000
