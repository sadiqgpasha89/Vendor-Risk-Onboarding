# API Reference Guide

## Base URL
```
http://localhost:8000/api/v1
```

## Authentication

All endpoints (except `/health`) require Bearer token authentication.

### Get Token
```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=user&password=password"
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

### Using Token
```bash
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/vendors
```

## Endpoints

### Health & Status

#### Get Health Status
```
GET /health
```

Response (200):
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00.000Z",
  "app_name": "Vendor Risk Onboarding",
  "environment": "production"
}
```

#### Get System Status
```
GET /status
```

Requires authentication. Response (200):
```json
{
  "status": "operational",
  "timestamp": "2024-01-15T10:30:00.000Z",
  "metrics": {
    "performance_summary": {...},
    "cost_summary": {...}
  },
  "user": {
    "id": "user-uuid",
    "username": "john.doe",
    "role": "compliance_officer"
  }
}
```

### Vendor Management

#### Create Vendor
```
POST /vendors
```

Request:
```json
{
  "name": "Acme Corp",
  "legal_name": "Acme Corporation Inc",
  "registration_number": "REG123456",
  "country": "US",
  "industry": "Technology",
  "website": "https://acme.com",
  "contact_email": "contact@acme.com",
  "phone": "+1-555-0100"
}
```

