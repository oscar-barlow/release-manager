import asyncio

import pytest

from release_manager.config import Settings
from release_manager.database import Database
from release_manager.github import GitHubEnvFile
from release_manager.poller import EnvironmentPoller


class FakeGitHubClient:
    def __init__(self, env_file: GitHubEnvFile):
        self._env_file = env_file
        self.calls = 0

    @property
    def env_file(self) -> GitHubEnvFile:
        return self._env_file

    @env_file.setter
    def env_file(self, value: GitHubEnvFile) -> None:
        self._env_file = value

    async def fetch_env_file(self, path: str) -> GitHubEnvFile:
        self.calls += 1
        return self._env_file


class FakeDeploymentEngine:
    def __init__(self):
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def deploy_preprod(self, commit_sha: str, services: dict[str, str], *, deployed_by: str = "system") -> None:
        self.calls.append((commit_sha, services))


@pytest.mark.asyncio
async def test_poller_triggers_and_tracks_latest_commit(tmp_path):
    db_path = tmp_path / "poller.db"
    database = Database(db_path)
    database.initialize_schema()

    settings = Settings(
        environment_name="test",
        stub_mode=False,
        github_repo="user/repo",
        github_token_file=None,
        github_token=None,
        poll_interval_seconds=0,
        docker_host=None,
        database_path=db_path,
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
    github = FakeGitHubClient(initial_env)
    engine = FakeDeploymentEngine()

    poller = EnvironmentPoller(
        settings=settings,
        database=database,
        github_client=github,
        deployment_engine=engine,
    )

    # First change should deploy and store latest commit.
    await poller.check_for_changes()
    assert engine.calls == [("sha-1", {"service": "1"})]

    # Same commit should no-op.
    await poller.check_for_changes()
    assert engine.calls == [("sha-1", {"service": "1"})]

    # New commit triggers another deployment.
    github.env_file = GitHubEnvFile(
        commit_sha="sha-2",
        raw_text="SERVICE_VERSION=2",
        services={"service": "2"},
    )
    await poller.check_for_changes()
    assert engine.calls[-1] == ("sha-2", {"service": "2"})
