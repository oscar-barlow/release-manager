# AGENTS README

This document captures working agreements and operational context gathered across recent collaboration on `release-manager`. Future agents should treat it as the first stop before making changes.

## Product & Interface Vision
- The service is a deployment manager for `home.services`, running FastAPI with HTMX/Alpine UI fragments.
- The UI should feel premium: follow the **Spark** design philosophy emphasising polished typography, purposeful hierarchy, thoughtful empty/loading states, and subtle motion. Keep a cohesive visual system; new components should align with the existing glassmorphism styling in `static/css/style.css`.
- Navigation uses HTMX + minimal Alpine JS. Maintain graceful degradation—server fragments must work without assuming heavy client frameworks.

## Environment & Configuration
- `.env.*` files drive runtime config; `.env.dev` is used locally. Environment variables should always favour these files over hard-coded defaults.
- `STUB_MODE=true` is only allowed for **dev/test** `ENV_NAME`s. All other environments must use the real Docker integration.
- GitHub access tokens are read from a **file path** (`GITHUB_TOKEN_FILE`), never from raw env variables, honouring secrets management guidance.

## Docker & Deployments
- Docker interactions now use a polymorphic hierarchy in `release_manager/docker_client.py`:
  - `StubbedDockerService` feeds deterministic data for the Directory tab in dev/test.
  - `EnvironmentDockerService` talks to real Docker Swarm for preprod/prod.
  - All consumers depend on the abstract `DockerService` interface; respect this separation when extending functionality.
- Directory tab (HTMX endpoint `/ui/directory`) expects `list_services_by_environment()` to return grouped snapshots matching this contract.

## Backend Notes
- Database helpers ensure UTC timestamps and deterministic IDs. Follow existing helpers for inserts/updates; avoid bypassing `_to_iso` / `_utcnow`.
- `DeploymentEngine` serialises deployments via an asyncio lock. Any new async work should remain concurrency-safe.
- Health checks persist via `HealthService`, which expects Docker services to return meaningful statuses even in stub mode.

## Testing & Tooling
- Python ≥ 3.11; dependency resolution uses `uv`.
- Commands (with `UV_CACHE_DIR=./.uv-cache`):
  1. `uv run pytest`
  2. `uv run mypy`
- CI (`.github/workflows/ci.yml`) blocks publishes until tests, type checks, and build succeed. Keep both jobs green. Ruff linting is already wired via dev extras; run as needed.

## Frontend Additions
- Templates live under `templates/`, fragments under `templates/partials/`. Use inclusion patterns consistent with existing HTMX flows.
- JS helpers sit in `static/js/app.js`; keep scripts lightweight and progressive-enhancement friendly.
- CSS belongs in `static/css/style.css`; follow current token system (`--bg-*`, `--accent`, etc.) and responsive rules.

## General Working Practices
- Maintain strict typing—mypy runs with `disallow_untyped_defs` and friends. Use `typing.cast` rather than `type: ignore`.
- Keep comments concise and purposeful; favour clean code over excessive documentation.
- Avoid renaming existing directories like `release_manager` unless explicitly requested (previously clarified that `src/` was undesired).
- Never create Docker image tags as Git tags; container tags follow `YYYY-M-D.increment` logic handled in CI.

## Useful References
- Design guidelines: `system_prompt.md` (`Design Philosophy` / `Human Interface` sections).
- High-level architecture & expectations: `release-manager-design.md`.
- Stub sample data resides in `StubbedDockerService._build_snapshots`.

Stay aligned with these constraints to keep future contributions harmonious with the established direction.***
