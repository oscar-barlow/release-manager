"""Deployment orchestration service."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional, Sequence

from release_manager.application.ports import (
    Clock,
    ContainerOrchestrator,
    DeploymentHistoryRepository,
    EnvironmentStateRepository,
    Logger,
)
from release_manager.health import HealthService
from release_manager.models import (
    DeploymentHistory,
    DeploymentStatus,
    DeploymentStatusType,
    HealthStatusType,
    ServiceHealth,
)


@dataclass(slots=True)
class _ServiceHistoryContext:
    service_name: str
    version: str
    history_id: int


class DeploymentService:
    """Coordinates deployments via defined ports."""

    def __init__(
        self,
        *,
        environment_repo: EnvironmentStateRepository,
        history_repo: DeploymentHistoryRepository,
        orchestrator: ContainerOrchestrator,
        health_service: HealthService,
        clock: Clock,
        logger: Logger,
    ):
        self._env_repo = environment_repo
        self._history_repo = history_repo
        self._orchestrator = orchestrator
        self._health_service = health_service
        self._clock = clock
        self._logger = logger
        self._lock = asyncio.Lock()
        self._active_environment: Optional[str] = None

    def is_deployment_in_progress(self) -> bool:
        return self._active_environment is not None

    async def deploy_preprod(
        self, *, commit_sha: str, services: dict[str, str], deployed_by: str = "system"
    ) -> DeploymentStatus:
        return await self._deploy(
            environment="preprod",
            target_versions=services,
            commit_sha=commit_sha,
            deployed_by=deployed_by,
            subset=None,
        )

    async def deploy_prod(
        self,
        *,
        services: dict[str, str],
        commit_sha: str,
        deployed_by: str = "manual",
        subset: Optional[Iterable[str]] = None,
    ) -> DeploymentStatus:
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
        subset: Optional[Iterable[str]],
    ) -> DeploymentStatus:
        async with self._lock:
            if self._active_environment:
                raise RuntimeError(
                    f"Deployment already in progress for {self._active_environment}"
                )
            self._active_environment = environment
            try:
                context = await self._execute_deployment(
                    environment=environment,
                    target_versions=target_versions,
                    commit_sha=commit_sha,
                    deployed_by=deployed_by,
                    subset=subset,
                )
                return context
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
    ) -> DeploymentStatus:
        services_to_deploy = self._select_services(target_versions, subset)
        if not services_to_deploy:
            raise ValueError("No services supplied for deployment")

        started_at = self._clock.now()
        history_records = self._start_history(
            environment=environment,
            commit_sha=commit_sha,
            deployed_by=deployed_by,
            started_at=started_at,
            target_versions=target_versions,
            services_to_deploy=services_to_deploy,
        )

        error_message: Optional[str] = None
        self._last_health_probe: list[ServiceHealth] = []
        status: DeploymentStatusType = "success"
        try:
            await asyncio.to_thread(
                self._orchestrator.deploy_stack,
                environment=environment,
                services={svc: target_versions[svc] for svc in services_to_deploy},
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            self._logger.error("Deployment failed for %s: %s", environment, exc)
            status = "failed"
            error_message = str(exc)

        completed_at = self._clock.now()
        duration_seconds = (completed_at - started_at).total_seconds()

        if status == "success":
            await self._handle_success(
                environment=environment,
                commit_sha=commit_sha,
                deployed_by=deployed_by,
                completed_at=completed_at,
                duration_seconds=duration_seconds,
                history_records=history_records,
                target_versions=target_versions,
            )
        else:
            self._handle_failure(
                completed_at=completed_at,
                duration_seconds=duration_seconds,
                error_message=error_message,
                history_records=history_records,
                target_versions=target_versions,
            )

        services_payload = self._build_services_payload(
            status=status,
            history_records=history_records,
            target_versions=target_versions,
            environment=environment,
        )

        return DeploymentStatus(
            deployment_id=history_records[0].history_id if history_records else -1,
            environment=environment,  # type: ignore[arg-type]
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            services_deployed=services_payload,
            error_message=error_message,
        )

    def _start_history(
        self,
        *,
        environment: str,
        commit_sha: str,
        deployed_by: str,
        started_at: datetime,
        target_versions: dict[str, str],
        services_to_deploy: Sequence[str],
    ) -> list[_ServiceHistoryContext]:
        entries: list[_ServiceHistoryContext] = []
        for service in services_to_deploy:
            version = target_versions[service]
            history_id = self._history_repo.start_history(
                environment=environment,
                service_name=service,
                version=version,
                commit_sha=commit_sha,
                deployed_by=deployed_by,
                started_at=started_at,
            )
            entries.append(
                _ServiceHistoryContext(service_name=service, version=version, history_id=history_id)
            )
        return entries

    async def _handle_success(
        self,
        *,
        environment: str,
        commit_sha: str,
        deployed_by: str,
        completed_at: datetime,
        duration_seconds: float,
        history_records: list[_ServiceHistoryContext],
        target_versions: dict[str, str],
    ) -> None:
        for record in history_records:
            self._history_repo.complete_history(
                record.history_id,
                status="success",
                completed_at=completed_at,
                duration_seconds=duration_seconds,
                error_message=None,
            )
            self._env_repo.record_deployment(
                environment=environment,
                service_name=record.service_name,
                version=target_versions[record.service_name],
                commit_sha=commit_sha,
                deployed_at=completed_at,
                deployed_by=deployed_by,
            )

        health_results = await self._health_service.refresh_environment(
            environment, [record.service_name for record in history_records]
        )
        self._last_health_probe = health_results

    def _handle_failure(
        self,
        *,
        completed_at: datetime,
        duration_seconds: float,
        error_message: Optional[str],
        history_records: list[_ServiceHistoryContext],
        target_versions: dict[str, str],
    ) -> None:
        for record in history_records:
            self._history_repo.complete_history(
                record.history_id,
                status="failed",
                completed_at=completed_at,
                duration_seconds=duration_seconds,
                error_message=error_message or "Deployment failed",
            )
        self._last_health_probe = []

    def _build_services_payload(
        self,
        *,
        status: DeploymentStatusType,
        history_records: list[_ServiceHistoryContext],
        target_versions: dict[str, str],
        environment: str,
    ) -> list[dict[str, str]]:
        payload: list[dict[str, str]] = []
        health_map: dict[str, ServiceHealth] = {
            health.service_name: health for health in getattr(self, "_last_health_probe", [])
        }
        for record in history_records:
            data = {
                "history_id": str(record.history_id),
                "name": record.service_name,
                "version": target_versions[record.service_name],
            }
            if status == "success":
                health = health_map.get(record.service_name)
                health_status: Optional[HealthStatusType] = health.status if health else "unknown"
                data["health_status"] = health_status or "unknown"
            else:
                data["status"] = "failed"
            payload.append(data)
        return payload

    def _select_services(
        self, target_versions: dict[str, str], subset: Optional[Iterable[str]]
    ) -> list[str]:
        if subset is None:
            return sorted(target_versions.keys())
        requested = [name for name in subset if name in target_versions]
        if not requested:
            raise ValueError("No valid services requested for deployment")
        return sorted(requested)

    def get_deployment_status(self, deployment_id: int) -> Optional[DeploymentStatus]:
        record = self._history_repo.fetch_history(deployment_id)
        if not record:
            return None
        group = self._history_repo.list_history_for_started_at(
            environment=record.environment, started_at=record.started_at
        )
        status: DeploymentStatusType = "success"
        error_message: Optional[str] = None
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
        return DeploymentStatus(
            deployment_id=deployment_id,
            environment=record.environment,  # type: ignore[arg-type]
            status=status,
            started_at=record.started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            services_deployed=services_payload,
            error_message=error_message,
        )

    def list_history(
        self,
        *,
        environment: Optional[str],
        service: Optional[str],
        limit: int,
        offset: int,
    ) -> tuple[list[DeploymentHistory], int]:
        return self._history_repo.list_history(
            environment=environment, service=service, limit=limit, offset=offset
        )

    def get_history_record(self, history_id: int) -> Optional[DeploymentHistory]:
        return self._history_repo.fetch_history(history_id)

    def list_related_history(
        self, *, environment: str, started_at: datetime
    ) -> list[DeploymentHistory]:
        return self._history_repo.list_history_for_started_at(
            environment=environment, started_at=started_at
        )
