# Release Manager Design Document

## Overview

A GitOps-inspired deployment automation service for the homelab Docker Swarm cluster. Automatically synchronises preprod environment with GitHub master branch and provides a web interface for managing production deployments.

## Architecture

### Components

1. **Poller Service** (Python async task)
   - Polls GitHub repository every 60 seconds
   - Detects changes to `env/.env.preprod`
   - Triggers preprod deployment pipeline
   - Runs as background task within main application

2. **Deployment Engine** (Python with Docker SDK)
   - Parses environment files from GitHub
   - Compares with current deployment state in database
   - Executes Docker stack deployments via SDK
   - Performs health checks post-deployment
   - Records deployment history and status

3. **Web API** (FastAPI)
   - RESTful endpoints for:
     - Viewing current environment states
     - Comparing preprod vs prod versions
     - Triggering manual prod deployments
     - Querying deployment history
     - Viewing service health status
   - Auto-generated OpenAPI documentation

4. **Web UI** (HTMX + Alpine.js)
   - Dashboard showing current versions per environment
   - Side-by-side diff view (prod vs preprod)
   - Deployment trigger button with confirmation
   - Deployment history log
   - Service health status indicators
   - Real-time updates without full page reloads
   - Minimal JavaScript for interactivity

5. **SQLite Database**
   - Stores deployment state and history
   - Schema detailed below

### Technology Stack

- **Python 3.11+**
- **FastAPI** - Web framework (includes Pydantic)
- **Pydantic** - Data validation and serialization
- **Docker SDK for Python** - Container orchestration
- **SQLite** - Database (using standard library `sqlite3`)
- **httpx** - Async HTTP client for GitHub API
- **Jinja2** - Template rendering for web UI
- **HTMX** - Dynamic HTML updates without JavaScript
- **Alpine.js** - Lightweight JavaScript framework for interactivity

## Database Schema

### Table: `deployments`

Current state of each service in each environment.

```sql
CREATE TABLE deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    environment TEXT NOT NULL,           -- 'prod' or 'preprod'
    service_name TEXT NOT NULL,          -- e.g., 'jellyfin', 'pihole'
    version TEXT NOT NULL,               -- e.g., '2025040803', 'latest'
    commit_sha TEXT NOT NULL,            -- GitHub commit SHA
    deployed_at TIMESTAMP NOT NULL,      -- Deployment timestamp
    deployed_by TEXT NOT NULL,           -- 'system' or 'manual'
    
    UNIQUE(environment, service_name)    -- One current version per service per env
);

CREATE INDEX idx_deployments_env ON deployments(environment);
CREATE INDEX idx_deployments_service ON deployments(service_name);
```

### Table: `deployment_history`

Historical record of all deployments.

```sql
CREATE TABLE deployment_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    environment TEXT NOT NULL,
    service_name TEXT NOT NULL,
    version TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    status TEXT NOT NULL,                -- 'success', 'failed', 'rolled_back'
    deployed_by TEXT NOT NULL,
    error_message TEXT,                  -- Populated if status='failed'
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    duration_seconds REAL
);

CREATE INDEX idx_history_env ON deployment_history(environment);
CREATE INDEX idx_history_service ON deployment_history(service_name);
CREATE INDEX idx_history_status ON deployment_history(status);
CREATE INDEX idx_history_started ON deployment_history(started_at DESC);
```

### Table: `service_health`

Current health status of services.

```sql
CREATE TABLE service_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    environment TEXT NOT NULL,
    service_name TEXT NOT NULL,
    status TEXT NOT NULL,                -- 'healthy', 'unhealthy', 'unknown'
    replicas_running INTEGER,
    replicas_desired INTEGER,
    last_checked TIMESTAMP NOT NULL,
    error_message TEXT,
    
    UNIQUE(environment, service_name)
);

CREATE INDEX idx_health_env ON service_health(environment);
CREATE INDEX idx_health_status ON service_health(status);
```

## Pydantic Models

Pydantic models provide type safety and validation for data moving between database, business logic, and API layers.

### Core Models

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class Deployment(BaseModel):
    """Current deployment state for a service in an environment"""
    id: int
    environment: str  # 'prod' or 'preprod'
    service_name: str
    version: str
    commit_sha: str
    deployed_at: datetime
    deployed_by: str  # 'system' or 'manual'

