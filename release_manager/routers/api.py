"""JSON API endpoints."""

from __future__ import annotations

from typing import Any, Optional, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..application.services.deployment_service import DeploymentService
from ..application.services.environment_service import EnvironmentService
from ..health import HealthService
from ..models import DeploymentRequest, DeploymentStatus

router = APIRouter(prefix="/api", tags=["api"])


def get_deployment_service(request: Request) -> DeploymentService:
    return cast(DeploymentService, request.app.state.deployment_service)


def get_environment_service(request: Request) -> EnvironmentService:
    return cast(EnvironmentService, request.app.state.environment_service)


def get_health_service(request: Request) -> HealthService:
    return cast(HealthService, request.app.state.health_service)


@router.get("/environments")
def list_environments(
    environment_service: EnvironmentService = Depends(get_environment_service),
) -> dict[str, Any]:
    states = environment_service.get_all_environments()
    return {env: state.model_dump() for env, state in states.items()}


@router.get("/diff")
def get_diff(
    environment_service: EnvironmentService = Depends(get_environment_service),
) -> dict[str, Any]:
    diff = environment_service.diff_environments()
    states = environment_service.get_all_environments()
    prod_state = states.get("prod")
    preprod_state = states.get("preprod")
    prod_commit = prod_state.commit_sha if prod_state else None
    preprod_commit = preprod_state.commit_sha if preprod_state else None
    return {
        "changes": [item.model_dump() for item in diff],
        "commit_range": {"from": prod_commit, "to": preprod_commit},
    }


@router.post(
    "/deploy/prod",
    response_model=DeploymentStatus,
    status_code=status.HTTP_202_ACCEPTED,
)
async def deploy_prod(
    request_body: DeploymentRequest,
    deployment_service: DeploymentService = Depends(get_deployment_service),
    environment_service: EnvironmentService = Depends(get_environment_service),
) -> DeploymentStatus:
    if not request_body.confirm:
        raise HTTPException(status_code=400, detail="Deployment requires confirmation")
    preprod_state = environment_service.get_environment("preprod")
    if not preprod_state:
        raise HTTPException(
            status_code=409, detail="Preprod environment has not been deployed yet"
        )
    if deployment_service.is_deployment_in_progress():
        raise HTTPException(status_code=409, detail="Deployment already in progress")
    subset = request_body.services
    try:
        result = await deployment_service.deploy_prod(
            services=preprod_state.services,
            commit_sha=preprod_state.commit_sha,
            subset=subset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/deploy/prod/{deployment_id}", response_model=DeploymentStatus)
def get_deploy_status(
    deployment_id: int,
    deployment_service: DeploymentService = Depends(get_deployment_service),
) -> DeploymentStatus:
    status_obj = deployment_service.get_deployment_status(deployment_id)
    if not status_obj:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return status_obj


@router.get("/history")
def list_history(
    environment: Optional[str] = Query(default=None),
    service: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    deployment_service: DeploymentService = Depends(get_deployment_service),
) -> dict[str, Any]:
    history, total = deployment_service.list_history(
        environment=environment, service=service, limit=limit, offset=offset
    )
    return {
        "deployments": [item.model_dump() for item in history],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/rollback/prod", response_model=DeploymentStatus)
async def rollback_prod(
    payload: dict[str, Any],
    deployment_service: DeploymentService = Depends(get_deployment_service),
) -> DeploymentStatus:
    history_id = payload.get("deployment_history_id")
    confirm = payload.get("confirm")
    if not confirm:
        raise HTTPException(status_code=400, detail="Rollback requires confirmation")
    if history_id is None:
        raise HTTPException(status_code=400, detail="deployment_history_id is required")
    record = deployment_service.get_history_record(int(history_id))
    if not record or record.environment != "prod":
        raise HTTPException(status_code=404, detail="Production deployment record not found")
    related = deployment_service.list_related_history(
        environment=record.environment, started_at=record.started_at
    )
    services = {entry.service_name: entry.version for entry in related}
    result = await deployment_service.deploy_prod(
        services=services,
        commit_sha=record.commit_sha,
        deployed_by="manual",
        subset=services.keys(),
    )
    return result


@router.get("/health")
async def health_snapshot(
    health_service: HealthService = Depends(get_health_service),
) -> dict[str, Any]:
    snapshot = health_service.health_snapshot()
    response: dict[str, Any] = {}
    for env, services in snapshot.items():
        response[env] = {
            service: entry.model_dump()
            for service, entry in services.items()
        }
    return response
