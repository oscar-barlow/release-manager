import pytest
from fastapi.testclient import TestClient

from release_manager import config


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "api.db"
    monkeypatch.setenv("GITHUB_REPO", "user/homelab")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("ENVIRONMENT_NAME", "test")
    monkeypatch.setenv("STUB_MODE", "true")
    config.get_settings.cache_clear()
    from release_manager.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_environment_endpoints(client):
    database = client.app.state.database
    database.initialize_schema()
    database.upsert_deployment(
        environment="preprod",
        service_name="jellyfin",
        version="2025040900",
        commit_sha="def456",
        deployed_by="system",
    )
    database.upsert_deployment(
        environment="prod",
        service_name="jellyfin",
        version="2025040803",
        commit_sha="abc123",
        deployed_by="manual",
    )

    response = client.get("/api/environments")
    assert response.status_code == 200
    data = response.json()
    assert "preprod" in data
    assert data["preprod"]["services"]["jellyfin"] == "2025040900"

    diff_response = client.get("/api/diff")
    assert diff_response.status_code == 200
    diff = diff_response.json()
    assert diff["changes"][0]["change_type"] == "version_bump"

    deploy_response = client.post("/api/deploy/prod", json={"confirm": True})
    assert deploy_response.status_code == 202
    deploy_data = deploy_response.json()
    assert deploy_data["status"] in {"success", "in_progress"}
    deployment_id = deploy_data["deployment_id"]

    status_response = client.get(f"/api/deploy/prod/{deployment_id}")
    assert status_response.status_code == 200

    history_response = client.get("/api/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert history["total"] >= 1

    health_response = client.get("/api/health")
    assert health_response.status_code == 200