class DeploymentHistory(BaseModel):
    """Historical record of a deployment"""
    id: int
    environment: str
    service_name: str
    version: str
    commit_sha: str
    status: str  # 'success', 'failed', 'in_progress'
    deployed_by: str
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None

class ServiceHealth(BaseModel):
    """Health status of a service"""
    id: Optional[int] = None
    environment: str
    service_name: str
    status: str  # 'healthy', 'unhealthy', 'unknown'
    replicas_running: int
    replicas_desired: int
    last_checked: datetime
    error_message: Optional[str] = None

class EnvironmentState(BaseModel):
    """Complete state of an environment"""
    commit_sha: str
    deployed_at: datetime
    services: dict[str, str]  # service_name -> version

class ServiceDiff(BaseModel):
    """Difference between environments for a single service"""
    service: str
    prod_version: str
    preprod_version: str
    change_type: str  # 'version_bump', 'no_change', 'new_service', 'removed_service'

class DeploymentRequest(BaseModel):
    """Request to trigger a deployment"""
    confirm: bool = Field(..., description="Must be true to proceed")
    services: Optional[list[str]] = Field(None, description="Specific services to deploy (None = all)")

class DeploymentStatus(BaseModel):
    """Current status of an ongoing deployment"""
    deployment_id: int
    status: str  # 'in_progress', 'success', 'failed'
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    services_deployed: list[dict[str, str]]
    error_message: Optional[str] = None
```

### Usage Pattern

```python
# database.py - returns raw dicts
def get_deployment(deployment_id: int) -> dict:
    cursor.execute(
        "SELECT * FROM deployments WHERE id = ?", 
        (deployment_id,)
    )
    row = cursor.fetchone()
    return dict(row) if row else None

# business logic - converts to Pydantic models
def fetch_deployment(deployment_id: int) -> Deployment:
    deployment_dict = db.get_deployment(deployment_id)
    if not deployment_dict:
        raise ValueError(f"Deployment {deployment_id} not found")
    return Deployment(**deployment_dict)

# API endpoints - Pydantic handles serialization
@app.get("/api/deployments/{deployment_id}", response_model=Deployment)
async def get_deployment_endpoint(deployment_id: int):
    return fetch_deployment(deployment_id)
```

This approach provides:
- Type checking in business logic
- Automatic validation of database data
- Self-documenting code via type hints
- FastAPI integration for request/response validation
- Easy serialization to JSON for API responses

## Development Setup

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) - Fast Python package installer and resolver
- Docker (for running the service)
- Access to Docker Swarm manager node

### Initial Setup

```bash
# Clone repository
git clone <repo-url>
cd release-manager

# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows
uv pip install -e ".[dev]"

# Initialize database
make db-init

# Run development server
make dev
```

### Makefile Targets

```makefile
.PHONY: dev test lint format db-init db-reset docker-build docker-run clean help

help:
	@echo "Available targets:"
	@echo "  dev          - Run development server with auto-reload"
	@echo "  test         - Run test suite"
	@echo "  lint         - Run linting (ruff)"
	@echo "  format       - Format code (ruff)"
	@echo "  db-init      - Initialize SQLite database"
	@echo "  db-reset     - Reset database (drop and recreate)"
	@echo "  docker-build - Build Docker image"
	@echo "  docker-run   - Run Docker container locally"
	@echo "  clean        - Remove build artifacts and cache"

dev:
	@echo "🚀 Starting development server..."
	uv run uvicorn release_manager.main:app --reload --host 0.0.0.0 --port 8080

test:
	@echo "🧪 Running tests..."
	uv run pytest tests/ -v

lint:
	@echo "🔍 Running linter..."
	uv run ruff check src/ tests/

format:
	@echo "✨ Formatting code..."
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

db-init:
	@echo "📦 Initializing database..."
	@if [ -f data/release-manager.db ]; then \
		echo "❌ Database already exists at data/release-manager.db"; \
		echo "   Use 'make db-reset' to recreate"; \
		exit 1; \
	fi
	@mkdir -p data
	sqlite3 data/release-manager.db < schema.sql
	@echo "✅ Database initialized at data/release-manager.db"

