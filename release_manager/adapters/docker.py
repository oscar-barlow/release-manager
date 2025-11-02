"""Docker-based adapters for container orchestration and health."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable

from release_manager.application.ports import ContainerOrchestrator, HealthProbe
from release_manager.docker_client import DockerService
from release_manager.models import ServiceHealth


@dataclass(slots=True)
class DockerContainerOrchestrator(ContainerOrchestrator):
    client: DockerService

    def deploy_stack(self, *, environment: str, services: dict[str, str]) -> None:
        self.client.deploy_stack(environment=environment, services=services)


@dataclass(slots=True)
class DockerHealthProbe(HealthProbe):
    client: DockerService

    async def probe(self, *, environment: str, services: Iterable[str]) -> list[ServiceHealth]:
        async def _fetch(service: str) -> ServiceHealth:
            return await asyncio.to_thread(
                self.client.get_service_health, environment=environment, service_name=service
            )

        tasks = [_fetch(service) for service in services]
        if not tasks:
            return []
        return await asyncio.gather(*tasks)
