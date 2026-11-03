# Quick Start Guide

Get the Vendor Risk Onboarding system up and running in minutes.

## 30-Minute Setup

### 1. Prerequisites (5 min)

Ensure you have:
- Python 3.10+
- Docker and Docker Compose (or local PostgreSQL + Redis)
- OpenAI API key or compatible LLM

### 2. Clone and Setup (10 min)

```bash
# Navigate to project directory
cd vendor-risk-onboarding

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env with your OpenAI API key
# OPENAI_API_KEY=sk-...
```

### 3. Database Setup (5 min)

**Option A: Using Docker Compose (Recommended)**
```bash
# Start all services
docker-compose up -d

# Initialize database (wait for postgres to be ready)
sleep 10
docker-compose exec api python -c "from src.db.connection import init_db; init_db()"
```

**Option B: Local PostgreSQL**
```bash
# Ensure PostgreSQL is running
createdb vendor_risk

# Update .env
DATABASE_URL=postgresql://user:password@localhost:5432/vendor_risk

# Initialize database
python -c "from src.db.connection import init_db; init_db()"
```

### 4. Start Development Server (5 min)

```bash
# Terminal 1: Start API
make dev

# Terminal 2: Start Celery worker (optional)
celery -A src.tasks.worker worker --loglevel=info

# API is now running at http://localhost:8000
# Docs available at http://localhost:8000/docs
```

## First Steps

### Check Health

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "app_name": "Vendor Risk Onboarding",
  "environment": "development"
}
```

### Create a Test Vendor

```bash
# Get token (if authentication enabled)
# For development, you might need to bypass auth or create a test user

# Create vendor
curl -X POST http://localhost:8000/api/v1/vendors \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Acme Corp",
    "legal_name": "Acme Corporation Inc",
    "registration_number": "REG123456",
    "country": "US",
    "industry": "Technology",
    "website": "https://acme.com",
    "contact_email": "contact@acme.com"
  }'
```

Expected response:
```json
{
  "id": "vendor-uuid",
  "name": "Acme Corp",
  "status": "pending",
  "risk_level": "high",
  "risk_score": 0.0,
  "kyc_verified": false,
  "created_at": "2024-01-15T10:30:00Z"
}
```

### Start Vendor Onboarding Workflow

```bash
# Replace VENDOR_ID with the ID from previous step
VENDOR_ID="vendor-uuid"

curl -X POST "http://localhost:8000/api/v1/workflows/vendor-onboarding?vendor_id=$VENDOR_ID" \
  -H "Content-Type: application/json"
```

Response:
```json
{
  "id": "workflow-uuid",
  "vendor_id": "vendor-uuid",
  "workflow_type": "vendor_onboarding",
  "status": "in_progress",
  "start_time": "2024-01-15T10:30:00Z"
}
```

### Check Workflow Status

```bash
WORKFLOW_ID="workflow-uuid"

curl http://localhost:8000/api/v1/workflows/$WORKFLOW_ID
```

### View Workflow Logs

```bash
curl http://localhost:8000/api/v1/workflows/$WORKFLOW_ID/log
```

## API Documentation

Once running, view interactive API docs:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Running Tests

```bash
# Run all tests
make test

# Run with coverage
make test-coverage

# Run specific test file
pytest tests/unit/test_agents.py -v
```

## Monitoring

Access monitoring dashboards:
- **Jaeger Traces**: http://localhost:16686
- **Flower (Celery)**: http://localhost:5555
- **MLFlow**: http://localhost:5000

## Evaluation Framework

Run evaluation on workflow outputs:

```python
from src.llmops.evaluator import (
    EvaluationFramework,
    EvaluationCriteria,
    EvaluationMetricType,
)

framework = EvaluationFramework()

framework.add_criteria(EvaluationCriteria(
    metric_type=EvaluationMetricType.CORRECTNESS,
    threshold=0.85,
))

# Run evaluation
results = await framework.evaluate(
    prediction="Your LLM output...",
    reference="Expected output..."
)

print(results)
```

## Stopping Services

```bash
# Stop everything
docker-compose down

# Stop and clean volumes
docker-compose down -v

# Stop development server
# Press Ctrl+C in terminal running the API
```

## Troubleshooting

### Port Already in Use

```bash
# Find process using port 8000
lsof -i :8000

# Kill process
kill -9 <PID>
```

### Database Connection Error

```bash
# Check PostgreSQL is running
docker-compose ps postgres

# Check database URL in .env
# Ensure DATABASE_URL is correct

# Reinitialize database
docker-compose exec api python -c "from src.db.connection import init_db; init_db()"
```

### LLM API Key Error

```bash
# Verify OpenAI API key
echo $OPENAI_API_KEY

# Update .env if needed
OPENAI_API_KEY=sk-your-actual-key
```

### Celery Worker Issues

```bash
# Check Redis is running
docker-compose ps redis

# Check Celery logs
docker-compose logs celery_worker

# Restart worker
docker-compose restart celery_worker
```

## Next Steps

1. **Explore Architecture**: Read [docs/architecture.md](docs/architecture.md)
2. **API Guide**: See [docs/api_guide.md](docs/api_guide.md)
3. **LLMOps**: Learn about LLMOps in [docs/llmops_guide.md](docs/llmops_guide.md)
4. **Production**: Deploy with [docs/deployment.md](docs/deployment.md)

## Common Commands

```bash
# View logs
docker-compose logs -f api

# Run migrations
make db-migrate

# Format code
make format

# Lint code
make lint

# Type checking
make type-check

# Generate requirements
make requirements
```

## Project Structure

```
vendor-risk-onboarding/
├── src/
│   ├── agents/          # Multi-agent orchestration
│   ├── llmops/          # LLMOps infrastructure
│   ├── api/             # FastAPI application
│   ├── db/              # Database layer
│   └── config/          # Configuration
├── tests/               # Test suite
├── docs/                # Documentation
├── docker-compose.yml   # Services definition
└── Makefile             # Common commands
```

## Support

- **Issues**: GitHub Issues
- **Discussions**: GitHub Discussions
- **Documentation**: See `docs/` folder
- **Email**: team@example.com

## Tips & Tricks

### Development with Auto-Reload

```bash
make dev
# Changes to Python files trigger automatic restart
```

### Watch LLM Calls

```bash
# Enable LangSmith tracing
export LANGSMITH_API_KEY=your-key
export LANGSMITH_PROJECT=vendor-risk

# View traces at langsmith.com
```

### Quick Database Reset

```bash
# Drop and recreate database
make db-drop
make db-init
```

### Test with Sample Data

```bash
python -c "from tests.fixtures.sample_data import TestDataFactory; print(TestDataFactory.create_vendor())"
```

## Performance Tips

1. **Increase Worker Pool**: `docker-compose up --scale celery_worker=4`
2. **Enable Caching**: Set `REDIS_CACHE_TTL=3600`
3. **Optimize Database**: Run `VACUUM ANALYZE` periodically
4. **Monitor Costs**: Check `/api/v1/monitoring/costs`

## Security Notes

- ⚠️ **Development Only**: Default `.env` is NOT secure
- 🔒 **Production**: Use strong passwords, enable SSL/TLS
- 🔐 **Secrets**: Never commit `.env` to version control
- 🛡️ **Rate Limiting**: Enabled by default (100 req/min)

---

**Ready to go!** Your system should now be running. Visit http://localhost:8000/docs to explore the API.