db-reset:
	@echo "⚠️  Resetting database..."
	@read -p "This will delete all data. Continue? (y/N) " confirm; \
	if [ "$$confirm" = "y" ]; then \
		rm -f data/release-manager.db; \
		mkdir -p data; \
		sqlite3 data/release-manager.db < schema.sql; \
		echo "✅ Database reset complete"; \
	else \
		echo "Cancelled"; \
	fi

docker-build:
	@echo "🐳 Building Docker image..."
	docker build -t release-manager:latest .

docker-run:
	@echo "🐳 Running Docker container..."
	docker run -d \
		-p 8080:8080 \
		-v /var/run/docker.sock:/var/run/docker.sock:ro \
		-v $$(pwd)/data:/data \
		-e GITHUB_REPO=user/homelab \
		-e DATABASE_PATH=/data/release-manager.db \
		--name release-manager \
		release-manager:latest

clean:
	@echo "🧹 Cleaning build artifacts..."
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf .pytest_cache/
	rm -rf .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	@echo "✅ Clean complete"
```

### pyproject.toml

```toml
[project]
name = "release-manager"
version = "0.1.0"
description = "GitOps deployment automation for homelab Docker Swarm"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
    "docker>=7.0.0",
    "httpx>=0.25.0",
    "jinja2>=3.1.0",
    "pydantic>=2.0.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "ruff>=0.1.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W"]
ignore = ["E501"]  # Line too long (handled by formatter)

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
asyncio_mode = "auto"
```

### Environment Variables (Development)

Create `.env` file for local development:

```bash
# GitHub Configuration
GITHUB_REPO=user/homelab
GITHUB_TOKEN=ghp_your_token_here

# Polling Configuration
POLL_INTERVAL_SECONDS=60

# Docker Configuration
DOCKER_HOST=unix:///var/run/docker.sock

# Database
DATABASE_PATH=./data/release-manager.db

# Deployment Configuration
DEPLOYMENT_TIMEOUT_SECONDS=300
HEALTH_CHECK_INTERVAL_SECONDS=5

# Web UI
WEB_HOST=0.0.0.0
WEB_PORT=8080
```

### Development Workflow

1. **Make changes** to source code
2. **Format code**: `make format`
3. **Run linter**: `make lint`
4. **Run tests**: `make test`
5. **Test locally**: `make dev` (auto-reloads on changes)
6. **Build Docker image**: `make docker-build`
7. **Test in Docker**: `make docker-run`

### Database Management

```bash
# View database schema
sqlite3 data/release-manager.db ".schema"

# Query deployments
sqlite3 data/release-manager.db "SELECT * FROM deployments;"

# Interactive SQL shell
sqlite3 data/release-manager.db

# Backup database
cp data/release-manager.db data/release-manager.db.backup

# Restore from backup
cp data/release-manager.db.backup data/release-manager.db
```

## Deployment Flow

### Preprod Automatic Deployment

```
1. Poller detects change in env/.env.preprod on GitHub master
   ↓
2. Fetch full .env.preprod content from GitHub
   ↓
3. Parse environment variables (service versions)
   ↓
4. Query database for current preprod deployment state
   ↓
5. Compare versions - identify changes
   ↓
6. Create deployment_history record (status='pending')
   ↓
7. Generate docker-swarm-stack.preprod.yml using envsubst
   ↓
8. Execute: docker stack deploy --compose-file docker-swarm-stack.preprod.yml homelab-preprod
   ↓
9. Wait for deployment to stabilise (configurable timeout)
   ↓
10. Run health checks on all services
    ↓
11. Update deployment_history record:
    - If healthy: status='success'
    - If unhealthy: status='failed'
    ↓
12. Update deployments table with new versions
    ↓
13. Update service_health table
```

### Prod Manual Deployment

```
1. User views diff in web UI (preprod vs prod)
   ↓
2. User clicks "Deploy to Production"
   ↓
3. API endpoint receives deployment request
   ↓
4. Copy preprod versions to prod in database
   ↓
5. Follow same deployment process as preprod (steps 6-13)
   ↓
6. Return deployment result to user
```

### Rollback Flow

```
1. User selects previous deployment from history
   ↓
2. API retrieves versions from deployment_history
   ↓
3. Update deployments table with historical versions
   ↓
