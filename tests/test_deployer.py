from datetime import datetime, timezone
import pytest

from release_manager.config import Settings
from release_manager.database import Database
from release_manager.deployer import DeploymentEngine
from release_manager.health import HealthService
from release_manager.models import ServiceHealth

class FakeDockerClient:
    def __init__(self):
        self.deploy_calls: list[tuple[str, str, str]] = []

    def deploy_service(self, *, environment: str, service_name: str, version: str) -> None:
        self.deploy_calls.append((environment, service_name, version))

    def get_service_health(self, *, environment: str, service_name: str) -> ServiceHealth:
        return ServiceHealth(
            environment=environment,
            service_name=service_name,
            status="healthy",
            replicas_running=1,
            replicas_desired=1,
            last_checked=datetime.now(timezone.utc),
        )


def make_database(tmp_path):
    db_path = tmp_path / "engine.db"
    database = Database(db_path)
    database.initialize_schema()
    return database


@pytest.mark.asyncio
async def test_deploy_prod(tmp_path):
    db = make_database(tmp_path)
    docker = FakeDockerClient()
    health = HealthService(db, docker)  # type: ignore[arg-type]
    settings = Settings(
        environment_name="test",
        stub_mode=False,
        github_repo="user/repo",
        github_token_file=None,
        github_token=None,
        poll_interval_seconds=0,
        docker_host=None,
        database_path=tmp_path / "engine-test.db",
        deployment_timeout_seconds=300,
        health_check_interval_seconds=5,
        web_host="0.0.0.0",
        web_port=8080,
    )
    engine = DeploymentEngine(
        database=db,
        docker_client=docker,  # type: ignore[arg-type]
        health_service=health,
        settings=settings,
    )

    result = await engine.deploy_prod(
        services={"jellyfin": "2025040900"},
        commit_sha="def456",
    )

    assert result.status == "success"
    assert docker.deploy_calls == [("prod", "jellyfin", "2025040900")]
    prod_state = db.get_environment_state("prod")
    assert prod_state is not None
    assert prod_state.services["jellyfin"] == "2025040900"
