"""Docker Swarm service integrations."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import docker
from docker.errors import DockerException, NotFound
from jinja2 import Environment, FileSystemLoader

from .models import (
    DockerServiceStatusType,
    DockerServiceSummary,
    HealthStatusType,
    ServiceHealth,
)

logger = logging.getLogger(__name__)


class DockerService(ABC):
    """Common interface for Docker-backed environments."""

    def close(self) -> None:
        """Release any resources associated with the service."""

    def deploy_service(
        self,
        *,
        environment: str,
        service_name: str,
        version: str,
        compose_file_path: Optional[str] = None,
    ) -> None:
        """Backward-compatible helper that delegates to stack deployments."""
        self.deploy_stack(environment=environment, services={service_name: version})

    @abstractmethod
    def deploy_stack(self, *, environment: str, services: dict[str, str]) -> None:
        """Render and deploy a Docker stack for the provided services."""

    @abstractmethod
    def get_service_health(self, *, environment: str, service_name: str) -> ServiceHealth:
        """Check service health via Docker Swarm (or stub implementation)."""

    @abstractmethod
    def list_services_by_environment(self) -> dict[str, list[DockerServiceSummary]]:
        """Enumerate running stack services grouped by environment."""


class EnvironmentDockerService(DockerService):
    """Real Docker Swarm implementation."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        stack_template: Optional[Path] = None,
    ):
        self._stack_template = stack_template or Path(__file__).resolve().parent / "docker_templates" / "docker-stack-template.yml.j2"
        self._template_env = Environment(
            loader=FileSystemLoader(self._stack_template.parent),
            autoescape=False,
        )
        try:
            if base_url:
                self._client = docker.DockerClient(base_url=base_url)
            else:
                self._client = docker.from_env()
            self._client.ping()
            logger.debug("Connected to Docker daemon")
        except DockerException as exc:
            logger.warning("Docker connection failed: %s", exc)
            self._client = None

    def close(self) -> None:
        if self._client:
            self._client.close()

    def deploy_stack(self, *, environment: str, services: dict[str, str]) -> None:
        logger.info(
            "Deploying stack for %s with services: %s", environment, ", ".join(sorted(services))
        )
        if not self._client:
            raise RuntimeError("Docker client unavailable for stack deployment")
        if not services:
            logger.info("No services supplied for deployment; skipping stack deploy")
            return

        template = self._template_env.get_template(self._stack_template.name)
        rendered = template.render(environment=environment, services=services)
        stack_name = f"homelab-{environment}"
        with tempfile.NamedTemporaryFile("w", suffix=f"-{environment}.yml", delete=False) as tmp:
            tmp.write(rendered)
            compose_path = Path(tmp.name)
        try:
            command = [
                "docker",
                "stack",
                "deploy",
                "--with-registry-auth",
                "--compose-file",
                str(compose_path),
                stack_name,
            ]
            logger.debug("Running command: %s", " ".join(command))
            result = subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if result.stdout:
                logger.debug("docker stack deploy output: %s", result.stdout.strip())
            if result.stderr:
                logger.debug("docker stack deploy stderr: %s", result.stderr.strip())
        except subprocess.CalledProcessError as exc:
            logger.error("docker stack deploy failed: %s", exc.stderr.strip())
            raise RuntimeError(exc.stderr.strip()) from exc
        finally:
            compose_path.unlink(missing_ok=True)

    def get_service_health(self, *, environment: str, service_name: str) -> ServiceHealth:
        timestamp = datetime.now(timezone.utc)
        if not self._client:
            return ServiceHealth(
                environment=environment,
                service_name=service_name,
                status="unknown",
                replicas_running=None,
                replicas_desired=None,
                last_checked=timestamp,
                error_message="Docker client unavailable",
            )

        swarm_service = f"homelab-{environment}_{service_name}"
        try:
            service = self._client.services.get(swarm_service)
        except NotFound:
            return ServiceHealth(
                environment=environment,
                service_name=service_name,
                status="unknown",
                replicas_running=0,
                replicas_desired=0,
                last_checked=timestamp,
                error_message="Service not found",
            )
        except DockerException as exc:
            logger.error("Failed to fetch health for %s: %s", swarm_service, exc)
            return ServiceHealth(
                environment=environment,
                service_name=service_name,
                status="unknown",
                replicas_running=None,
                replicas_desired=None,
                last_checked=timestamp,
                error_message=str(exc),
            )

        tasks = service.tasks()
        running = sum(1 for task in tasks if task.get("Status", {}).get("State") == "running")
        desired = service.attrs["Spec"]["Mode"]["Replicated"]["Replicas"]
        status: HealthStatusType = "healthy" if running == desired else "unhealthy"
        return ServiceHealth(
            environment=environment,
            service_name=service_name,
            status=status,
            replicas_running=running,
            replicas_desired=desired,
            last_checked=timestamp,
            error_message=None,
        )

    def list_services_by_environment(self) -> dict[str, list[DockerServiceSummary]]:
        if not self._client:
            return {}

        try:
            services = self._client.services.list()
        except DockerException as exc:  # pragma: no cover - docker errors depend on host state
            logger.error("Failed to list docker services: %s", exc)
            return {}

        grouped: dict[str, list[DockerServiceSummary]] = {}
        for service in services:
            name = service.name or ""
            if not name.startswith("homelab-") or "_" not in name:
                continue

            env_segment, _, svc_segment = name.partition("_")
            environment = env_segment.replace("homelab-", "", 1)
            if not environment or not svc_segment:
                continue

            attrs = service.attrs or {}
            spec = attrs.get("Spec", {})
            mode = spec.get("Mode", {})
            task_template = spec.get("TaskTemplate", {})
            container_spec = task_template.get("ContainerSpec", {})
            desired = mode.get("Replicated", {}).get("Replicas")
            try:
                tasks = service.tasks()
            except DockerException:  # pragma: no cover - depends on docker state
                tasks = []
            running = sum(1 for task in tasks if task.get("Status", {}).get("State") == "running")
            status: DockerServiceStatusType
            if desired is None:
                status = "unknown"
            elif desired == 0 or running == 0:
                status = "stopped"
            elif running < desired:
                status = "degraded"
            else:
                status = "healthy"

            summary = DockerServiceSummary(
                environment=environment,
                service_name=svc_segment,
                stack_service=name,
                image=container_spec.get("Image"),
                replicas_desired=desired,
                replicas_running=running,
                status=status,
                created_at=self._parse_timestamp(attrs.get("CreatedAt")),
                updated_at=self._parse_timestamp(attrs.get("UpdatedAt")),
                message=self._extract_update_message(attrs),
            )
            grouped.setdefault(environment, []).append(summary)

        for env_services in grouped.values():
            env_services.sort(key=lambda svc: svc.service_name)
        return grouped

    @staticmethod
    def _parse_timestamp(raw: Optional[str]) -> Optional[datetime]:
        if not raw:
            return None
        try:
            cleaned = raw.replace("Z", "+00:00")
            if "." in cleaned:
                head, tail = cleaned.split(".", 1)
                if "+" in tail:
                    fraction, tz = tail.split("+", 1)
                    fraction = fraction[:6]
                    cleaned = f"{head}.{fraction}+{tz}"
                elif "-" in tail:
                    fraction, tz = tail.split("-", 1)
                    fraction = fraction[:6]
                    cleaned = f"{head}.{fraction}-{tz}"
                else:
                    cleaned = f"{head}.{tail[:6]}"
            return datetime.fromisoformat(cleaned)
        except ValueError:
            logger.debug("Unable to parse docker timestamp: %s", raw)
            return None

    @staticmethod
    def _extract_update_message(attrs: dict[str, Any]) -> Optional[str]:
        update_status = attrs.get("UpdateStatus")
        if isinstance(update_status, dict):
            message = update_status.get("Message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        return None


class StubbedDockerService(DockerService):
    """Deterministic sample data for development and testing."""

    def __init__(self, *, environment_name: str):
        self._environment = self._normalize_environment(environment_name or "dev")
        self._snapshots = self._build_snapshots()

    def close(self) -> None:
        return None

    def deploy_stack(self, *, environment: str, services: dict[str, str]) -> None:
        logger.debug(
            "Stubbed docker deploy for %s (%s services)", environment, len(services or {})
        )

    def get_service_health(self, *, environment: str, service_name: str) -> ServiceHealth:
        timestamp = datetime.now(timezone.utc)
        normalized = self._normalize_environment(environment)
        services = self._snapshots.get(normalized)
        if not services:
            return ServiceHealth(
                environment=environment,
                service_name=service_name,
                status="unknown",
                replicas_running=None,
                replicas_desired=None,
                last_checked=timestamp,
                error_message="No stub data for environment",
            )
        summary = next((svc for svc in services if svc.service_name == service_name), None)
        if not summary:
            return ServiceHealth(
                environment=environment,
                service_name=service_name,
                status="unknown",
                replicas_running=None,
                replicas_desired=None,
                last_checked=timestamp,
                error_message="Service not found in stub data",
            )
        status: HealthStatusType = "healthy"
        if summary.status in {"degraded", "stopped"}:
            status = "unhealthy"
        elif summary.status == "unknown":
            status = "unknown"
        return ServiceHealth(
            environment=environment,
            service_name=service_name,
            status=status,
            replicas_running=summary.replicas_running,
            replicas_desired=summary.replicas_desired,
            last_checked=timestamp,
            error_message=summary.message,
        )

    def list_services_by_environment(self) -> dict[str, list[DockerServiceSummary]]:
        environment = self._environment
        normalized = self._normalize_environment(self._environment)
        if normalized not in {"dev", "test"}:
            return {}
        key = normalized
        # Return deep copies to avoid accidental mutation.
        return {
            key: [
                DockerServiceSummary(
                    environment=summary.environment,
                    service_name=summary.service_name,
                    stack_service=summary.stack_service,
                    image=summary.image,
                    replicas_desired=summary.replicas_desired,
                    replicas_running=summary.replicas_running,
                    status=summary.status,
                    created_at=summary.created_at,
                    updated_at=summary.updated_at,
                    message=summary.message,
                )
                for summary in self._snapshots[key]
            ]
        }

    def _build_snapshots(self) -> dict[str, list[DockerServiceSummary]]:
        now = datetime.now(timezone.utc)
        repo_prefix = "ghcr.io/oscar-barlow/home.services"

        dev_services = [
            DockerServiceSummary(
                environment="dev",
                service_name="api",
                stack_service="homelab-dev_api",
                image=f"{repo_prefix}-api:2025.11.03",
                replicas_desired=1,
                replicas_running=1,
                status="healthy",
                created_at=now - timedelta(hours=2),
                updated_at=now - timedelta(minutes=17),
                message="Node running on dev-01",
            ),
            DockerServiceSummary(
                environment="dev",
                service_name="scheduler",
                stack_service="homelab-dev_scheduler",
                image=f"{repo_prefix}-scheduler:2025.10.29",
                replicas_desired=1,
                replicas_running=1,
                status="healthy",
                created_at=now - timedelta(days=1, hours=3),
                updated_at=now - timedelta(minutes=5),
                message=None,
            ),
            DockerServiceSummary(
                environment="dev",
                service_name="inspector",
                stack_service="homelab-dev_inspector",
                image=f"{repo_prefix}-inspector:2025.09.12",
                replicas_desired=1,
                replicas_running=0,
                status="stopped",
                created_at=now - timedelta(days=12),
                updated_at=now - timedelta(hours=6),
                message="Paused while feature flags disabled",
            ),
        ]

        test_services = [
            DockerServiceSummary(
                environment="test",
                service_name="api",
                stack_service="homelab-test_api",
                image=f"{repo_prefix}-api:2025.11.03",
                replicas_desired=1,
                replicas_running=1,
                status="healthy",
                created_at=now - timedelta(hours=4),
                updated_at=now - timedelta(minutes=22),
                message="Sample test deployment",
            ),
            DockerServiceSummary(
                environment="test",
                service_name="scheduler",
                stack_service="homelab-test_scheduler",
                image=f"{repo_prefix}-scheduler:2025.10.29",
                replicas_desired=1,
                replicas_running=1,
                status="healthy",
                created_at=now - timedelta(days=2),
                updated_at=now - timedelta(minutes=9),
                message=None,
            ),
        ]

        for items in (dev_services, test_services):
            items.sort(key=lambda svc: svc.service_name)

        return {"dev": dev_services, "test": test_services}

    @staticmethod
    def _normalize_environment(environment: str) -> str:
        env = environment.lower()
        if env.startswith("dev"):
            return "dev"
        if env.startswith("test"):
            return "test"
        return env


# Backwards compatibility for older imports.
DockerServiceClient = EnvironmentDockerService

__all__ = [
    "DockerService",
    "EnvironmentDockerService",
    "StubbedDockerService",
    "DockerServiceClient",
]
