"""Clock adapter for application services."""

from __future__ import annotations

from datetime import datetime, timezone

from release_manager.application.ports import Clock


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(timezone.utc)
