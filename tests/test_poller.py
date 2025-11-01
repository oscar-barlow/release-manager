from datetime import datetime, timezone

import pytest

from release_manager.application.ports import ManifestFetcher
from release_manager.config import Settings
from release_manager.github import GitHubEnvFile
from release_manager.models import EnvironmentState
from release_manager.poller import EnvironmentPoller


class FakeManifestFetcher(ManifestFetcher):
    def __init__(self, env_file: GitHubEnvFile):
        self.env_file = env_file

    async def fetch(self, path: str) -> GitHubEnvFile:
        return self.env_file


class FakeEnvironmentService:
    def __init__(self, initial_commit: str | None = None):
        self._commit = initial_commit

    def set_commit(self, commit: str) -> None:
        self._commit = commit

    def get_environment(self, environment: str):
        if environment != "preprod" or self._commit is None:
            return None
        return EnvironmentState(
            commit_sha=self._commit,
            deployed_at=datetime.now(timezone.utc),
            services={},
        )

    def get_all_environments(self):
        state = self.get_environment("preprod")
        return {"preprod": state} if state else {}

    def diff_environments(self):
        return []


class FakeDeploymentService:
    def __init__(self, environment_service: FakeEnvironmentService):
        self.calls: list[tuple[str, dict[str, str]]] = []
        self._environment_service = environment_service

    async def deploy_preprod(
        self, *, commit_sha: str, services: dict[str, str], deployed_by: str = "system"
    ):  # pragma: no cover - simple fake
        self.calls.append((commit_sha, services))
        self._environment_service.set_commit(commit_sha)


@pytest.mark.asyncio
async def test_poller_triggers_and_tracks_latest_commit(tmp_path):
    settings = Settings(
        environment_name="test",
        stub_mode=False,
        github_repo="user/repo",
        github_token_file=None,
        github_token=None,
        poll_interval_seconds=0,
        docker_host=None,
        database_path=tmp_path / "poller.db",
        deployment_timeout_seconds=300,
        health_check_interval_seconds=5,
        web_host="0.0.0.0",
        web_port=8080,
    )

    initial_env = GitHubEnvFile(
        commit_sha="sha-1",
        raw_text="SERVICE_VERSION=1",
        services={"service": "1"},
    )
    environment_service = FakeEnvironmentService()
    deployment_service = FakeDeploymentService(environment_service)
    fetcher = FakeManifestFetcher(initial_env)

    poller = EnvironmentPoller(
        settings=settings,
        manifest_fetcher=fetcher,
        deployment_service=deployment_service,
        environment_service=environment_service,
    )

    # First change should deploy and store latest commit.
    await poller.check_for_changes()
    assert deployment_service.calls == [("sha-1", {"service": "1"})]

    # Same commit should no-op.
    await poller.check_for_changes()
    assert deployment_service.calls == [("sha-1", {"service": "1"})]

    # New commit triggers another deployment.
    fetcher.env_file = GitHubEnvFile(
        commit_sha="sha-2",
        raw_text="SERVICE_VERSION=2",
        services={"service": "2"},
    )
    await poller.check_for_changes()
    assert deployment_service.calls[-1] == ("sha-2", {"service": "2"})
