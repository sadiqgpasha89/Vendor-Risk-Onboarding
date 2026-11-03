# Vendor Risk Onboarding - LangGraph Multi-Agent Solution

A production-ready, enterprise-grade vendor risk onboarding platform built with LangGraph, featuring multi-agent orchestration, comprehensive LLMOps infrastructure, and support for 10+ concurrent users.

## 🏗️ Architecture Overview

### Multi-Agent System
- **Document Ingestion Agent**: Processes vendor documents (compliance reports, financial statements, etc.)
- **KYC Agent**: Performs Know-Your-Customer validation
- **Risk Assessment Agent**: Evaluates vendor risk profile
- **Compliance Agent**: Checks regulatory requirements
- **Orchestrator Agent**: Coordinates all agents and maintains workflow state
- **Report Generation Agent**: Creates audit-ready compliance reports

### LLMOps Components
- **Model Registry**: Version management for LLM configurations
- **Prompt Management**: Centralized prompt storage with versioning
- **Evaluation Framework**: Automated assessment of agent outputs
- **Monitoring & Logging**: Real-time performance tracking
- **Configuration Management**: Environment-based configurations
- **CI/CD Pipeline**: Automated testing and deployment

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Docker & Docker Compose
- PostgreSQL (or use Docker Compose)
- OpenAI API key (or compatible LLM)

### Installation

```bash
# Clone and setup
cd vendor-risk-onboarding
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Setup environment
cp .env.example .env
# Edit .env with your configuration

# Initialize database
make db-init

# Run application
make run
```

### Docker Deployment

```bash
docker-compose up -d
```

## 📁 Project Structure

```
vendor-risk-onboarding/
├── src/
│   ├── agents/                          # LangGraph agent definitions
│   │   ├── __init__.py
│   │   ├── orchestrator.py             # Main workflow orchestrator
│   │   ├── document_processor.py        # Document ingestion agent
│   │   ├── kyc_validator.py            # KYC validation agent
│   │   ├── risk_assessor.py            # Risk assessment agent
│   │   ├── compliance_checker.py        # Compliance agent
│   │   └── report_generator.py          # Report generation agent
│   │
│   ├── llmops/
│   │   ├── __init__.py
│   │   ├── model_registry.py            # LLM model management
│   │   ├── prompt_manager.py            # Prompt versioning & management
│   │   ├── evaluator.py                 # Evaluation framework
│   │   ├── monitoring.py                # Logging & monitoring
│   │   ├── tracer.py                    # LangSmith integration
│   │   └── config.py                    # LLMOps configuration
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── llm_models.py                # LLM instantiation
│   │   └── embeddings.py                # Embedding models
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py                # Database connection
│   │   ├── models.py                    # SQLAlchemy models
│   │   ├── repository.py                # Repository pattern
│   │   └── migrations/                  # Alembic migrations
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py                      # FastAPI app
│   │   ├── routes/
│   │   │   ├── vendors.py               # Vendor endpoints
│   │   │   ├── workflows.py             # Workflow management
│   │   │   ├── evaluations.py           # Evaluation endpoints
│   │   │   └── monitoring.py            # Monitoring endpoints
│   │   ├── middleware/
│   │   │   ├── auth.py                  # Authentication
│   │   │   ├── rate_limit.py            # Rate limiting
│   │   │   └── telemetry.py             # Request tracking
│   │   └── schemas/
│   │       ├── vendor.py
│   │       ├── workflow.py
│   │       └── evaluation.py
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py                  # Pydantic settings
│   │   ├── llmops_config.yaml           # LLMOps configuration
│   │   └── prompts/                     # Prompt templates
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── vendor.py
│   │   ├── assessment.py
│   │   ├── document.py
│   │   └── workflow.py
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── document_parser.py           # Document processing
│   │   ├── validators.py                # Validation utilities
│   │   └── formatters.py                # Output formatting
│   │
│   └── __init__.py
│
├── tests/
│   ├── __init__.py
│   ├── unit/
│   │   ├── agents/
│   │   ├── llmops/
│   │   └── api/
│   ├── integration/
│   │   ├── test_workflows.py
│   │   └── test_api.py
│   ├── conftest.py
│   └── fixtures/
│       └── sample_data.py
│
├── evals/
│   ├── __init__.py
│   ├── criteria.py                      # Evaluation criteria definitions
│   ├── datasets.py                      # Test datasets
│   ├── run_evals.py                     # Evaluation runner
│   └── results/                         # Evaluation results
│
├── workflows/
│   ├── vendor_onboarding.yaml           # Workflow definitions
│   └── risk_assessment.yaml
│
├── docker/
│   ├── Dockerfile
│   ├── Dockerfile.worker
│   └── docker-compose.override.yml
│
├── docs/
│   ├── architecture.md
│   ├── api_guide.md
│   ├── llmops_guide.md
│   ├── deployment.md
│   └── adr/                             # Architecture Decision Records
│
├── notebooks/
│   ├── exploration.ipynb
│   ├── model_testing.ipynb
│   └── prompt_optimization.ipynb
│
├── .github/
│   └── workflows/
│       ├── test.yml
│       ├── lint.yml
│       └── deploy.yml
│
├── requirements.txt
├── requirements-dev.txt
├── docker-compose.yml
├── .env.example
├── .dockerignore
├── .gitignore
├── Makefile
├── pytest.ini
└── pyproject.toml
```

## 🤖 Supported LLM Providers

- OpenAI (GPT-4, GPT-3.5-turbo)
- Azure OpenAI
- Anthropic Claude
- Open-source: Ollama, LLaMA, Mistral

## 📊 Features

- ✅ Multi-agent orchestration with state management
- ✅ Document processing & OCR support
- ✅ Real-time monitoring & tracing
- ✅ Evaluation framework with custom metrics
- ✅ Prompt versioning & A/B testing
- ✅ PostgreSQL persistence layer
- ✅ REST API with FastAPI
- ✅ Role-based access control (RBAC)
- ✅ Audit logging for compliance
- ✅ Scalable to 10+ concurrent users
- ✅ Docker deployment ready

## 📈 Performance & Scalability

- **Concurrent Users**: 10-100+ with horizontal scaling
- **Response Time**: <5s average (including LLM calls)
- **Database**: PostgreSQL with connection pooling
- **Caching**: Redis for prompt/model caching
- **Async Processing**: Celery for background jobs

## 🔐 Security

- JWT-based authentication
- Rate limiting per user/endpoint
- Input validation & sanitization
- Encrypted sensitive data storage
- Audit trails for compliance
- OWASP compliance

## 📚 Documentation

See the [docs/](docs/) directory for detailed guides on:
- Architecture and design patterns
- API reference
- LLMOps configuration and best practices
- Deployment strategies
- Contributing guidelines

## 🧪 Testing

```bash
# Run all tests
make test

# Run with coverage
make test-coverage

# Run evaluations
make evals
```

## 🚀 Deployment

See [docs/deployment.md](docs/deployment.md) for:
- Kubernetes deployment
- AWS/Azure/GCP setup
- CI/CD pipeline configuration
- Monitoring & alerting setup

## 📝 License

MIT

## 🤝 Contributing

See CONTRIBUTING.md for guidelines.

## 📞 Support

For issues and questions, please open a GitHub issue or contact the team.
