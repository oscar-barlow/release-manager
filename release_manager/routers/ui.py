"""HTMX UI fragment endpoints."""

from __future__ import annotations

from typing import Any, Optional, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..application.services.deployment_service import DeploymentService
from ..application.services.environment_service import EnvironmentService
from ..docker_client import DockerService
from ..health import HealthService

router = APIRouter(prefix="/ui", tags=["ui"])
templates = Jinja2Templates(directory="templates")


def get_deployment_service(request: Request) -> DeploymentService:
    return cast(DeploymentService, request.app.state.deployment_service)


def get_environment_service(request: Request) -> EnvironmentService:
    return cast(EnvironmentService, request.app.state.environment_service)


def get_health(request: Request) -> HealthService:
    return cast(HealthService, request.app.state.health_service)


def get_docker_client(request: Request) -> DockerService:
    return cast(DockerService, request.app.state.docker_client)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    deployment_service: DeploymentService = Depends(get_deployment_service),
    environment_service: EnvironmentService = Depends(get_environment_service),
    health_service: HealthService = Depends(get_health),
) -> HTMLResponse:
    states = environment_service.get_all_environments()
    diff = environment_service.diff_environments()
    health_snapshot = health_service.health_snapshot()
    context = {
        "request": request,
        "states": states,
        "diff": diff,
        "health": health_snapshot,
    }
    return templates.TemplateResponse("partials/dashboard.html", context)


@router.get("/environments", response_class=HTMLResponse)
async def environments(
    request: Request,
    environment_service: EnvironmentService = Depends(get_environment_service),
    health_service: HealthService = Depends(get_health),
) -> HTMLResponse:
    context = {
        "request": request,
        "states": environment_service.get_all_environments(),
        "health": health_service.health_snapshot(),
    }
    return templates.TemplateResponse("partials/environments.html", context)


@router.get("/diff", response_class=HTMLResponse)
async def diff(
    request: Request,
    environment_service: EnvironmentService = Depends(get_environment_service),
) -> HTMLResponse:
    context = {"request": request, "diff": environment_service.diff_environments()}
    return templates.TemplateResponse("partials/diff.html", context)


@router.post("/deploy/prod", response_class=HTMLResponse)
async def trigger_deploy_prod(
    request: Request,
    deployment_service: DeploymentService = Depends(get_deployment_service),
    environment_service: EnvironmentService = Depends(get_environment_service),
) -> HTMLResponse:
    payload: dict[str, Any] = {}
    try:
        json_body = await request.json()
        if isinstance(json_body, dict):
            payload = json_body
    except Exception:
        form = await request.form()
        services_form = [item for item in form.getlist("services") if isinstance(item, str)]
        payload = {
            "confirm": form.get("confirm", "true"),
            "services": services_form,
        }

    confirm = str(payload.get("confirm", True)).lower() in {"true", "1", "yes", "on"}
    services_raw = payload.get("services")
    services: Optional[list[str]]
    if services_raw is None:
        services = None
    elif isinstance(services_raw, str):
        services = [services_raw]
    elif isinstance(services_raw, list):
        services = [item for item in services_raw if isinstance(item, str)]
    else:
        services = None
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    preprod_state = environment_service.get_environment("preprod")
    if not preprod_state:
        raise HTTPException(status_code=409, detail="Preprod environment not initialised")
    if services is not None and len(services) == 0:
        context: dict[str, Any] = {
            "request": request,
            "status": None,
            "error": "Select at least one service to deploy.",
        }
        return templates.TemplateResponse("partials/deploy-status.html", context)
    result = await deployment_service.deploy_prod(
        services=preprod_state.services,
        commit_sha=preprod_state.commit_sha,
        subset=services,
    )
    response_context: dict[str, Any] = {"request": request, "status": result}
    return templates.TemplateResponse("partials/deploy-status.html", response_context)


@router.get("/deploy/status/{deployment_id}", response_class=HTMLResponse)
def deployment_status(
    deployment_id: int,
    request: Request,
    deployment_service: DeploymentService = Depends(get_deployment_service),
) -> HTMLResponse:
    status_obj = deployment_service.get_deployment_status(deployment_id)
    if not status_obj:
        raise HTTPException(status_code=404, detail="Deployment not found")
    context = {"request": request, "status": status_obj}
    return templates.TemplateResponse("partials/deploy-status.html", context)


@router.get("/history", response_class=HTMLResponse)
async def history(
    request: Request,
    environment: Optional[str] = Query(default=None),
    service: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    deployment_service: DeploymentService = Depends(get_deployment_service),
) -> HTMLResponse:
    history, total = deployment_service.list_history(
        environment=environment, service=service, limit=limit, offset=offset
    )
    context = {
        "request": request,
        "history": history,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
    return templates.TemplateResponse("partials/history.html", context)


@router.get("/health", response_class=HTMLResponse)
async def health(
    request: Request,
    health_service: HealthService = Depends(get_health),
) -> HTMLResponse:
    context = {"request": request, "health": health_service.health_snapshot()}
    return templates.TemplateResponse("partials/health.html", context)


@router.get("/directory", response_class=HTMLResponse)
async def directory(
    request: Request,
    docker_client: DockerService = Depends(get_docker_client),
) -> HTMLResponse:
    services = docker_client.list_services_by_environment()
    context = {"request": request, "services": services}
    return templates.TemplateResponse("partials/directory.html", context)
