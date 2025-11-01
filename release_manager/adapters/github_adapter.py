"""GitHub adapter implementing manifest fetching port."""

from __future__ import annotations

from dataclasses import dataclass

from release_manager.application.ports import ManifestFetcher
from release_manager.github import GitHubClient, GitHubEnvFile


@dataclass(slots=True)
class GitHubManifestFetcher(ManifestFetcher):
    client: GitHubClient

    async def fetch(self, path: str) -> GitHubEnvFile:
        return await self.client.fetch_env_file(path)
