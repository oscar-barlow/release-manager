"""Thin wrapper around Docker SDK with graceful fallbacks for constrained environments."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import docker
from docker.errors import DockerException, NotFound
from jinja2 import Environment, FileSystemLoader

from .models import HealthStatusType, ServiceHealth

logger = logging.getLogger(__name__)


class DockerServiceClient:
    """Handles Docker Swarm operations required by the deployment engine."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        stub_mode: bool = False,
        stack_template: Optional[Path] = None,
    ):
        self._stub_mode = stub_mode
        self._stack_template = stack_template or Path(__file__).resolve().parent / "docker_templates" / "docker-stack-template.yml.j2"
        self._template_env = Environment(
            loader=FileSystemLoader(self._stack_template.parent), autoescape=False
        )
        if self._stub_mode:
            logger.info("Docker client initialised in stub mode; no real deployments will run.")
            self._client = None
            return
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
        """Render and deploy a Docker stack for the provided services."""
        logger.info(
            "Deploying stack for %s with services: %s", environment, ", ".join(sorted(services))
        )
        if self._stub_mode:
            logger.debug("Stub mode enabled; skipping stack deployment for %s", environment)
            return
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

    def deploy_service(
        self,
        *,
        environment: str,
        service_name: str,
        version: str,
        compose_file_path: Optional[str] = None,
    ) -> None:
        """Backward-compatible helper for tests; delegates to deploy_stack."""
        self.deploy_stack(environment=environment, services={service_name: version})

    def get_service_health(self, *, environment: str, service_name: str) -> ServiceHealth:
        """Check service health via Docker Swarm."""
        timestamp = datetime.now(timezone.utc)
        if self._stub_mode or not self._client:
            return ServiceHealth(
                environment=environment,
                service_name=service_name,
                status="unknown",
                replicas_running=None,
                replicas_desired=None,
                last_checked=timestamp,
                error_message="Stub mode enabled" if self._stub_mode else "Docker client unavailable",
            )

        swarm_service = f"homelab-{environment}_{service_name}"
        try:
            service = self._client.services.get(swarm_service)
            tasks = service.tasks()
            running = sum(1 for task in tasks if task["Status"]["State"] == "running")
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
