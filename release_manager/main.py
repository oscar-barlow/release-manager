"""FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from release_manager.adapters.docker import DockerContainerOrchestrator, DockerHealthProbe
from release_manager.adapters.github_adapter import GitHubManifestFetcher
from release_manager.adapters.persistence import (
    DatabaseDeploymentHistoryRepository,
    DatabaseEnvironmentRepository,
    DatabaseServiceHealthRepository,
)
from release_manager.adapters.time import SystemClock
from release_manager.application.services.deployment_service import DeploymentService
from release_manager.application.services.environment_service import EnvironmentService
from release_manager.config import Settings, get_settings
from release_manager.database import Database
from release_manager.docker_client import DockerService, EnvironmentDockerService, StubbedDockerService
from release_manager.github import GitHubClient
from release_manager.health import HealthService
from release_manager.poller import EnvironmentPoller
from release_manager.routers import api, pages, ui

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    database = Database(settings.database_path)
    database.initialize_schema()

    env_name = settings.environment_name
    use_stub = settings.stub_mode and (env_name.startswith("dev") or env_name.startswith("test"))
    docker_client: DockerService
    if use_stub:
        docker_client = StubbedDockerService(environment_name=settings.environment_name)
    else:
        docker_client = EnvironmentDockerService(base_url=settings.docker_host)

    environment_repository = DatabaseEnvironmentRepository(database)
    history_repository = DatabaseDeploymentHistoryRepository(database)
    health_repository = DatabaseServiceHealthRepository(database)

    orchestrator = DockerContainerOrchestrator(docker_client)
    health_probe = DockerHealthProbe(docker_client)
    clock = SystemClock()

    health_service = HealthService(health_repository, health_probe)
    environment_service = EnvironmentService(environment_repository)
    deployment_service = DeploymentService(
        environment_repo=environment_repository,
        history_repo=history_repository,
        orchestrator=orchestrator,
        health_service=health_service,
        clock=clock,
        logger=logger,
    )
    github_client = GitHubClient(repo=settings.github_repo, token=settings.github_token)
    manifest_fetcher = GitHubManifestFetcher(github_client)
    poller = EnvironmentPoller(
        settings=settings,
        manifest_fetcher=manifest_fetcher,
        deployment_service=deployment_service,
        environment_service=environment_service,
    )

    app.state.settings = settings
    app.state.database = database
    app.state.environment_repository = environment_repository
    app.state.history_repository = history_repository
    app.state.service_health_repository = health_repository
    app.state.environment_service = environment_service
    app.state.deployment_service = deployment_service
    app.state.health_service = health_service
    app.state.docker_client = docker_client
    app.state.github_client = github_client
    app.state.poller = poller

    if settings.poll_interval_seconds > 0:
        await poller.start()
    try:
        yield
    finally:
        if settings.poll_interval_seconds > 0:
            await poller.stop()
        await github_client.close()
        docker_client.close()
        database.close()


app = FastAPI(title="Release Manager", lifespan=lifespan)

app.include_router(api.router)
app.include_router(ui.router)
app.include_router(pages.router)
app.mount("/static", StaticFiles(directory="static"), name="static")
