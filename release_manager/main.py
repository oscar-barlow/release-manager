"""FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import Settings, get_settings
from .database import Database
from .deployer import DeploymentEngine
from .docker_client import DockerService, EnvironmentDockerService, StubbedDockerService
from .github import GitHubClient
from .health import HealthService
from .poller import EnvironmentPoller
from .routers import api, pages, ui

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
    health_service = HealthService(database, docker_client)
    github_client = GitHubClient(repo=settings.github_repo, token=settings.github_token)
    deployment_engine = DeploymentEngine(
        database=database,
        docker_client=docker_client,
        health_service=health_service,
        settings=settings,
    )
    poller = EnvironmentPoller(
        settings=settings,
        database=database,
        github_client=github_client,
        deployment_engine=deployment_engine,
    )

    app.state.settings = settings
    app.state.database = database
    app.state.deployment_engine = deployment_engine
    app.state.health_service = health_service
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