4. Execute deployment (same as manual deployment)
   ↓
5. Record rollback in deployment_history
```

## Health Check Strategy

Health checks use Docker Swarm's built-in service status only:

### Docker Service Health

- Query Docker Swarm for service status via SDK
- Check: `replicas_running == replicas_desired`
- Check: Task state is 'running' not 'failed'
- Check: No recent task failures

**Implementation:**
```python
async def check_service_health(service_name: str, environment: str) -> ServiceHealth:
    service = docker_client.services.get(f"homelab-{environment}_{service_name}")
    tasks = service.tasks()
    
    running = sum(1 for t in tasks if t['Status']['State'] == 'running')
    desired = service.attrs['Spec']['Mode']['Replicated']['Replicas']
    
    return ServiceHealth(
        status='healthy' if running == desired else 'unhealthy',
        replicas_running=running,
        replicas_desired=desired
    )
```

No additional configuration files needed - health status determined purely from Docker API.

## API Endpoints

### REST API Endpoints

These endpoints return JSON for programmatic access.

### GET `/api/environments`

Returns current state of all environments.

**Response:**
```json
{
  "prod": {
    "commit_sha": "abc123...",
    "deployed_at": "2025-10-31T10:30:00Z",
    "services": {
      "jellyfin": "2025040803",
      "pihole": "2025.04.0",
      "traefik": "v3.4.4"
    }
  },
  "preprod": {
    "commit_sha": "def456...",
    "deployed_at": "2025-10-31T12:00:00Z",
    "services": {
      "jellyfin": "2025040900",
      "pihole": "2025.04.0",
      "traefik": "v3.4.4"
    }
  }
}
```

### GET `/api/diff`

Returns differences between preprod and prod.

**Response:**
```json
{
  "changes": [
    {
      "service": "jellyfin",
      "prod_version": "2025040803",
      "preprod_version": "2025040900",
      "change_type": "version_bump"
    }
  ],
  "commit_range": {
    "from": "abc123...",
    "to": "def456..."
  }
}
```

### POST `/api/deploy/prod`

Triggers production deployment.

**Request:**
```json
{
  "confirm": true
}
```

**Response:**
```json
{
  "deployment_id": 42,
  "status": "in_progress",
  "started_at": "2025-10-31T13:00:00Z"
}
```

### GET `/api/deploy/prod/{deployment_id}`

Get status of specific deployment.

**Response:**
```json
{
  "deployment_id": 42,
  "status": "success",
  "started_at": "2025-10-31T13:00:00Z",
  "completed_at": "2025-10-31T13:05:00Z",
  "duration_seconds": 300,
  "services_deployed": [
    {
      "name": "jellyfin",
      "version": "2025040900",
      "health_status": "healthy"
    }
  ]
}
```

### GET `/api/history`

Returns deployment history.

**Query parameters:**
- `environment`: Filter by environment (optional)
- `service`: Filter by service (optional)
- `limit`: Number of records (default: 50)
- `offset`: Pagination offset (default: 0)

**Response:**
```json
{
  "deployments": [
    {
      "id": 42,
      "environment": "prod",
      "service_name": "jellyfin",
      "version": "2025040900",
      "status": "success",
      "deployed_by": "manual",
      "started_at": "2025-10-31T13:00:00Z",
      "completed_at": "2025-10-31T13:05:00Z"
    }
  ],
  "total": 150,
  "limit": 50,
  "offset": 0
}
```

### POST `/api/rollback/prod`

Rollback production to previous deployment.

**Request:**
```json
{
  "deployment_history_id": 40,
  "confirm": true
}
```

### GET `/api/health`

Returns current health status of all services.

**Response:**
```json
{
  "prod": {
    "jellyfin": {
      "status": "healthy",
      "replicas_running": 1,
      "replicas_desired": 1,
      "last_checked": "2025-10-31T13:10:00Z"
    },
    "pihole": {
      "status": "healthy",
      "replicas_running": 1,
      "replicas_desired": 1,
      "last_checked": "2025-10-31T13:10:00Z"
    }
  },
  "preprod": {
    "jellyfin": {
      "status": "healthy",
      "replicas_running": 1,
      "replicas_desired": 1,
      "last_checked": "2025-10-31T13:10:00Z"
    }
  }
}
```

### GET `/`

Serves the web UI (HTML with HTMX and Alpine.js).

### HTMX Endpoints

These endpoints return HTML fragments for HTMX to swap into the page.

### GET `/ui/environments`

Returns HTML fragment showing current environment states.

**HTMX attributes:**
```html
<div hx-get="/ui/environments" 
     hx-trigger="every 30s"
     hx-swap="outerHTML">
  <!-- Content auto-refreshes every 30 seconds -->
