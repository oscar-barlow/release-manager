"""Configuration management for the Release Manager service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    """Application configuration loaded from environment variables."""

    environment_name: str
    stub_mode: bool
    github_repo: str
    github_token: Optional[str]
    poll_interval_seconds: int
    docker_host: Optional[str]
    database_path: Path
    deployment_timeout_seconds: int
    health_check_interval_seconds: int
    web_host: str
    web_port: int

    @property
    def preprod_env_path(self) -> str:
        """Path to the preprod environment file within the repository."""
        return "env/.env.preprod"

    @property
    def prod_env_path(self) -> str:
        """Path to the production environment file within the repository."""
        return "env/.env.prod"

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "Settings":
        """Create settings from environment variables (optionally loading a .env file)."""
        if env_file:
            load_dotenv(env_file, override=True)
        else:
            load_dotenv(override=False)

        environment_name = _determine_environment_name(os.environ.get("ENVIRONMENT_NAME", "preprod"))
        stub_mode = _to_bool(os.environ.get("STUB_MODE", "false"))
        github_repo = os.environ.get("GITHUB_REPO", "oscar-barlow/home.services")
        if not github_repo:
            raise ValueError("GITHUB_REPO environment variable must be set")

        database_path = _resolve_database_path(
            os.environ.get("DATABASE_PATH", "./data/release-manager.db"),
            environment_name,
        )
        database_path.parent.mkdir(parents=True, exist_ok=True)

        return cls(
            environment_name=environment_name,
            stub_mode=stub_mode,
            github_repo=github_repo,
            github_token=os.environ.get("GITHUB_TOKEN"),
            poll_interval_seconds=int(os.environ.get("POLL_INTERVAL_SECONDS", "60")),
            docker_host=os.environ.get("DOCKER_HOST"),
            database_path=database_path,
            deployment_timeout_seconds=int(os.environ.get("DEPLOYMENT_TIMEOUT_SECONDS", "300")),
            health_check_interval_seconds=int(
                os.environ.get("HEALTH_CHECK_INTERVAL_SECONDS", "5")
            ),
            web_host=os.environ.get("WEB_HOST", "0.0.0.0"),
            web_port=int(os.environ.get("WEB_PORT", "8080")),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings.from_env()


def _to_bool(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _determine_environment_name(raw: str) -> str:
    name = raw.strip() or "preprod"
    safe = name.replace(" ", "-").lower()
    return safe


def _resolve_database_path(raw: str, environment_name: str) -> Path:
    input_path = Path(raw).expanduser()

    # Treat trailing slash or lack of suffix as a directory hint.
    is_directory_hint = raw.endswith("/") or input_path.suffix == ""

    if is_directory_hint:
        directory = input_path.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"release-manager-{environment_name}.db"
        return (directory / filename).resolve()

    resolved = input_path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if environment_name in resolved.stem.split("-"):
        return resolved
    filename = f"{resolved.stem}-{environment_name}{resolved.suffix}"
    return resolved.with_name(filename)
