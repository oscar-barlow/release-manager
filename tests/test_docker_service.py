import pytest

from release_manager.docker_client import StubbedDockerService


def test_stubbed_directory_for_dev_environment():
    stub = StubbedDockerService(environment_name="dev")

    snapshot = stub.list_services_by_environment()

    assert "dev" in snapshot
    services = snapshot["dev"]
    assert services
    first = services[0]
    assert first.environment == "dev"
    assert first.stack_service.startswith("homelab-dev")
    assert first.image


def test_stubbed_directory_hidden_for_prod_like_environment():
    stub = StubbedDockerService(environment_name="prod")

    snapshot = stub.list_services_by_environment()

    assert snapshot == {}


def test_stubbed_health_unknown_environment_reports_message():
    stub = StubbedDockerService(environment_name="dev")

    health = stub.get_service_health(environment="prod", service_name="api")

    assert health.status == "unknown"
    assert health.error_message is not None
    assert "stub" in health.error_message.lower()
