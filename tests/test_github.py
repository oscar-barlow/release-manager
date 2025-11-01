from release_manager.github import parse_service_versions


def test_parse_service_versions():
    raw = """
    # comment line
    JELLYFIN_VERSION=2025040803
    PIHOLE_VERSION=2025.04.0
    OTHER_VALUE=ignored
    """
    result = parse_service_versions(raw)
    assert result == {
        "jellyfin": "2025040803",
        "pihole": "2025.04.0",
    }