</div>
```

### GET `/ui/diff`

Returns HTML fragment showing differences between environments.

### POST `/ui/deploy/prod`

Triggers production deployment, returns status HTML fragment.

### GET `/ui/deploy/status/{deployment_id}`

Returns HTML fragment with current deployment status. Polled during active deployments.

### GET `/ui/history`

Returns HTML fragment with deployment history.

**Query parameters:**
- `environment`: Filter by environment
- `limit`: Number of records (default: 20)
- `offset`: Pagination offset

### GET `/ui/health`

Returns HTML fragment with service health status. Auto-refreshes every 10 seconds.

## Web UI Design

Single-page application using HTMX for dynamic updates and Alpine.js for client-side interactivity.

### HTML Structure

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Release Manager</title>
    <link rel="stylesheet" href="/static/css/style.css">
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <script src="https://unpkg.com/alpinejs@3.13.3" defer></script>
</head>
<body>
    <header>
        <h1>Release Manager</h1>
        <nav x-data="{ activeTab: 'dashboard' }">
            <button @click="activeTab = 'dashboard'" 
                    :class="{ active: activeTab === 'dashboard' }"
                    hx-get="/ui/dashboard" 
                    hx-target="#content">
                Dashboard
            </button>
            <button @click="activeTab = 'history'" 
                    :class="{ active: activeTab === 'history' }"
                    hx-get="/ui/history" 
                    hx-target="#content">
                History
            </button>
            <button @click="activeTab = 'health'" 
                    :class="{ active: activeTab === 'health' }"
                    hx-get="/ui/health" 
                    hx-target="#content">
                Health
            </button>
        </nav>
    </header>
    
    <main id="content">
        <!-- Dynamic content loaded here via HTMX -->
    </main>
</body>
</html>
```

### 1. Environment Dashboard

```html
<div class="dashboard">
    <!-- Auto-refresh every 30 seconds -->
    <div hx-get="/ui/environments" 
         hx-trigger="load, every 30s"
         hx-swap="innerHTML">
        
        <div class="environments-grid">
            <div class="environment-card">
                <h3>Production</h3>
                <p class="meta">Deployed 2h ago • Commit: abc123...</p>
                <div class="services">
                    <div class="service healthy">
                        <span class="name">jellyfin</span>
                        <span class="version">2025040803</span>
                        <span class="health-dot"></span>
                    </div>
                    <div class="service healthy">
                        <span class="name">pihole</span>
                        <span class="version">2025.04.0</span>
                        <span class="health-dot"></span>
                    </div>
                </div>
            </div>
            
            <div class="environment-card">
                <h3>Preprod</h3>
                <p class="meta">Deployed 15m ago • Commit: def456...</p>
                <div class="services">
                    <div class="service healthy newer">
                        <span class="name">jellyfin</span>
                        <span class="version">2025040900</span>
                        <span class="badge">NEWER</span>
                        <span class="health-dot"></span>
                    </div>
                    <div class="service healthy">
                        <span class="name">pihole</span>
                        <span class="version">2025.04.0</span>
                        <span class="health-dot"></span>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Diff view -->
    <div class="diff-section" hx-get="/ui/diff" hx-trigger="load" hx-swap="innerHTML">
        <h3>Changes to Deploy</h3>
        <table class="diff-table">
            <thead>
                <tr>
                    <th>Service</th>
                    <th>Production</th>
                    <th>Preprod</th>
                    <th>Change</th>
                </tr>
            </thead>
            <tbody>
                <tr class="changed">
                    <td>jellyfin</td>
                    <td>2025040803</td>
                    <td>2025040900</td>
                    <td><span class="badge version-bump">Version Bump</span></td>
                </tr>
                <tr class="unchanged">
                    <td>pihole</td>
                    <td>2025.04.0</td>
                    <td>2025.04.0</td>
                    <td><span class="badge">No Change</span></td>
                </tr>
            </tbody>
        </table>
        
        <!-- Alpine.js for deployment state -->
        <div class="actions" x-data="{ deploying: false, showConfirm: false }">
            <button 
                @click="showConfirm = true"
                :disabled="deploying"
                class="btn-primary"
                x-show="!showConfirm">
                Deploy to Production
            </button>
            
            <div x-show="showConfirm" class="confirm-dialog" x-cloak>
                <p>Deploy these changes to production?</p>
                <button 
                    hx-post="/ui/deploy/prod" 
                    hx-target="#deployment-status"
                    @click="deploying = true; showConfirm = false"
                    class="btn-danger">
                    Confirm Deploy
                </button>
                <button @click="showConfirm = false" class="btn-secondary">
                    Cancel
                </button>
            </div>
            
            <div id="deployment-status"></div>
        </div>
    </div>
</div>
```

