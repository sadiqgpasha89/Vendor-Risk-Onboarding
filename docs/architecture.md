# Architecture and Design

## System Overview

The Vendor Risk Onboarding system is a production-grade multi-agent application built with LangGraph, designed for financial institutions to automate and streamline vendor risk assessment.

```
┌─────────────────────────────────────────────────────────────┐
│                        FastAPI Gateway                       │
│  (Authentication, Rate Limiting, Request Routing)            │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
    ┌────────┐  ┌────────────┐  ┌──────────┐
    │ Vendor │  │ Workflows  │  │ Monitor  │
    │ Routes │  │   Routes   │  │  Routes  │
    └────┬───┘  └──────┬─────┘  └──────┬───┘
         │             │               │
         └─────────────┼───────────────┘
                       │
        ┌──────────────▼──────────────┐
        │   LangGraph Orchestrator    │
        │                             │
        │  ┌────────────────────────┐ │
        │  │ Sub-Agents:            │ │
        │  │ - Document Processor   │ │
        │  │ - KYC Validator        │ │
        │  │ - Risk Assessor        │ │
        │  │ - Compliance Checker   │ │
        │  │ - Report Generator     │ │
        │  └────────────────────────┘ │
        └──────────────┬───────────────┘
                       │
        ┌──────────────┼──────────────┬──────────────┐
        │              │              │              │
        ▼              ▼              ▼              ▼
    ┌─────────┐  ┌─────────┐   ┌────────┐   ┌─────────┐
    │PostgreSQL│ │  Redis  │   │ Jaeger │   │ Celery  │
    │          │ │  Cache  │   │ Tracing│   │ Workers │
    └──────────┘ └─────────┘   └────────┘   └─────────┘
```

## Microservices Architecture

### 1. API Layer (FastAPI)
- **Role**: HTTP request handling and routing
- **Responsibility**:
  - Authentication and authorization
  - Request validation
  - Response formatting
  - Rate limiting
  - CORS handling

### 2. LangGraph Orchestrator
- **Role**: Coordinates multi-agent workflow
- **Agents**:
  - Document Ingestion Agent
  - KYC Validation Agent
  - Risk Assessment Agent
  - Compliance Checker Agent
  - Report Generation Agent

### 3. LLMOps Infrastructure
- **Model Registry**: Version management for LLM configs
- **Prompt Manager**: Template versioning and management
- **Evaluator**: Quality assessment framework
- **Monitor**: Performance tracking and observability
- **Tracer**: Distributed tracing with Jaeger

### 4. Data Layer
- **PostgreSQL**: Primary data storage
- **Redis**: Caching and session management
- **Document Store**: File storage for vendor documents

### 5. Execution Layer
- **Celery Workers**: Async task processing
- **Flower**: Celery task monitoring

## State Management

### Workflow State Machine

```
PENDING → IN_REVIEW → UNDER_ASSESSMENT → APPROVED/REJECTED
   ↓
CONDITIONAL_APPROVED
   ↓
SUSPENDED
```

### Agent State Flow

```python
AgentState:
  vendor_id
  workflow_id
  documents: List[Document]
  kyc_data: KYCData
  risk_assessment: RiskAssessmentResult
  report: str
  agent_results: Dict
  errors: List[str]
  logs: List[Dict]
```

## Multi-Agent Coordination

### Sequential Orchestration
```
1. Document Processing
   ↓
2. KYC Validation
   ↓
3. Risk Assessment
   ↓
4. Compliance Check
   ↓
5. Report Generation
```

### Parallel Processing (Future)
Documents can be processed in parallel, with aggregation before downstream steps.

## Database Schema

### Core Tables
- `users`: User accounts with RBAC roles
- `vendors`: Vendor master data
- `vendor_documents`: Document storage metadata
- `document_analyses`: Agent analysis results
- `risk_assessments`: Risk scoring results
- `workflows`: Workflow execution tracking
- `audit_logs`: Compliance audit trail
- `evaluation_results`: LLMOps evaluation metrics
- `model_metrics`: LLM performance metrics

