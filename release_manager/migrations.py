"""Utilities for running Alembic migrations programmatically."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config

from .config import Settings, get_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _make_config(database_path: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return cfg


def upgrade_database(database_path: Path, revision: str = "head") -> None:
    cfg = _make_config(database_path)
    command.upgrade(cfg, revision)


def downgrade_database(database_path: Path, revision: str) -> None:
    cfg = _make_config(database_path)
    command.downgrade(cfg, revision)


def stamp_database(database_path: Path, revision: str) -> None:
    cfg = _make_config(database_path)
    command.stamp(cfg, revision)


def _resolve_database_path(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    settings: Settings = get_settings()
    return settings.database_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage database schema migrations")
    parser.add_argument(
        "command",
        choices=["upgrade", "downgrade", "stamp"],
        help="Alembic command to execute",
    )
    parser.add_argument("--revision", default="head", help="Target revision (default: head)")
    parser.add_argument(
        "--database",
        dest="database",
        default=None,
        help="Optional database path (defaults to resolved settings path)",
    )
    args = parser.parse_args()

    database_path = _resolve_database_path(args.database)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    if args.command == "upgrade":
        upgrade_database(database_path, args.revision)
    elif args.command == "downgrade":
        downgrade_database(database_path, args.revision)
    elif args.command == "stamp":
        stamp_database(database_path, args.revision)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
