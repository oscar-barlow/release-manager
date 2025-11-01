"""Port definitions for Hexagonal architecture."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional, Protocol, Tuple

from release_manager.github import GitHubEnvFile
from release_manager.models import DeploymentHistory, EnvironmentState, ServiceHealth


class Clock(Protocol):
    """Provides wall-clock timestamps."""

    def now(self) -> datetime:
        ...


class Logger(Protocol):
    """Light-weight logging port."""

    def info(self, msg: str, *args: object, **kwargs: object) -> None:
        ...

    def warning(self, msg: str, *args: object, **kwargs: object) -> None:
        ...

    def debug(self, msg: str, *args: object, **kwargs: object) -> None:
        ...

    def error(self, msg: str, *args: object, **kwargs: object) -> None:
        ...


class EnvironmentStateRepository(Protocol):
    """Access to the latest deployed state per environment."""

    def get_environment(self, environment: str) -> Optional[EnvironmentState]:
        ...

    def get_all_environments(self) -> dict[str, EnvironmentState]:
        ...

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
        ...


class DeploymentHistoryRepository(Protocol):
    """Persists detailed deployment history."""

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
        ...

    def complete_history(
        self,
        history_id: int,
        *,
        status: str,
        completed_at: datetime,
        duration_seconds: float,
        error_message: Optional[str] = None,
    ) -> None:
        ...

    def fetch_history(self, history_id: int) -> Optional[DeploymentHistory]:
        ...

    def list_history_for_started_at(
        self, *, environment: str, started_at: datetime
    ) -> list[DeploymentHistory]:
        ...

    def list_history(
        self,
        *,
        environment: Optional[str],
        service: Optional[str],
        limit: int,
        offset: int,
    ) -> Tuple[list[DeploymentHistory], int]:
        ...


class ServiceHealthRepository(Protocol):
    """Stores health snapshots for services."""

    def store(self, health: ServiceHealth) -> None:
        ...

    def list(self, environment: Optional[str] = None) -> list[ServiceHealth]:
        ...


class ManifestFetcher(Protocol):
    """Fetches deployment manifests (e.g., from GitHub)."""

    async def fetch(self, path: str) -> GitHubEnvFile:
        ...


class ContainerOrchestrator(Protocol):
    """Deploys services to a container platform."""

    def deploy_stack(self, *, environment: str, services: dict[str, str]) -> None:
        ...


class HealthProbe(Protocol):
    """Collects live health information for deployed services."""

    async def probe(self, *, environment: str, services: Iterable[str]) -> list[ServiceHealth]:
        ...
