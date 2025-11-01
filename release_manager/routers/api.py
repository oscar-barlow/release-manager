"""JSON API endpoints."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..database import Database
from ..deployer import DeploymentEngine
from ..health import HealthService
from ..models import DeploymentRequest, DeploymentStatus

router = APIRouter(prefix="/api", tags=["api"])


def get_engine(request: Request) -> DeploymentEngine:
    return request.app.state.deployment_engine


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_health_service(request: Request) -> HealthService:
    return request.app.state.health_service


@router.get("/environments")
def list_environments(
    engine: DeploymentEngine = Depends(get_engine),
) -> dict[str, Any]:
    states = engine.get_environment_states()
    return {env: state.model_dump() for env, state in states.items()}


@router.get("/diff")
def get_diff(
    engine: DeploymentEngine = Depends(get_engine),
) -> dict[str, Any]:
    diff = engine.diff_environments()
    states = engine.get_environment_states()
    prod_commit = states.get("prod").commit_sha if "prod" in states else None
    preprod_commit = states.get("preprod").commit_sha if "preprod" in states else None
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
    engine: DeploymentEngine = Depends(get_engine),
    database: Database = Depends(get_database),
) -> DeploymentStatus:
    if not request_body.confirm:
        raise HTTPException(status_code=400, detail="Deployment requires confirmation")
    preprod_state = database.get_environment_state("preprod")
    if not preprod_state:
        raise HTTPException(
            status_code=409, detail="Preprod environment has not been deployed yet"
        )
    if engine.is_deployment_in_progress():
        raise HTTPException(status_code=409, detail="Deployment already in progress")
    subset = request_body.services
    try:
        result = await engine.deploy_prod(
            services=preprod_state.services,
            commit_sha=preprod_state.commit_sha,
            subset=subset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/deploy/prod/{deployment_id}", response_model=DeploymentStatus)
def get_deploy_status(
    deployment_id: int, engine: DeploymentEngine = Depends(get_engine)
) -> DeploymentStatus:
    status_obj = engine.get_deployment_status(deployment_id)
    if not status_obj:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return status_obj


@router.get("/history")
def list_history(
    environment: Optional[str] = Query(default=None),
    service: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    history, total = database.list_history(
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
    engine: DeploymentEngine = Depends(get_engine),
    database: Database = Depends(get_database),
) -> DeploymentStatus:
    history_id = payload.get("deployment_history_id")
    confirm = payload.get("confirm")
    if not confirm:
        raise HTTPException(status_code=400, detail="Rollback requires confirmation")
    if history_id is None:
        raise HTTPException(status_code=400, detail="deployment_history_id is required")
    record = database.fetch_history_record(int(history_id))
    if not record or record.environment != "prod":
        raise HTTPException(status_code=404, detail="Production deployment record not found")
    related = database.list_history_for_started_at(
        environment=record.environment, started_at=record.started_at
    )
    services = {entry.service_name: entry.version for entry in related}
    result = await engine.deploy_prod(
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