### 2. Deployment History

```html
<div class="history-view">
    <div class="filters" x-data="{ 
        environment: 'all', 
        service: 'all' 
    }">
        <select x-model="environment" 
                @change="htmx.ajax('GET', `/ui/history?env=${environment}&service=${service}`, '#history-table')">
            <option value="all">All Environments</option>
            <option value="prod">Production</option>
            <option value="preprod">Preprod</option>
        </select>
        
        <select x-model="service"
                @change="htmx.ajax('GET', `/ui/history?env=${environment}&service=${service}`, '#history-table')">
            <option value="all">All Services</option>
            <option value="jellyfin">Jellyfin</option>
            <option value="pihole">Pi-hole</option>
            <!-- More services... -->
        </select>
    </div>
    
    <div id="history-table" 
         hx-get="/ui/history" 
         hx-trigger="load"
         hx-swap="innerHTML">
        
        <table class="history-table">
            <thead>
                <tr>
                    <th>Environment</th>
                    <th>Service</th>
                    <th>Version</th>
                    <th>Status</th>
                    <th>Time</th>
                    <th>By</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                <tr class="status-success" x-data="{ expanded: false }">
                    <td>preprod</td>
                    <td>jellyfin</td>
                    <td>2025040900</td>
                    <td><span class="badge success">✓</span></td>
                    <td>15m ago</td>
                    <td>system</td>
                    <td>
                        <button @click="expanded = !expanded" class="btn-icon">
                            <span x-show="!expanded">▶</span>
                            <span x-show="expanded">▼</span>
                        </button>
                    </td>
                </tr>
                <tr x-show="expanded" class="details-row">
                    <td colspan="7">
                        <div class="deployment-details">
                            <p>Duration: 2m 34s</p>
                            <p>Commit: abc123...</p>
                            <p>Health: All checks passed</p>
                        </div>
                    </td>
                </tr>
            </tbody>
        </table>
        
        <div class="pagination">
            <button 
                hx-get="/ui/history?offset=20" 
                hx-target="#history-table"
                hx-swap="innerHTML"
                class="btn-secondary">
                Load More
            </button>
        </div>
    </div>
</div>
```

### 3. Health Status

```html
<div class="health-view">
    <!-- Auto-refresh every 10 seconds -->
    <div hx-get="/ui/health" 
         hx-trigger="load, every 10s"
         hx-swap="innerHTML">
        
        <div class="environment-health">
            <h3>Production</h3>
            <div class="services-health">
                <div class="service-health healthy" 
                     x-data="{ showDetails: false }">
                    <div class="health-summary" @click="showDetails = !showDetails">
                        <span class="icon">✓</span>
                        <span class="name">jellyfin</span>
                        <span class="replicas">1/1</span>
                        <span class="last-check">30s ago</span>
                    </div>
                    <div x-show="showDetails" class="health-details" x-cloak>
                        <p>Version: 2025040803</p>
                        <p>Uptime: 2d 14h 23m</p>
                        <p>HTTP Check: ✓ 200 OK</p>
                    </div>
                </div>
                
                <div class="service-health unhealthy"
                     x-data="{ showDetails: false }">
                    <div class="health-summary" @click="showDetails = !showDetails">
                        <span class="icon">✗</span>
                        <span class="name">pihole</span>
                        <span class="replicas">0/1</span>
                        <span class="last-check">10s ago</span>
                    </div>
                    <div x-show="showDetails" class="health-details" x-cloak>
                        <p class="error">Container failed to start</p>
                        <p>Last logs: Error binding to port 53...</p>
                        <button 
                            hx-post="/api/restart/prod/pihole"
                            hx-swap="none"
                            class="btn-warning">
                            Restart Service
                        </button>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="environment-health">
            <h3>Preprod</h3>
            <!-- Similar structure -->
        </div>
    </div>
</div>
```

