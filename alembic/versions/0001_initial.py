"""Initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2025-01-01 00:00:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("service_name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("commit_sha", sa.Text(), nullable=False),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deployed_by", sa.Text(), nullable=False),
        sa.UniqueConstraint("environment", "service_name", name="uq_deployments_env_service"),
    )
    op.create_index("idx_deployments_env", "deployments", ["environment"])
    op.create_index("idx_deployments_service", "deployments", ["service_name"])

    op.create_table(
        "deployment_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("service_name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("commit_sha", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("deployed_by", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
    )
    op.create_index("idx_history_env", "deployment_history", ["environment"])
    op.create_index("idx_history_service", "deployment_history", ["service_name"])
    op.create_index("idx_history_status", "deployment_history", ["status"])
    op.create_index("idx_history_started", "deployment_history", ["started_at"], unique=False)

    op.create_table(
        "service_health",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("service_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("replicas_running", sa.Integer(), nullable=True),
        sa.Column("replicas_desired", sa.Integer(), nullable=True),
        sa.Column("last_checked", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.UniqueConstraint("environment", "service_name", name="uq_service_health_env_service"),
    )
    op.create_index("idx_health_env", "service_health", ["environment"])
    op.create_index("idx_health_status", "service_health", ["status"])


def downgrade() -> None:
    op.drop_index("idx_health_status", table_name="service_health")
    op.drop_index("idx_health_env", table_name="service_health")
    op.drop_table("service_health")

    op.drop_index("idx_history_started", table_name="deployment_history")
    op.drop_index("idx_history_status", table_name="deployment_history")
    op.drop_index("idx_history_service", table_name="deployment_history")
    op.drop_index("idx_history_env", table_name="deployment_history")
    op.drop_table("deployment_history")

    op.drop_index("idx_deployments_service", table_name="deployments")
    op.drop_index("idx_deployments_env", table_name="deployments")
    op.drop_table("deployments")