### Relationships
```
User (1) ──→ (M) Workflow
User (1) ──→ (M) AuditLog
Vendor (1) ──→ (M) Document
Vendor (1) ──→ (M) RiskAssessment
Vendor (1) ──→ (M) Workflow
Document (1) ──→ (M) DocumentAnalysis
Workflow (1) ──→ (M) RiskAssessment
Workflow (1) ──→ (M) EvaluationResult
```

## LLMOps Pipeline

### 1. Model Registry
Tracks LLM versions and configurations:
```json
{
  "provider": "openai",
  "model": "gpt-4",
  "version": "1.0.0",
  "temperature": 0.3,
  "tags": {"use_case": "risk_assessment"},
  "metadata": {"cost_optimization": true}
}
```

### 2. Prompt Management
Versioned prompt templates:
```json
{
  "name": "risk_assessment",
  "version": "2.0",
  "template": "Assess risk for vendor: {vendor_name}...",
  "variables": ["vendor_name", "financial_data"],
  "tags": {"domain": "compliance"}
}
```

### 3. Evaluation Framework
```
Criteria:
  - Correctness (threshold: 0.85)
  - Faithfulness (threshold: 0.80)
  - Relevance (threshold: 0.75)
  - Coherence (threshold: 0.80)
  
Results: Stored in evaluation_results table
Reports: Generated and tracked for improvement
```

### 4. Monitoring & Observability
- **Structured Logging**: JSON structured logs via structlog
- **Distributed Tracing**: Jaeger integration
- **Metrics**: Performance tracking per operation
- **Cost Tracking**: LLM token usage and costs

## Scalability Considerations

### Horizontal Scaling
- **API Servers**: Multiple uvicorn workers
- **Celery Workers**: Auto-scaling via worker pool
- **Database**: Connection pooling (20 connections, 40 overflow)
- **Cache**: Redis cluster for multi-node setup

### Performance Optimization
- **Caching**: Redis for prompt/model configs (3600s TTL)
- **Connection Pooling**: Database and Redis
- **Async Processing**: Celery for long-running tasks
- **Batch Processing**: Support for bulk vendor imports

### Target Capacity
- **Concurrent Users**: 10-100+
- **Workflows/Hour**: 100-1000+
- **Documents/Workflow**: Up to 50
- **Response Time**: <5s average

## Security Architecture

### Authentication
- JWT-based token authentication
- 24-hour token expiration
- Refresh token support (7 days)

### Authorization
- Role-based access control (RBAC)
- Roles: Admin, Compliance Officer, Risk Manager, Vendor Manager, Auditor, Viewer
- Resource-level permissions

### Data Protection
- Encrypted sensitive fields
- Audit logging for compliance
- PII masking capability
- 7-year data retention policy

### API Security
- Rate limiting (100 requests/min per user)
- Input validation and sanitization
- CORS security
- HTTPS in production

## Deployment

### Docker Compose (Development)
- All services in one compose file
- Health checks on critical services
- Volume persistence for data

### Kubernetes (Production)
- Helm charts for deployment
- StatefulSets for database and cache
- HPA for auto-scaling
- Network policies for security

## Monitoring & Alerting

### Metrics
- Request latency (p50, p95, p99)
- Error rates by endpoint
- Model inference latency
- Token usage and costs
- Database connection pool usage

### Alerts
- High error rate (>5%)
- Slow responses (>5s)
- High LLM costs (daily threshold)
- Database connection issues
- Task queue backlog

## Development Workflow

1. **Local Development**: Use `make dev` with auto-reload
2. **Testing**: Unit tests with pytest, integration tests with Docker
3. **Evaluation**: Run LLMOps evaluations before deployment
4. **CI/CD**: GitHub Actions for test, lint, build
5. **Deployment**: Blue-green deployment strategy

## Future Enhancements

1. **Graph Database**: Neo4j for relationship queries
2. **Vector Store**: Pinecone/Milvus for semantic search
3. **Advanced Caching**: LLM response caching
4. **A/B Testing**: Prompt and model A/B testing
5. **Advanced Scheduling**: Recurring assessments
6. **Multi-Tenant**: Organization-level isolation
7. **Real-time Collaboration**: WebSocket support
8. **Mobile App**: React Native mobile application