### 4. Deployment Status (During Active Deployment)

```html
<div id="deployment-status" 
     class="deployment-status deploying"
     hx-get="/ui/deploy/status/42"
     hx-trigger="every 2s"
     hx-swap="outerHTML">
    
    <div class="deployment-progress">
        <div class="spinner"></div>
        <h4>Deploying to Production</h4>
        
        <div class="progress-bar">
            <div class="progress" style="width: 45%"></div>
        </div>
        
        <div class="deployment-steps">
            <div class="step completed">
                <span class="icon">✓</span>
                <span>Fetched configuration</span>
            </div>
            <div class="step in-progress">
                <span class="icon spinner-small"></span>
                <span>Updating services...</span>
            </div>
            <div class="step pending">
                <span class="icon">○</span>
                <span>Health checks</span>
            </div>
        </div>
        
        <button 
            hx-post="/api/deploy/cancel/42"
            hx-confirm="Cancel this deployment?"
            class="btn-danger-outline">
            Cancel Deployment
        </button>
    </div>
</div>
```

### Key HTMX Patterns Used

1. **Polling**: `hx-trigger="every 30s"` for auto-refresh
2. **Load on view**: `hx-trigger="load"` for initial data fetch
3. **Targeted swaps**: `hx-target="#specific-id"` for precise updates
4. **Confirmations**: `hx-confirm="..."` for user prompts
5. **Indicators**: `hx-indicator="#spinner"` for loading states

### Key Alpine.js Patterns Used

1. **Local state**: `x-data="{ expanded: false }"` for component state
2. **Conditional display**: `x-show` for toggling elements
3. **Event handlers**: `@click` for interactions
4. **Dynamic classes**: `:class="{ active: ... }"` for styling
5. **Cloak**: `x-cloak` to prevent flash of unstyled content

## Configuration

### Environment Variables

```bash
# GitHub Configuration
GITHUB_REPO=user/homelab
GITHUB_TOKEN=ghp_...           # Optional, for private repos

# Polling Configuration
POLL_INTERVAL_SECONDS=60

# Docker Configuration
DOCKER_HOST=unix:///var/run/docker.sock

# Database
DATABASE_PATH=/data/release-manager.db

# Deployment Configuration
DEPLOYMENT_TIMEOUT_SECONDS=300
HEALTH_CHECK_INTERVAL_SECONDS=5

# Web UI
WEB_HOST=0.0.0.0
WEB_PORT=8080
```

### Docker Compose Service Definition

Add to `docker-swarm-stack.yml`:

```yaml
  release-manager:
    image: release-manager:latest
    build:
      context: ./release-manager
      dockerfile: Dockerfile
    environment:
      GITHUB_REPO: user/homelab
      GITHUB_TOKEN_FILE: /run/secrets/github_token
      POLL_INTERVAL_SECONDS: 60
      DOCKER_HOST: unix:///var/run/docker.sock
      DATABASE_PATH: /data/release-manager.db
      DEPLOYMENT_TIMEOUT_SECONDS: 300
      HEALTH_CHECK_INTERVAL_SECONDS: 5
      WEB_HOST: 0.0.0.0
      WEB_PORT: 8080
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /srv/data/${ENV_NAME}/release-manager:/data
    secrets:
      - github_token
    networks:
      - homelab-shared
    deploy:
      replicas: 1
      labels:
        - "env=${ENV_NAME}"
        - "traefik.enable=true"
        - "traefik.http.routers.release-manager-${ENV_NAME}.rule=Host(`release-manager.${DOMAIN_SUFFIX}`)"
        - "traefik.http.services.release-manager-${ENV_NAME}.loadbalancer.server.port=8080"
      restart_policy:
        condition: on-failure
      placement:
        constraints:
          - node.labels.hardware == n100
      resources:
        limits:
          memory: 256M
        reservations:
          memory: 128M
```

