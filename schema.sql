CREATE TABLE IF NOT EXISTS deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    environment TEXT NOT NULL,
    service_name TEXT NOT NULL,
    version TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    deployed_at TIMESTAMP NOT NULL,
    deployed_by TEXT NOT NULL,
    UNIQUE(environment, service_name)
);

CREATE INDEX IF NOT EXISTS idx_deployments_env ON deployments(environment);
CREATE INDEX IF NOT EXISTS idx_deployments_service ON deployments(service_name);

CREATE TABLE IF NOT EXISTS deployment_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    environment TEXT NOT NULL,
    service_name TEXT NOT NULL,
    version TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    status TEXT NOT NULL,
    deployed_by TEXT NOT NULL,
    error_message TEXT,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    duration_seconds REAL
);

CREATE INDEX IF NOT EXISTS idx_history_env ON deployment_history(environment);
CREATE INDEX IF NOT EXISTS idx_history_service ON deployment_history(service_name);
CREATE INDEX IF NOT EXISTS idx_history_status ON deployment_history(status);
CREATE INDEX IF NOT EXISTS idx_history_started ON deployment_history(started_at DESC);

CREATE TABLE IF NOT EXISTS service_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    environment TEXT NOT NULL,
    service_name TEXT NOT NULL,
    status TEXT NOT NULL,
    replicas_running INTEGER,
    replicas_desired INTEGER,
    last_checked TIMESTAMP NOT NULL,
    error_message TEXT,
    UNIQUE(environment, service_name)
);

CREATE INDEX IF NOT EXISTS idx_health_env ON service_health(environment);
CREATE INDEX IF NOT EXISTS idx_health_status ON service_health(status);
