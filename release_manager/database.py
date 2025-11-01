"""SQLite database helpers for the Release Manager service."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from .migrations import upgrade_database
from .models import (
    ChangeType,
    Deployment,
    DeploymentHistory,
    DeploymentStatusType,
    EnvironmentState,
    ServiceDiff,
    ServiceHealth,
)

ISOFORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: datetime) -> str:
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _from_iso(value: str | None) -> Optional[datetime]:
    if value is None:
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Database:
    """Lightweight wrapper around sqlite3 providing convenience helpers."""

    def __init__(self, path: Path):
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def initialize_schema(self, schema_path: Optional[Path] = None) -> None:
        """Ensure database schema is created using Alembic migrations."""
        with self._lock:
            # Commit any pending work before running Alembic migrations.
            self._conn.commit()
        upgrade_database(self.path)

    def _execute(self, query: str, params: Sequence | None = None) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(query, params or [])
            self._conn.commit()
        return cursor

    def _query(self, query: str, params: Sequence | None = None) -> list[sqlite3.Row]:
        with self._lock:
            cursor = self._conn.execute(query, params or [])
            rows = cursor.fetchall()
        return rows

    def upsert_deployment(
        self,
        *,
        environment: str,
        service_name: str,
        version: str,
        commit_sha: str,
        deployed_at: datetime | None = None,
        deployed_by: str,
    ) -> int:
        """Insert or update a deployment record."""
        deployed_at = deployed_at or _utcnow()
        params = (
            environment,
            service_name,
            version,
            commit_sha,
            _to_iso(deployed_at),
            deployed_by,
        )
        query = """
            INSERT INTO deployments (environment, service_name, version, commit_sha, deployed_at, deployed_by)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(environment, service_name)
            DO UPDATE SET
                version=excluded.version,
                commit_sha=excluded.commit_sha,
                deployed_at=excluded.deployed_at,
                deployed_by=excluded.deployed_by
        """
        cursor = self._execute(query, params)
        last_row_id = cursor.lastrowid
        return int(last_row_id) if last_row_id is not None else -1

    def list_deployments(self, environment: Optional[str] = None) -> list[Deployment]:
        """Return deployments (optionally filtered by environment)."""
        query = "SELECT * FROM deployments"
        params: list[str] = []
        if environment:
            query += " WHERE environment = ?"
            params.append(environment)
        rows = self._query(query, params)
        return [
            Deployment(
                id=row["id"],
                environment=row["environment"],
                service_name=row["service_name"],
                version=row["version"],
                commit_sha=row["commit_sha"],
                deployed_at=_from_iso(row["deployed_at"]) or _utcnow(),
                deployed_by=row["deployed_by"],
            )
            for row in rows
        ]

    def get_environment_state(self, environment: str) -> Optional[EnvironmentState]:
        """Return the latest environment state assembled from deployments."""
        deployments = self.list_deployments(environment)
        if not deployments:
            return None
        services = {d.service_name: d.version for d in deployments}
        baseline = datetime.min.replace(tzinfo=timezone.utc)
        latest = max(deployments, key=lambda d: d.deployed_at or baseline)
        return EnvironmentState(
            commit_sha=latest.commit_sha,
            deployed_at=latest.deployed_at or _utcnow(),
            services=services,
        )

    def get_all_environment_states(self) -> dict[str, EnvironmentState]:
        """Return state for all environments present in the database."""
        states: dict[str, EnvironmentState] = {}
        for env in ["prod", "preprod"]:
            state = self.get_environment_state(env)
            if state:
                states[env] = state
        return states

    def create_history_record(
        self,
        *,
        environment: str,
        service_name: str,
        version: str,
        commit_sha: str,
        deployed_by: str,
        status: DeploymentStatusType = "in_progress",
        started_at: datetime | None = None,
    ) -> int:
        """Insert a deployment_history record."""
        started_at = started_at or _utcnow()
        params = (
            environment,
            service_name,
            version,
            commit_sha,
            status,
            deployed_by,
            None,
            _to_iso(started_at),
        )
        query = """
            INSERT INTO deployment_history (
                environment, service_name, version, commit_sha, status,
                deployed_by, error_message, started_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor = self._execute(query, params)
        last_row_id = cursor.lastrowid
        return int(last_row_id) if last_row_id is not None else -1

    def finalize_history_record(
        self,
        history_id: int,
        *,
        status: DeploymentStatusType,
        completed_at: datetime | None = None,
        duration_seconds: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update a deployment_history record with completion details."""
        completed_at = completed_at or _utcnow()
        params = (
            status,
            error_message,
            duration_seconds,
            _to_iso(completed_at),
            history_id,
        )
        query = """
            UPDATE deployment_history
            SET status = ?, error_message = ?, duration_seconds = ?, completed_at = ?
            WHERE id = ?
        """
        self._execute(query, params)

    def fetch_history_record(self, history_id: int) -> Optional[DeploymentHistory]:
        rows = self._query("SELECT * FROM deployment_history WHERE id = ?", (history_id,))
        if not rows:
            return None
        row = rows[0]
        return DeploymentHistory(
            id=row["id"],
            environment=row["environment"],
            service_name=row["service_name"],
            version=row["version"],
            commit_sha=row["commit_sha"],
            status=row["status"],
            deployed_by=row["deployed_by"],
            error_message=row["error_message"],
            started_at=_from_iso(row["started_at"]) or _utcnow(),
            completed_at=_from_iso(row["completed_at"]),
            duration_seconds=row["duration_seconds"],
        )

    def list_history(
        self,
        *,
        environment: Optional[str] = None,
        service: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[DeploymentHistory], int]:
        """Return deployment history entries with pagination."""
        clauses = []
        params: list[str | int] = []
        if environment and environment != "all":
            clauses.append("environment = ?")
            params.append(environment)
        if service and service not in ("all", ""):
            clauses.append("service_name = ?")
            params.append(service)

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total_query = f"SELECT COUNT(*) FROM deployment_history {where_clause}"
        total_rows = self._query(total_query, params)
        total = total_rows[0][0] if total_rows else 0

        query = f"""
            SELECT * FROM deployment_history
            {where_clause}
            ORDER BY started_at DESC
            LIMIT ? OFFSET ?
        """
        rows = self._query(query, (*params, limit, offset))
        history = [
            DeploymentHistory(
                id=row["id"],
                environment=row["environment"],
                service_name=row["service_name"],
                version=row["version"],
                commit_sha=row["commit_sha"],
                status=row["status"],
                deployed_by=row["deployed_by"],
                error_message=row["error_message"],
                started_at=_from_iso(row["started_at"]) or _utcnow(),
                completed_at=_from_iso(row["completed_at"]),
                duration_seconds=row["duration_seconds"],
            )
            for row in rows
        ]
        return history, total

    def list_history_for_started_at(
        self, *, environment: str, started_at: datetime
    ) -> list[DeploymentHistory]:
        """Fetch all history rows that share the same started_at timestamp."""
        rows = self._query(
            """
            SELECT * FROM deployment_history
            WHERE environment = ? AND started_at = ?
            ORDER BY service_name
            """,
            (environment, _to_iso(started_at)),
        )
        return [
            DeploymentHistory(
                id=row["id"],
                environment=row["environment"],
                service_name=row["service_name"],
                version=row["version"],
                commit_sha=row["commit_sha"],
                status=row["status"],
                deployed_by=row["deployed_by"],
                error_message=row["error_message"],
                started_at=_from_iso(row["started_at"]) or _utcnow(),
                completed_at=_from_iso(row["completed_at"]),
                duration_seconds=row["duration_seconds"],
            )
            for row in rows
        ]

    def update_service_health(self, health: ServiceHealth) -> int:
        """Insert or update a service health record."""
        params = (
            health.environment,
            health.service_name,
            health.status,
            health.replicas_running,
            health.replicas_desired,
            _to_iso(health.last_checked),
            health.error_message,
        )
        query = """
            INSERT INTO service_health (
                environment, service_name, status, replicas_running,
                replicas_desired, last_checked, error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(environment, service_name)
            DO UPDATE SET
                status=excluded.status,
                replicas_running=excluded.replicas_running,
                replicas_desired=excluded.replicas_desired,
                last_checked=excluded.last_checked,
                error_message=excluded.error_message
        """
        cursor = self._execute(query, params)
        last_row_id = cursor.lastrowid
        return int(last_row_id) if last_row_id is not None else -1

    def list_service_health(self, environment: Optional[str] = None) -> list[ServiceHealth]:
        """Return service health entries."""
        query = "SELECT * FROM service_health"
        params: list[str] = []
        if environment:
            query += " WHERE environment = ?"
            params.append(environment)
        rows = self._query(query, params)
        return [
            ServiceHealth(
                id=row["id"],
                environment=row["environment"],
                service_name=row["service_name"],
                status=row["status"],
                replicas_running=row["replicas_running"],
                replicas_desired=row["replicas_desired"],
                last_checked=_from_iso(row["last_checked"]) or _utcnow(),
                error_message=row["error_message"],
            )
            for row in rows
        ]

    def compute_diff(self) -> list[ServiceDiff]:
        """Return service differences between preprod and prod."""
        preprod = self.get_environment_state("preprod")
        prod = self.get_environment_state("prod")
        differences: list[ServiceDiff] = []
        if not preprod and not prod:
            return differences
        services: set[str] = set()
        if preprod:
            services.update(preprod.services.keys())
        if prod:
            services.update(prod.services.keys())
        for service in sorted(services):
            prod_version = prod.services.get(service) if prod else None
            preprod_version = preprod.services.get(service) if preprod else None
            if prod_version and preprod_version:
                if prod_version == preprod_version:
                    change_type: ChangeType = "no_change"
                else:
                    change_type = "version_bump"
            elif preprod_version and not prod_version:
                change_type = "new_service"
            else:
                change_type = "removed_service"
            differences.append(
                ServiceDiff(
                    service=service,
                    prod_version=prod_version,
                    preprod_version=preprod_version,
                    change_type=change_type,
                )
            )
        return differences
