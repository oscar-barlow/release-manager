"""Service health management."""

from __future__ import annotations

import asyncio
from typing import Iterable, Optional

from .database import Database
from .docker_client import DockerService
from .models import ServiceHealth


class HealthService:
    """Coordinates health checks using the Docker client and persists the results."""

    def __init__(self, database: Database, docker_client: DockerService):
        self._db = database
        self._docker = docker_client

    async def refresh_environment(
        self, environment: str, services: Optional[Iterable[str]] = None
    ) -> list[ServiceHealth]:
        """Refresh health information for the requested services."""
        env_state = self._db.get_environment_state(environment)
        if not env_state:
            return []
        target_services = list(services) if services else sorted(env_state.services.keys())
        results: list[ServiceHealth] = []
        for service in target_services:
            health = await asyncio.to_thread(
                self._docker.get_service_health, environment=environment, service_name=service
            )
            self._db.update_service_health(health)
            results.append(health)
        return results

    def health_snapshot(self) -> dict[str, dict[str, ServiceHealth]]:
        """Return the latest health information grouped by environment."""
        snapshot: dict[str, dict[str, ServiceHealth]] = {"prod": {}, "preprod": {}}
        for env in snapshot.keys():
            for entry in self._db.list_service_health(env):
                snapshot[env][entry.service_name] = entry
        return snapshot