## Project Structure

```
release-manager/
├── Dockerfile
├── Makefile                     # Development and build tasks
├── requirements.txt
├── pyproject.toml              # Project metadata and dependencies
├── schema.sql                  # SQLite database schema
├── .env.example                # Example environment variables
├── data/                       # SQLite database (gitignored)
│   └── release-manager.db
├── src/
│   └── release_manager/
│       ├── __init__.py
│       ├── main.py              # FastAPI app entry point
│       ├── config.py            # Configuration management
│       ├── database.py          # SQLite connection and queries
│       ├── models.py            # Pydantic models for validation and data structures
│       ├── poller.py            # GitHub polling background task
│       ├── deployer.py          # Deployment orchestration
│       ├── health.py            # Health check logic
│       ├── github.py            # GitHub API client
│       ├── docker_client.py     # Docker SDK wrapper
│       └── routers/
│           ├── __init__.py
│           ├── api.py           # JSON API endpoints
│           ├── ui.py            # HTMX HTML fragment endpoints
│           └── pages.py         # Full page templates
├── static/
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── app.js               # Minimal custom JS if needed
├── templates/
│   ├── base.html                # Base template with HTMX/Alpine
│   ├── index.html               # Main dashboard
│   └── partials/
│       ├── environments.html    # Environment cards
│       ├── diff.html            # Diff table
│       ├── history.html         # History table
│       ├── health.html          # Health status
│       └── deploy-status.html   # Deployment progress
└── tests/
    ├── __init__.py
    ├── test_database.py
    ├── test_deployer.py
    ├── test_github.py
    └── test_api.py
```

## Security Considerations

1. **GitHub Token**: Store in Docker secret, read-only access sufficient
2. **Docker Socket**: Mount read-only where possible, but deployment requires write access
3. **Web UI Authentication**: Consider adding basic auth or OAuth for production use
4. **Rate Limiting**: Implement on API endpoints to prevent abuse
5. **Input Validation**: Sanitise all user inputs, especially service names and versions

## Deployment Considerations

1. **Single Instance**: Only one replica should run to avoid race conditions
2. **Placement**: Should run on a Swarm manager node (needs Docker socket access)
3. **Persistence**: SQLite database must be on persistent volume
4. **Secrets**: GitHub token should be created as Docker secret before deployment

## Testing Strategy

1. **Unit Tests**: Test individual components (parser, health checks, etc.)
2. **Integration Tests**: Test GitHub API interaction, Docker SDK usage
3. **End-to-End Tests**: Spin up test stack, trigger deployments, verify state
4. **Manual Testing**: Test web UI in browser, verify workflows

## Design Decisions

### Answered Questions

1. **Dry-run deployments**: Not implemented - rollback is simple enough
2. **Deployment approval workflow**: No approval gates - manual trigger via web UI is sufficient
3. **Concurrent deployments**: Reject new requests while deployment in progress
4. **Partial deployments**: Yes - support deploying individual services
5. **Health check configuration**: No config file - use Docker Swarm status only

## Success Criteria

1. Preprod automatically syncs with GitHub master within 60 seconds of changes
2. Web UI displays current state of both environments accurately
3. Manual prod deployment succeeds and updates all services correctly
4. Docker health checks correctly identify service status
5. Deployment history is accurately recorded
6. System handles concurrent deployment requests correctly (rejects while in progress)
7. System recovers gracefully from failures (GitHub API down, Docker issues, etc.)
8. Partial service deployments work correctly

## Implementation Priority

### Phase 1: Core Functionality
1. Database schema and SQL queries
2. GitHub polling and env file parsing
3. Docker SDK integration for deployments
4. Docker health checks
5. API endpoints for environments and deployments

### Phase 2: Web UI
1. HTMX/Alpine.js dashboard
2. Environment comparison view
3. Deployment trigger interface
4. History view

### Phase 3: Advanced Features
1. Partial service deployments
2. Rollback functionality
3. Detailed deployment status tracking
4. Error handling and recovery

### Phase 4: Polish
1. Logging and monitoring
2. Performance optimisation
3. Documentation
4. Testing
