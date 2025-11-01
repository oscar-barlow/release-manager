"""Database-backed port implementations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from release_manager.application.ports import (
    DeploymentHistoryRepository,
    EnvironmentStateRepository,
    ServiceHealthRepository,
)
from release_manager.database import Database
from release_manager.models import DeploymentHistory, EnvironmentState, ServiceHealth


@dataclass(slots=True)
class DatabaseEnvironmentRepository(EnvironmentStateRepository):
    """Environment state persistence backed by SQLite."""

    database: Database

    def get_environment(self, environment: str) -> Optional[EnvironmentState]:
        return self.database.get_environment_state(environment)

    def get_all_environments(self) -> dict[str, EnvironmentState]:
        return self.database.get_all_environment_states()

    def record_deployment(
        self,
        *,
        environment: str,
        service_name: str,
        version: str,
        commit_sha: str,
        deployed_at: datetime,
        deployed_by: str,
    ) -> None:
        self.database.upsert_deployment(
            environment=environment,
            service_name=service_name,
            version=version,
            commit_sha=commit_sha,
            deployed_at=deployed_at,
            deployed_by=deployed_by,
        )


@dataclass(slots=True)
class DatabaseDeploymentHistoryRepository(DeploymentHistoryRepository):
    """Deployment history adapter."""

    database: Database

    def start_history(
        self,
        *,
        environment: str,
        service_name: str,
        version: str,
        commit_sha: str,
        deployed_by: str,
        started_at: datetime,
    ) -> int:
        return self.database.create_history_record(
            environment=environment,
            service_name=service_name,
            version=version,
            commit_sha=commit_sha,
            deployed_by=deployed_by,
            started_at=started_at,
            status="in_progress",
        )

    def complete_history(
        self,
        history_id: int,
        *,
        status: str,
        completed_at: datetime,
        duration_seconds: float,
        error_message: Optional[str] = None,
    ) -> None:
        self.database.finalize_history_record(
            history_id,
            status=status,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            error_message=error_message,
        )

    def fetch_history(self, history_id: int) -> Optional[DeploymentHistory]:
        return self.database.fetch_history_record(history_id)

    def list_history_for_started_at(
        self, *, environment: str, started_at: datetime
    ) -> list[DeploymentHistory]:
        return self.database.list_history_for_started_at(
            environment=environment, started_at=started_at
        )

    def list_history(
        self,
        *,
        environment: Optional[str],
        service: Optional[str],
        limit: int,
        offset: int,
    ) -> Tuple[list[DeploymentHistory], int]:
        return self.database.list_history(
            environment=environment, service=service, limit=limit, offset=offset
        )


@dataclass(slots=True)
class DatabaseServiceHealthRepository(ServiceHealthRepository):
    """Service health persistence adapter."""

    database: Database

    def store(self, health: ServiceHealth) -> None:
        self.database.update_service_health(health)

    def list(self, environment: Optional[str] = None) -> list[ServiceHealth]:
        return self.database.list_service_health(environment)
