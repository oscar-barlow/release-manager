"""Thin wrapper around Docker SDK with graceful fallbacks for constrained environments."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import docker
from docker.errors import DockerException, NotFound

from .models import HealthStatusType, ServiceHealth

logger = logging.getLogger(__name__)


class DockerServiceClient:
    """Handles Docker Swarm operations required by the deployment engine."""

    def __init__(self, *, base_url: Optional[str] = None, stub_mode: bool = False):
        self._stub_mode = stub_mode
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

    def deploy_service(
        self,
        *,
        environment: str,
        service_name: str,
        version: str,
        compose_file_path: Optional[str] = None,
    ) -> None:
        """
        Trigger a deployment for a service.

        In this reference implementation we log the operation and rely on tests to mock
        out real Docker calls. When a Docker client is available we attempt to update
        the service image tag by appending the version value.
        """
        logger.info(
            "Deploying service %s in %s to version %s", service_name, environment, version
        )
        if self._stub_mode:
            logger.debug("Stub mode enabled; skipping Docker deployment for %s", service_name)
            return
        if not self._client:
            return

        swarm_service = f"homelab-{environment}_{service_name}"
        try:
            service = self._client.services.get(swarm_service)
        except NotFound:
            logger.warning("Service %s not found in Docker Swarm", swarm_service)
            return
        except DockerException as exc:
            logger.error("Failed to locate service %s: %s", swarm_service, exc)
            return

        try:
            spec = service.attrs["Spec"]
            task_template = spec.get("TaskTemplate", {})
            container_spec = task_template.get("ContainerSpec", {})
            image = container_spec.get("Image")
            if image and ":" in image:
                base_image = image.split(":", 1)[0]
            else:
                base_image = image or service_name
            new_image = f"{base_image}:{version}"
            service.update(image=new_image, fetch_current_spec=True)
            logger.debug("Updated service %s image to %s", swarm_service, new_image)
        except DockerException as exc:
            logger.error("Failed to update service %s: %s", swarm_service, exc)

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
