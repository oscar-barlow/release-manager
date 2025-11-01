from datetime import datetime, timezone
import logging
from typing import Iterable

import pytest

from release_manager.adapters.persistence import (
    DatabaseDeploymentHistoryRepository,
    DatabaseEnvironmentRepository,
    DatabaseServiceHealthRepository,
)
from release_manager.application.services.deployment_service import DeploymentService
from release_manager.database import Database
from release_manager.health import HealthService
from release_manager.models import ServiceHealth
from release_manager.application.ports import Clock, ContainerOrchestrator, HealthProbe


class FixedClock(Clock):
    def now(self) -> datetime:
        return datetime(2025, 1, 1, tzinfo=timezone.utc)


class FakeOrchestrator(ContainerOrchestrator):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def deploy_stack(self, *, environment: str, services: dict[str, str]) -> None:
        self.calls.append((environment, services))


class FakeHealthProbe(HealthProbe):
    async def probe(self, *, environment: str, services: Iterable[str]) -> list[ServiceHealth]:
        now = datetime.now(timezone.utc)
        return [
            ServiceHealth(
                environment=environment,
                service_name=service,
                status="healthy",
                replicas_running=1,
                replicas_desired=1,
                last_checked=now,
            )
            for service in services
        ]


def make_database(tmp_path):
    db_path = tmp_path / "engine.db"
    database = Database(db_path)
    database.initialize_schema()
    return database


@pytest.mark.asyncio
async def test_deploy_prod(tmp_path):
    db = make_database(tmp_path)
    environment_repo = DatabaseEnvironmentRepository(db)
    history_repo = DatabaseDeploymentHistoryRepository(db)
    health_repo = DatabaseServiceHealthRepository(db)
    orchestrator = FakeOrchestrator()
    health_service = HealthService(health_repo, FakeHealthProbe())
    deployment_service = DeploymentService(
        environment_repo=environment_repo,
        history_repo=history_repo,
        orchestrator=orchestrator,
        health_service=health_service,
        clock=FixedClock(),
        logger=logging.getLogger(__name__),
    )

    result = await deployment_service.deploy_prod(
        services={"jellyfin": "2025040900"},
        commit_sha="def456",
    )

    assert result.status == "success"
    assert orchestrator.calls == [("prod", {"jellyfin": "2025040900"})]
    prod_state = db.get_environment_state("prod")
    assert prod_state is not None
    assert prod_state.services["jellyfin"] == "2025040900"


@pytest.mark.asyncio
async def test_deploy_prod_subset_validation(tmp_path):
    db = make_database(tmp_path)
    environment_repo = DatabaseEnvironmentRepository(db)
    history_repo = DatabaseDeploymentHistoryRepository(db)
    health_repo = DatabaseServiceHealthRepository(db)
    orchestrator = FakeOrchestrator()
    health_service = HealthService(health_repo, FakeHealthProbe())
    deployment_service = DeploymentService(
        environment_repo=environment_repo,
        history_repo=history_repo,
        orchestrator=orchestrator,
        health_service=health_service,
        clock=FixedClock(),
        logger=logging.getLogger(__name__),
    )

    with pytest.raises(ValueError):
        await deployment_service.deploy_prod(
            services={"api": "1.0.0"},
            commit_sha="sha",
            subset=["unknown"],
        )

    result = await deployment_service.deploy_prod(
        services={"api": "1.0.0", "worker": "1.0.0"},
        commit_sha="sha",
        subset=["worker"],
    )

    assert orchestrator.calls == [("prod", {"worker": "1.0.0"})]
    assert result.services_deployed[0]["name"] == "worker"
