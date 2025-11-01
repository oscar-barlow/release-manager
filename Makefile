.PHONY: dev test lint format db-init db-reset docker-build docker-run clean help

UV_CACHE_DIR := ./.uv-cache
UV := UV_CACHE_DIR=$(UV_CACHE_DIR) uv
ENVIRONMENT_NAME ?= dev
DATABASE_DIR := data
DATABASE_FILE := $(DATABASE_DIR)/release-manager-$(ENVIRONMENT_NAME).db

GITHUB_TOKEN_SECRET := $(CURDIR)/.secrets/github_token
ifneq (,$(wildcard $(GITHUB_TOKEN_SECRET)))
DOCKER_SECRET_FLAGS := -v $(GITHUB_TOKEN_SECRET):/run/secrets/github_token:ro -e GITHUB_TOKEN_FILE=/run/secrets/github_token
else
DOCKER_SECRET_FLAGS :=
endif

help:
	@echo "Available targets:"
	@echo "  dev          - Run development server with auto-reload"
	@echo "  test         - Run test suite"
	@echo "  lint         - Run linting (ruff)"
	@echo "  format       - Format code (ruff)"
	@echo "  db-init      - Initialize SQLite database"
	@echo "  db-reset     - Reset database (drop and recreate)"
	@echo "  db-upgrade   - Apply latest database migrations"
	@echo "  docker-build - Build Docker image"
	@echo "  docker-run   - Run Docker container locally"
	@echo "  clean        - Remove build artifacts and cache"

dev:
	@echo "🚀 Starting development server..."
	$(UV) run uvicorn release_manager.main:app --reload --host 0.0.0.0 --port 8080

test:
	@echo "🧪 Running tests..."
	$(UV) run pytest tests/ -v

lint:
	@echo "🔍 Running linter..."
	$(UV) run ruff check src/ tests/

format:
	@echo "✨ Formatting code..."
	$(UV) run ruff format src/ tests/
	$(UV) run ruff check --fix src/ tests/

db-init:
	@echo "📦 Initializing database..."
	@if [ -f $(DATABASE_FILE) ]; then \
		echo "❌ Database already exists at $(DATABASE_FILE)"; \
		echo "   Use 'make db-reset' to recreate"; \
		exit 1; \
	fi
	@mkdir -p $(DATABASE_DIR)
	ENVIRONMENT_NAME=$(ENVIRONMENT_NAME) DATABASE_PATH=$(DATABASE_FILE) $(UV) run python -m release_manager.migrations upgrade
	@echo "✅ Database initialized at $(DATABASE_FILE)"

db-reset:
	@echo "⚠️  Resetting database..."
	@read -p "This will delete all data. Continue? (y/N) " confirm; \
	if [ "$$confirm" = "y" ]; then \
		rm -f $(DATABASE_FILE); \
		mkdir -p $(DATABASE_DIR); \
		ENVIRONMENT_NAME=$(ENVIRONMENT_NAME) DATABASE_PATH=$(DATABASE_FILE) $(UV) run python -m release_manager.migrations upgrade; \
		echo "✅ Database reset complete"; \
	else \
		echo "Cancelled"; \
	fi

db-upgrade:
	@echo "⬆️  Applying database migrations..."
	ENVIRONMENT_NAME=$(ENVIRONMENT_NAME) DATABASE_PATH=$(DATABASE_FILE) $(UV) run python -m release_manager.migrations upgrade $(if $(REVISION),--revision $(REVISION),)
	@echo "✅ Database migrated"

docker-build:
	@echo "🐳 Building Docker image..."
	docker build -t release-manager:latest .

docker-run:
	@echo "🐳 Running Docker container..."
	@if [ -f "$(GITHUB_TOKEN_SECRET)" ]; then \
		SECRET_FLAGS="$(DOCKER_SECRET_FLAGS)"; \
	else \
		SECRET_FLAGS=""; \
	fi; \
	docker run -d \
		-p 8080:8080 \
		-v /var/run/docker.sock:/var/run/docker.sock:ro \
		-v $$(pwd)/data:/data \
		-e ENVIRONMENT_NAME=$(ENVIRONMENT_NAME) \
		-e GITHUB_REPO=oscar-barlow/home.services \
		-e DATABASE_PATH=/data/release-manager-$(ENVIRONMENT_NAME).db \
		$$SECRET_FLAGS \
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
