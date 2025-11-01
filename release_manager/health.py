"""Service health management."""

from __future__ import annotations

from typing import Iterable

from release_manager.application.ports import HealthProbe, ServiceHealthRepository
from release_manager.models import ServiceHealth


class HealthService:
    """Coordinates health checks using configured ports."""

    def __init__(self, repository: ServiceHealthRepository, probe: HealthProbe):
        self._repository = repository
        self._probe = probe

    async def refresh_environment(
        self, environment: str, services: Iterable[str]
    ) -> list[ServiceHealth]:
        """Refresh health information for the provided services."""
        target_services = list(services)
        if not target_services:
            return []
        results = await self._probe.probe(environment=environment, services=target_services)
        for entry in results:
            self._repository.store(entry)
        return results

    def health_snapshot(self) -> dict[str, dict[str, ServiceHealth]]:
        """Return the latest health information grouped by environment."""
        snapshot: dict[str, dict[str, ServiceHealth]] = {}
        for entry in self._repository.list():
            snapshot.setdefault(entry.environment, {})[entry.service_name] = entry
        snapshot.setdefault("prod", {})
        snapshot.setdefault("preprod", {})
        return snapshot
