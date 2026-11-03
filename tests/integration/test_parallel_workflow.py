"""Integration tests for parallel multi-agent workflow and FastAPI enterprise endpoints."""

import pytest
import uuid
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.middleware.auth import get_current_user
from src.db.connection import get_db
from src.agents.graph_workflow import vendor_risk_workflow
from src.db.models import User, UserRole


@pytest.fixture
def test_user():
    return User(
        id=str(uuid.uuid4()),
        username="integration_tester",
        email="tester@enterprise.com",
        role=UserRole.ADMIN,
        is_active=True,
    )


@pytest.fixture
def client(db, test_user):
    """FastAPI TestClient with overridden dependencies."""
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_parallel_multi_agent_workflow_execution():
    """Test full LangGraph StateGraph parallel fan-out and synthesis."""
    vendor_id = f"VEND-{uuid.uuid4().hex[:6]}"
    vendor_data = {
        "id": vendor_id,
        "name": "Acme Global Solutions",
        "legal_name": "Acme Global Solutions Corp",
        "registration_number": "12-3456789",
        "country": "US",
        "industry": "Software Engineering",
        "annual_revenue": 15000000.0,
        "employee_count": 80,
    }
    docs = [
        {
            "id": "DOC-1",
            "name": "W9_Tax_Form.pdf",
            "type": "tax_document",
            "content": "Official W-9 Form for Acme Global Solutions Corp, EIN 12-3456789",
        }
    ]

    final_state = await vendor_risk_workflow.execute(
        vendor_id=vendor_id,
        vendor_data=vendor_data,
        documents=docs,
    )

    assert final_state.status in ("completed", "requires_review")
    assert "document_processor" in final_state.agent_results
    assert "kyc_validator" in final_state.agent_results
    assert "compliance_checker" in final_state.agent_results
    assert "risk_assessor" in final_state.agent_results
    assert "report_generator" in final_state.agent_results
    assert "supervisor" in final_state.agent_results
    assert final_state.risk_assessment is not None
    assert final_state.risk_assessment.overall_score is not None


@pytest.mark.integration
def test_health_check_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.integration
def test_batch_screen_vendors_endpoint(client):
    payload = {
        "vendors": [
            {
                "name": "Clean Vendor One",
                "legal_name": "Clean Vendor One Inc",
                "registration_number": "11-2233445",
                "country": "US",
            },
            {
                "name": "Rosneft Oil Company",
                "legal_name": "Rosneft Oil Company",
                "registration_number": "RU7706107510",
                "country": "RU",
            },
        ]
    }
    response = client.post("/api/v1/vendors/batch-screen", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["total_screened"] == 2
    assert len(data["results"]) == 2
    assert data["avg_latency_ms"] >= 0.0

    # Ensure sanctioned Russian entity is flagged as HIGH or CRITICAL
    sanc_result = next(r for r in data["results"] if "Rosneft" in r["name"])
    assert sanc_result["risk_level"] in ("HIGH", "CRITICAL")
    assert sanc_result["decision"] == "REJECT"


@pytest.mark.integration
def test_mlops_endpoints(client):
    # 1. Models list
    resp_models = client.get("/api/v1/mlops/models")
    assert resp_models.status_code == 200
    assert "models" in resp_models.json()

    # 2. Drift check
    resp_drift = client.post("/api/v1/mlops/drift", json={})
    assert resp_drift.status_code == 200
    drift_data = resp_drift.json()
    assert drift_data["status"] == "success"
    assert "feature_metrics" in drift_data

    # 3. Model evaluation candidate
    resp_eval = client.post("/api/v1/mlops/evaluate")
    assert resp_eval.status_code == 200
    eval_data = resp_eval.json()
    assert "passed" in eval_data
    assert "auc_pr" in eval_data


@pytest.mark.integration
def test_llmops_endpoints(client):
    # 1. Prompts list
    resp_prompts = client.get("/api/v1/llmops/prompts")
    assert resp_prompts.status_code == 200
    assert "prompts" in resp_prompts.json()

    # 2. Gateway status
    resp_gateway = client.get("/api/v1/llmops/gateway/status")
    assert resp_gateway.status_code == 200
    gw_data = resp_gateway.json()
    assert "active_provider" in gw_data
    assert "circuit_breaker_status" in gw_data


@pytest.mark.integration
def test_stakeholder_dashboard_endpoints(client):
    # JSON dashboard
    resp_json = client.get("/api/v1/dashboards/stakeholder")
    assert resp_json.status_code == 200
    json_data = resp_json.json()
    assert "summary" in json_data
    assert "total_vendors" in json_data["summary"]

    # HTML dashboard
    resp_html = client.get("/api/v1/dashboards/stakeholder?format=html")
    assert resp_html.status_code == 200
    assert "text/html" in resp_html.headers.get("content-type", "")
    assert "Executive Enterprise Dashboard" in resp_html.text
