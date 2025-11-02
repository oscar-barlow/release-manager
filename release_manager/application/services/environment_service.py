"""Environment-focused application services."""

from __future__ import annotations

from typing import Optional

from release_manager.application.ports import EnvironmentStateRepository
from release_manager.models import ChangeType, EnvironmentState, ServiceDiff


class EnvironmentService:
    """Provides read-oriented operations over environment states."""

    def __init__(self, repository: EnvironmentStateRepository):
        self._repository = repository

    def get_environment(self, environment: str) -> Optional[EnvironmentState]:
        return self._repository.get_environment(environment)

    def get_all_environments(self) -> dict[str, EnvironmentState]:
        return self._repository.get_all_environments()

    def diff_environments(self) -> list[ServiceDiff]:
        states = self._repository.get_all_environments()
        prod = states.get("prod")
        preprod = states.get("preprod")
        return self._compute_diff(prod, preprod)

    @staticmethod
    def _compute_diff(
        prod: Optional[EnvironmentState], preprod: Optional[EnvironmentState]
    ) -> list[ServiceDiff]:
        if not prod and not preprod:
            return []
        prod_services = prod.services if prod else {}
        preprod_services = preprod.services if preprod else {}
        all_services = sorted(set(prod_services.keys()) | set(preprod_services.keys()))
        diff: list[ServiceDiff] = []
        for service in all_services:
            prod_version = prod_services.get(service)
            preprod_version = preprod_services.get(service)
            if prod_version and preprod_version:
                change_type: ChangeType = (
                    "no_change" if prod_version == preprod_version else "version_bump"
                )
            elif preprod_version and not prod_version:
                change_type = "new_service"
            else:
                change_type = "removed_service"
            diff.append(
                ServiceDiff(
                    service=service,
                    prod_version=prod_version,
                    preprod_version=preprod_version,
                    change_type=change_type,
                )
            )
        return diff
