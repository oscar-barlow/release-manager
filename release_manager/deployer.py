"""Deployment orchestration logic."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional, cast, Literal

from .config import Settings
from .database import Database
from .docker_client import DockerService
from .health import HealthService
from .models import (
    DeploymentStatus,
    DeploymentStatusType,
    DockerServiceSummary,
    EnvironmentState,
    ServiceDiff,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DeploymentResult:
    """Internal helper capturing the outcome of a deployment run."""

    deployment_id: int
    environment: str
    status: DeploymentStatusType
    started_at: datetime
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]
    services_deployed: list[dict[str, str]]
    error_message: Optional[str]


class DeploymentEngine:
    """Coordinates deployments across GitHub, Docker and the database."""

    def __init__(
        self,
        *,
        database: Database,
        docker_client: DockerService,
        health_service: HealthService,
        settings: Settings,
    ):
        self._db = database
        self._docker = docker_client
        self._health = health_service
        self._settings = settings
        self._lock = asyncio.Lock()
        self._active_environment: Optional[str] = None

    def diff_environments(self) -> list[ServiceDiff]:
        return self._db.compute_diff()

    def get_environment_states(self) -> dict[str, EnvironmentState]:
        return self._db.get_all_environment_states()

    async def deploy_preprod(
        self, commit_sha: str, services: dict[str, str], *, deployed_by: str = "system"
    ) -> DeploymentStatus:
        """Sync preprod with the latest configuration from GitHub."""
        return await self._deploy(
            environment="preprod",
            target_versions=services,
            commit_sha=commit_sha,
            deployed_by=deployed_by,
        )

    async def deploy_prod(
        self,
        services: dict[str, str],
        commit_sha: str,
        *,
        deployed_by: str = "manual",
        subset: Optional[Iterable[str]] = None,
    ) -> DeploymentStatus:
        """Deploy selected services (default: all) to production."""
        return await self._deploy(
            environment="prod",
            target_versions=services,
            commit_sha=commit_sha,
            deployed_by=deployed_by,
            subset=subset,
        )

    async def _deploy(
        self,
        *,
        environment: str,
        target_versions: dict[str, str],
        commit_sha: str,
        deployed_by: str,
        subset: Optional[Iterable[str]] = None,
    ) -> DeploymentStatus:
        async with self._lock:
            if self._active_environment:
                raise RuntimeError(
                    f"Deployment already in progress for {self._active_environment}"
                )
            self._active_environment = environment
            try:
                result = await self._execute_deployment(
                    environment=environment,
                    target_versions=target_versions,
                    commit_sha=commit_sha,
                    deployed_by=deployed_by,
                    subset=subset,
                )
                env_literal = cast(Literal["prod", "preprod"], environment)
                return DeploymentStatus(
                    deployment_id=result.deployment_id,
                    environment=env_literal,
                    status=result.status,
                    started_at=result.started_at,
                    completed_at=result.completed_at,
                    duration_seconds=result.duration_seconds,
                    services_deployed=result.services_deployed,
                    error_message=result.error_message,
                )
            finally:
                self._active_environment = None

    async def _execute_deployment(
        self,
        *,
        environment: str,
        target_versions: dict[str, str],
        commit_sha: str,
        deployed_by: str,
        subset: Optional[Iterable[str]],
    ) -> DeploymentResult:
        services_to_deploy = self._select_services(target_versions, subset)
        started_at = datetime.now(timezone.utc)
        history_ids: dict[str, int] = {}
        for service in services_to_deploy:
            version = target_versions[service]
            history_ids[service] = self._db.create_history_record(
                environment=environment,
                service_name=service,
                version=version,
                commit_sha=commit_sha,
                deployed_by=deployed_by,
                started_at=started_at,
                status="in_progress",
            )

        stack_versions = {service: target_versions[service] for service in services_to_deploy}
        error_message: Optional[str] = None
        status: DeploymentStatusType = "success"
        try:
            await asyncio.to_thread(
                self._docker.deploy_stack, environment=environment, services=stack_versions
            )
        except Exception as exc:  # pragma: no cover - best effort logging
            logger.exception("Stack deployment failed for %s", environment)
            status = "failed"
            error_message = str(exc)

        completion_time = datetime.now(timezone.utc)
        duration = (completion_time - started_at).total_seconds()

        services_payload: list[dict[str, str]] = []
        if status == "success":
            for service in services_to_deploy:
                history_id = history_ids[service]
                self._db.upsert_deployment(
                    environment=environment,
                    service_name=service,
                    version=target_versions[service],
                    commit_sha=commit_sha,
                    deployed_at=completion_time,
                    deployed_by=deployed_by,
                )
                self._db.finalize_history_record(
                    history_id,
                    status="success",
                    completed_at=completion_time,
                    duration_seconds=duration,
                )
            health_results = await self._health.refresh_environment(
                environment, services_to_deploy
            )
            for service in services_to_deploy:
                history_id = history_ids[service]
                health = next((h for h in health_results if h.service_name == service), None)
                services_payload.append(
                    {
                        "history_id": str(history_id) if history_id else "",
                        "name": service,
                        "version": target_versions[service],
                        "health_status": health.status if health else "unknown",
                    }
                )
        else:
            for service in services_to_deploy:
                history_id = history_ids[service]
                self._db.finalize_history_record(
                    history_id,
                    status="failed",
                    completed_at=completion_time,
                    duration_seconds=duration,
                    error_message=error_message or "Stack deployment failed",
                )
                services_payload.append(
                    {
                        "history_id": str(history_id),
                        "name": service,
                        "version": target_versions[service],
                        "status": "failed",
                    }
                )
            health_results = []

        deployment_id = next(iter(history_ids.values())) if history_ids else -1
        completed_at = (
            max((health.last_checked for health in health_results), default=completion_time)
            if status == "success"
            else completion_time
        )
        duration_seconds = (completed_at - started_at).total_seconds()
        return DeploymentResult(
            deployment_id=deployment_id,
            environment=environment,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            services_deployed=services_payload,
            error_message=error_message,
        )

    def _select_services(
        self, target_versions: dict[str, str], subset: Optional[Iterable[str]]
    ) -> list[str]:
        if subset:
            requested = [svc for svc in subset if svc in target_versions]
            if not requested:
                raise ValueError("No valid services requested for deployment")
            return requested
        return sorted(target_versions.keys())

    def is_deployment_in_progress(self) -> bool:
        return self._active_environment is not None

    def get_deployment_status(self, deployment_id: int) -> Optional[DeploymentStatus]:
        record = self._db.fetch_history_record(deployment_id)
        if not record:
            return None
        group = self._db.list_history_for_started_at(
            environment=record.environment, started_at=record.started_at
        )
        status: DeploymentStatusType = "success"
        error_message = None
        completed_at = record.completed_at
        for entry in group:
            if entry.status in ("failed", "rolled_back"):
                status = "failed"
                error_message = entry.error_message
            if entry.status == "in_progress" and status != "failed":
                status = "in_progress"
            if entry.completed_at and (completed_at is None or entry.completed_at > completed_at):
                completed_at = entry.completed_at
        services_payload = [
            {
                "history_id": str(entry.id),
                "name": entry.service_name,
                "version": entry.version,
                "status": entry.status,
            }
            for entry in group
        ]
        duration_seconds = (
            (completed_at - record.started_at).total_seconds() if completed_at else None
        )
        env_literal = cast(Literal["prod", "preprod"], record.environment)
        return DeploymentStatus(
            deployment_id=deployment_id,
            environment=env_literal,
            status=status,
            started_at=record.started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            services_deployed=services_payload,
            error_message=error_message,
        )

    async def list_services(self) -> dict[str, list[DockerServiceSummary]]:
        """Return a snapshot of running Docker services grouped by environment."""
        return await asyncio.to_thread(self._docker.list_services_by_environment)
