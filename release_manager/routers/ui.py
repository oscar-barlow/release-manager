"""HTMX UI fragment endpoints."""

from __future__ import annotations

from typing import Any, Optional, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..database import Database
from ..deployer import DeploymentEngine
from ..health import HealthService

router = APIRouter(prefix="/ui", tags=["ui"])
templates = Jinja2Templates(directory="templates")


def get_engine(request: Request) -> DeploymentEngine:
    return cast(DeploymentEngine, request.app.state.deployment_engine)


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def get_health(request: Request) -> HealthService:
    return cast(HealthService, request.app.state.health_service)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    engine: DeploymentEngine = Depends(get_engine),
    health_service: HealthService = Depends(get_health),
) -> HTMLResponse:
    states = engine.get_environment_states()
    diff = engine.diff_environments()
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
    engine: DeploymentEngine = Depends(get_engine),
    health_service: HealthService = Depends(get_health),
) -> HTMLResponse:
    context = {
        "request": request,
        "states": engine.get_environment_states(),
        "health": health_service.health_snapshot(),
    }
    return templates.TemplateResponse("partials/environments.html", context)


@router.get("/diff", response_class=HTMLResponse)
async def diff(
    request: Request,
    engine: DeploymentEngine = Depends(get_engine),
) -> HTMLResponse:
    context = {"request": request, "diff": engine.diff_environments()}
    return templates.TemplateResponse("partials/diff.html", context)


@router.post("/deploy/prod", response_class=HTMLResponse)
async def trigger_deploy_prod(
    request: Request,
    engine: DeploymentEngine = Depends(get_engine),
    database: Database = Depends(get_database),
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
    preprod_state = database.get_environment_state("preprod")
    if not preprod_state:
        raise HTTPException(status_code=409, detail="Preprod environment not initialised")
    if services is not None and len(services) == 0:
        context: dict[str, Any] = {
            "request": request,
            "status": None,
            "error": "Select at least one service to deploy.",
        }
        return templates.TemplateResponse("partials/deploy-status.html", context)
    result = await engine.deploy_prod(
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
    engine: DeploymentEngine = Depends(get_engine),
) -> HTMLResponse:
    status_obj = engine.get_deployment_status(deployment_id)
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
    database: Database = Depends(get_database),
) -> HTMLResponse:
    history, total = database.list_history(
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
    engine: DeploymentEngine = Depends(get_engine),
) -> HTMLResponse:
    services = await engine.list_services()
    context = {"request": request, "services": services}
    return templates.TemplateResponse("partials/directory.html", context)
