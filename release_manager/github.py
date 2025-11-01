"""GitHub client responsible for fetching environment configuration."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GitHubEnvFile:
    """Representation of an environment file fetched from GitHub."""

    commit_sha: str
    raw_text: str
    services: dict[str, str]


def parse_service_versions(raw_text: str) -> dict[str, str]:
    """Parse service version mappings from .env style content."""
    services: dict[str, str] = {}
    for line in raw_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not value:
            continue
        normalized_key = key.lower()
        if normalized_key.endswith("_version"):
            service = normalized_key[: -len("_version")]
        elif normalized_key.endswith("_tag"):
            service = normalized_key[: -len("_tag")]
        else:
            # Ignore non-version variables to avoid polluting the diff.
            continue
        service = service.replace("_", "-")
        services[service] = value
    return services


class GitHubClient:
    """Tiny wrapper around the GitHub REST API."""

    def __init__(
        self,
        *,
        repo: str,
        token: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.repo = repo
        self.token = token
        self._client = client or httpx.AsyncClient(base_url="https://api.github.com")

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_env_file(self, path: str) -> GitHubEnvFile:
        """Fetch an environment file from GitHub and parse service versions."""
        url = f"/repos/{self.repo}/contents/{path}"
        headers = {"Accept": "application/vnd.github.raw+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        logger.debug("Fetching environment file from GitHub: %s", url)
        response = await self._client.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        content = payload.get("content", "")
        encoding = payload.get("encoding", "utf-8")
        if encoding == "base64":
            raw_bytes = base64.b64decode(content)
            raw_text = raw_bytes.decode("utf-8")
        else:
            raw_text = content
        commit_sha = payload.get("sha") or payload.get("commit_sha") or ""
        services = parse_service_versions(raw_text)
        return GitHubEnvFile(commit_sha=commit_sha, raw_text=raw_text, services=services)
