"""Asynchronous poller that keeps preprod in sync with manifests."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from release_manager.application.ports import ManifestFetcher
from release_manager.application.services.deployment_service import DeploymentService
from release_manager.application.services.environment_service import EnvironmentService
from release_manager.config import Settings

logger = logging.getLogger(__name__)


class EnvironmentPoller:
    """Background task that polls the manifest source for environment changes."""

    def __init__(
        self,
        *,
        settings: Settings,
        manifest_fetcher: ManifestFetcher,
        deployment_service: DeploymentService,
        environment_service: EnvironmentService,
    ):
        self._settings = settings
        self._fetcher = manifest_fetcher
        self._deployment_service = deployment_service
        self._environment_service = environment_service
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._latest_commit: Optional[str] = None

    async def start(self) -> None:
        if self._task:
            return
        self._stop_event.clear()
        # Seed latest commit from current preprod state if available.
        preprod_state = self._environment_service.get_environment("preprod")
        if preprod_state:
            self._latest_commit = preprod_state.commit_sha
        self._task = asyncio.create_task(self._run(), name="preprod-poller")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop_event.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        logger.info(
            "Starting manifest poller for %s at %s-second intervals",
            self._settings.preprod_env_path,
            self._settings.poll_interval_seconds,
        )
        while not self._stop_event.is_set():
            try:
                await self.check_for_changes()
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Poller iteration failed")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._settings.poll_interval_seconds
                )
            except asyncio.TimeoutError:
                continue
        logger.info("Poller stopped")

    async def check_for_changes(self) -> None:
        env_file = await self._fetcher.fetch(self._settings.preprod_env_path)
        if not env_file.services:
            logger.debug("No services discovered in preprod manifest; skipping deployment")
            return
        if env_file.commit_sha == self._latest_commit:
            logger.debug("No new commit detected for preprod env file")
            return
        logger.info("Detected new commit %s for preprod; triggering deployment", env_file.commit_sha)
        await self._deployment_service.deploy_preprod(
            commit_sha=env_file.commit_sha,
            services=env_file.services,
            deployed_by="system",
        )
        self._latest_commit = env_file.commit_sha
