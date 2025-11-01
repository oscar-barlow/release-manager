"""Asynchronous poller that keeps preprod in sync with GitHub."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .config import Settings
from .database import Database
from .deployer import DeploymentEngine
from .github import GitHubClient

logger = logging.getLogger(__name__)


class EnvironmentPoller:
    """Background task that polls GitHub for environment changes."""

    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        github_client: GitHubClient,
        deployment_engine: DeploymentEngine,
    ):
        self._settings = settings
        self._database = database
        self._github = github_client
        self._deployer = deployment_engine
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._latest_commit: Optional[str] = None

    async def start(self) -> None:
        if self._task:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="preprod-poller")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop_event.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        logger.info(
            "Starting GitHub poller for %s at %s-second intervals",
            self._settings.preprod_env_path,
            self._settings.poll_interval_seconds,
        )
        initial_state = self._database.get_environment_state("preprod")
        if initial_state:
            self._latest_commit = initial_state.commit_sha
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
        env_file = await self._github.fetch_env_file(self._settings.preprod_env_path)
        if not env_file.services:
            logger.debug("No services discovered in preprod env file; skipping deployment")
            return
        if env_file.commit_sha == self._latest_commit:
            logger.debug("No new commit detected for preprod env file")
            return
        logger.info("Detected new commit %s for preprod; triggering deployment", env_file.commit_sha)
        await self._deployer.deploy_preprod(env_file.commit_sha, env_file.services)
        self._latest_commit = env_file.commit_sha
