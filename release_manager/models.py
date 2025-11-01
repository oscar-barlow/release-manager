"""Pydantic models representing Release Manager domain objects."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

ChangeType = Literal["version_bump", "no_change", "new_service", "removed_service"]
DeploymentStatusType = Literal["pending", "in_progress", "success", "failed", "rolled_back"]
HealthStatusType = Literal["healthy", "unhealthy", "unknown"]


class Deployment(BaseModel):
    """Current deployment state for a service in an environment."""

    id: int
    environment: Literal["prod", "preprod"]
    service_name: str
    version: str
    commit_sha: str
    deployed_at: datetime
    deployed_by: Literal["system", "manual"]


class DeploymentHistory(BaseModel):
    """Historical record of a deployment run for a single service."""

    id: int
    environment: Literal["prod", "preprod"]
    service_name: str
    version: str
    commit_sha: str
    status: DeploymentStatusType
    deployed_by: Literal["system", "manual"]
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None


class ServiceHealth(BaseModel):
    """Health status of a service in a particular environment."""

    id: Optional[int] = None
    environment: Literal["prod", "preprod"]
    service_name: str
    status: HealthStatusType
    replicas_running: Optional[int] = None
    replicas_desired: Optional[int] = None
    last_checked: datetime
    error_message: Optional[str] = None


class EnvironmentState(BaseModel):
    """Complete state of an environment."""

    commit_sha: str
    deployed_at: datetime
    services: dict[str, str]


class ServiceDiff(BaseModel):
    """Difference between environments for a single service."""

    service: str
    prod_version: Optional[str] = None
    preprod_version: Optional[str] = None
    change_type: ChangeType


class DeploymentRequest(BaseModel):
    """Request to trigger a deployment."""

    confirm: bool = Field(..., description="Must be true to proceed")
    services: Optional[list[str]] = Field(
        None, description="Specific services to deploy (None = all preprod services)"
    )


class DeploymentStatus(BaseModel):
    """Current status of an ongoing deployment."""

    deployment_id: int = Field(..., description="Identifier for the deployment run")
    environment: Literal["prod", "preprod"]
    status: DeploymentStatusType
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    services_deployed: list[dict[str, str]]
    error_message: Optional[str] = None


class DeploymentDiff(BaseModel):
    """Represents a diff result between environments."""

    changes: list[ServiceDiff]
    commit_range: Optional[dict[str, str]] = None
