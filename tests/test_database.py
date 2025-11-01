from release_manager.database import Database


def make_db(tmp_path):
    db_path = tmp_path / "release-manager.db"
    database = Database(db_path)
    database.initialize_schema()
    return database


def test_upsert_and_fetch_environment(tmp_path):
    db = make_db(tmp_path)
    db.upsert_deployment(
        environment="preprod",
        service_name="jellyfin",
        version="2025040803",
        commit_sha="abc123",
        deployed_by="system",
    )
    state = db.get_environment_state("preprod")
    assert state is not None
    assert state.services["jellyfin"] == "2025040803"


def test_compute_diff(tmp_path):
    db = make_db(tmp_path)
    db.upsert_deployment(
        environment="preprod",
        service_name="jellyfin",
        version="2025040900",
        commit_sha="def456",
        deployed_by="system",
    )
    db.upsert_deployment(
        environment="prod",
        service_name="jellyfin",
        version="2025040803",
        commit_sha="abc123",
        deployed_by="manual",
    )
    diff = db.compute_diff()
    assert diff
    entry = diff[0]
    assert entry.service == "jellyfin"
    assert entry.change_type == "version_bump"