Response (201):
```json
{
  "id": "vendor-uuid",
  "name": "Acme Corp",
  "legal_name": "Acme Corporation Inc",
  "registration_number": "REG123456",
  "country": "US",
  "industry": "Technology",
  "website": "https://acme.com",
  "contact_email": "contact@acme.com",
  "phone": "+1-555-0100",
  "status": "pending",
  "risk_level": "high",
  "risk_score": 0.0,
  "kyc_verified": false,
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

#### Get Vendor
```
GET /vendors/{vendor_id}
```

Response (200):
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

#### List Vendors
```
GET /vendors?skip=0&limit=10&status=pending&risk_level=high
```

Query Parameters:
- `skip` (int): Records to skip (default: 0)
- `limit` (int): Records per page (default: 10)
- `status` (string): Filter by status
- `risk_level` (string): Filter by risk level

Response (200):
```json
{
  "items": [
    {
      "id": "vendor-uuid",
      "name": "Acme Corp",
      "status": "pending",
      "risk_level": "high",
      "risk_score": 0.0
    }
  ],
  "total": 1,
  "skip": 0,
  "limit": 10
}
```

### Document Management

#### Upload Document
```
POST /vendors/{vendor_id}/documents
```

Request (multipart/form-data):
- `file` (binary): Document file

Response (200):
```json
{
  "document_id": "doc-uuid",
  "vendor_id": "vendor-uuid",
  "file_name": "financial_report.pdf",
  "file_path": "/data/uploads/vendor-uuid/financial_report.pdf",
  "size": 1024000,
  "uploaded_at": "2024-01-15T10:30:00Z"
}
```

### Workflow Management

#### Start Vendor Onboarding
```
POST /workflows/vendor-onboarding?vendor_id={vendor_id}
```

Response (202):
```json
{
  "id": "workflow-uuid",
  "vendor_id": "vendor-uuid",
  "workflow_type": "vendor_onboarding",
  "status": "in_progress",
  "start_time": "2024-01-15T10:30:00Z",
  "created_at": "2024-01-15T10:30:00Z"
}
```

#### Get Workflow
```
GET /workflows/{workflow_id}
```

Response (200):
```json
{
  "id": "workflow-uuid",
  "vendor_id": "vendor-uuid",
  "workflow_type": "vendor_onboarding",
  "status": "completed",
  "start_time": "2024-01-15T10:30:00Z",
  "end_time": "2024-01-15T10:35:00Z",
  "duration_seconds": 300,
  "created_at": "2024-01-15T10:30:00Z"
}
```

#### List Workflows
```
GET /workflows?vendor_id={vendor_id}&status=completed&skip=0&limit=10
```

Query Parameters:
- `vendor_id` (string): Filter by vendor
- `status` (string): Filter by status
- `skip` (int): Records to skip
- `limit` (int): Records per page

Response (200):
```json
{
  "items": [...],
  "total": 5,
  "skip": 0,
  "limit": 10
}
```

#### Get Workflow Log
```
GET /workflows/{workflow_id}/log?format=json
```

Query Parameters:
- `format` (string): `json` or `text` (default: json)

Response (200):
```json
[
  {
    "timestamp": "2024-01-15T10:30:00Z",
    "event_type": "step_completed",
    "agent": "document_processing",
    "status": "success"
  },
  {
    "timestamp": "2024-01-15T10:31:00Z",
    "event_type": "step_completed",
    "agent": "kyc_validation",
    "status": "success"
  }
]
```

### Monitoring & Evaluation

#### Get Performance Metrics
```
GET /monitoring/metrics?operation_name={operation_name}
```

Query Parameters:
- `operation_name` (string): Filter by operation (optional)

Response (200):
```json
{
  "metrics": {
    "operation": "workflow_step_document_processing",
    "metrics": [
      {
        "timestamp": "2024-01-15T10:30:00Z",
        "operation": "workflow_step_document_processing",
        "duration_seconds": 2.5,
        "memory_delta_mb": 45.2
      }
    ]
  },
  "summary": {
    "workflow_step_document_processing": {
      "count": 10,
      "avg_duration": 2.3,
      "min_duration": 1.8,
      "max_duration": 3.5,
      "total_duration": 23.0
    }
  }
}
```

#### Get LLM Costs
```
GET /monitoring/costs
```

Response (200):
```json
{
  "total_cost": 12.50,
  "cost_by_model": {
    "gpt-4": 10.25,
    "gpt-3.5-turbo": 2.25
  },
  "usage_by_model": {
    "gpt-4": {
      "input": 5000,
      "output": 1000
    },
    "gpt-3.5-turbo": {
      "input": 10000,
      "output": 2000
    }
  }
}
```

#### Run Evaluations
```
POST /evals/run?workflow_id={workflow_id}
```

Response (202):
```json
{
  "evaluation_id": "eval-uuid",
  "workflow_id": "workflow-uuid",
  "status": "in_progress",
  "started_at": "2024-01-15T10:30:00Z"
}
```

#### Get Evaluation Results
```
GET /evals/{evaluation_id}
```

Response (200):
```json
{
  "evaluation_id": "eval-uuid",
  "status": "completed",
  "results": {
    "correctness": 0.92,
    "faithfulness": 0.88,
    "relevance": 0.95
  }
}
```

### Audit & Compliance

#### Get Audit Logs
```
GET /audit-logs?resource_type=vendor&skip=0&limit=100
```

Query Parameters:
- `resource_type` (string): Filter by resource type
- `skip` (int): Records to skip
- `limit` (int): Records per page

Response (200):
```json
{
  "items": [
    {
      "id": "log-uuid",
      "user_id": "user-uuid",
      "action": "create",
      "resource_type": "vendor",
      "resource_id": "vendor-uuid",
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "total": 10,
  "skip": 0,
  "limit": 100
}
```

## Error Responses

### 400 Bad Request
```json
{
  "detail": "Invalid request payload"
}
```

### 401 Unauthorized
```json
{
  "detail": "Token has expired"
}
```

### 403 Forbidden
```json
{
  "detail": "Insufficient permissions"
}
```

### 404 Not Found
```json
{
  "detail": "Vendor not found"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Internal server error"
}
```

## Rate Limiting

Rate limits: 100 requests per minute per user

Response headers:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1642251120
```

## Pagination

All list endpoints support pagination:
- `skip`: Number of records to skip (default: 0)
- `limit`: Number of records per page (default: 10, max: 100)

## Filtering

Supported filters vary by endpoint. Common filters:
- `status`: Workflow/Vendor status
- `risk_level`: Risk level classification
- `created_at`: Creation timestamp
- `updated_at`: Last update timestamp

## Example Workflows

### Complete Vendor Onboarding

1. **Create Vendor**
```bash
curl -X POST http://localhost:8000/api/v1/vendors \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme","country":"US"}'
```

2. **Upload Documents**
```bash
curl -X POST http://localhost:8000/api/v1/vendors/$VENDOR_ID/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@financial_report.pdf"
```

3. **Start Workflow**
```bash
curl -X POST "http://localhost:8000/api/v1/workflows/vendor-onboarding?vendor_id=$VENDOR_ID" \
  -H "Authorization: Bearer $TOKEN"
```

4. **Check Progress**
```bash
curl http://localhost:8000/api/v1/workflows/$WORKFLOW_ID \
  -H "Authorization: Bearer $TOKEN"
```

5. **Get Results**
```bash
curl http://localhost:8000/api/v1/workflows/$WORKFLOW_ID/log \
  -H "Authorization: Bearer $TOKEN"
```

## SDKs & Clients

### Python Client (Future)
```python
from vendor_risk_client import VendorRiskClient

client = VendorRiskClient(api_key="your-api-key")
vendor = client.vendors.create(name="Acme", country="US")
workflow = client.workflows.start_onboarding(vendor_id=vendor.id)
```

### JavaScript Client (Future)
```javascript
import { VendorRiskClient } from '@vendor-risk/client';

const client = new VendorRiskClient({ apiKey: 'your-api-key' });
const vendor = await client.vendors.create({ name: 'Acme', country: 'US' });
const workflow = await client.workflows.startOnboarding({ vendorId: vendor.id });
```
