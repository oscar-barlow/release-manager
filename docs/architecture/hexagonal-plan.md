# Hexagonal Architecture Refactor Plan

This document captures the planned transition of `release-manager` to a port-and-adapter (hexagonal) architecture. Keep it updated as implementation progresses.

## Objectives

- Centre all business logic in a framework-agnostic application core.
- Model all external interactions (DB, GitHub, Docker, web UI, scheduling) as adapters connected via well-defined ports.
- Enable extensive, fast unit testing of the core while keeping adapter/integration tests targeted.

## Current Landscape (as of 2025-xx-xx)

- Core logic lives in `DeploymentEngine`, `EnvironmentPoller`, database helpers, etc., tightly coupled to concrete adapters (SQLite, Docker, GitHub).
- FastAPI endpoints and poller directly orchestrate deployments and persistence.
- Tests cover API + DB + deployer + GitHub parsing, but lack adapter contract coverage and richer domain scenarios.

## Target Architecture

### Domain / Application Core
Use-cases exposed by application services:
- `EnvironmentSynchroniser`: computes diffs, orchestrates preprod syncs, resolves partial deployments.
- `DeploymentCoordinator`: handles prod deploys/rollbacks, history tracking.
- `HealthMonitor`: refreshes status for tracked services.
- `ManifestComparator`: compares environment manifests and produces diffs for UI/API.

Domain entities / value objects:
- `EnvironmentSnapshot`, `ServiceVersion`, `DeploymentRecord`, `HealthSnapshot`, `DeploymentDiff`.

Utilities: `Clock`, `Logger` interfaces for deterministic behaviour.

### Ports (Interfaces)
Outbound (driven) ports:
- `EnvironmentRepository`: load/save environment state.
- `DeploymentHistoryRepository`.
- `ServiceHealthRepository`.
- `ManifestFetcher`: fetch environment .env manifests.
- `ContainerOrchestrator`: deploy stacks/services.
- `Notifier` (optional future; e.g., Slack alerts).
- `Clock`, `Logger`.

Inbound (driving) ports (adapters will call core):
- FastAPI controllers (HTTP API + HTMX UI).
- Poller / scheduler.
- CLI or background tasks.

### Adapters
Primary (driving) adapters:
- FastAPI router modules.
- Poller scheduler.

Secondary (driven) adapters:
- SQLite repositories (`EnvironmentRepository`, etc.).
- GitHub HTTP client implementing `ManifestFetcher`.
- Docker SDK / CLI executor implementing `ContainerOrchestrator`.
- Stub Docker service reimplemented as adapter, still fulfilling `ContainerOrchestrator`.
- Logging/time wrappers.

### Wiring
- Composition root in `main.py` builds adapters, injects ports into application services, and registers inbound adapters (FastAPI endpoints, poller) against the core interfaces.

## Testing Strategy

1. **Unit tests (core)**: exhaustive coverage of application services and domain objects using fake ports; no I/O.
2. **Contract tests**: ensure adapters honour port contracts (e.g., Docker adapter respects interface semantics, GitHub adapter handles API errors).
3. **Integration tests**: DB migrations + repositories, real HTTP interactions mocked via respx, Docker CLI simulated.
4. **End-to-end smoke**: FastAPI + poller booted with stub adapters verifying wiring and key flows.
5. **Test suites organisation**:
   - `tests/unit` for core.
   - `tests/adapters` for contract/integration.
   - `tests/e2e` for smoke scenarios.
   - Pytest markers (`unit`, `integration`, `e2e`) with CI stages.

## Refactor Phases

1. **Documentation & scaffolding**
   - Maintain this plan.
   - Introduce `docs/architecture/` overview and ADR once ports stabilise.

2. **Define port interfaces**
   - Create `release_manager/application/ports` module with protocols/interfaces for repositories, orchestrators, etc.
   - Provide DTOs/value objects in `release_manager/domain`.

3. **Extract domain services**
   - Move logic from `DeploymentEngine`, `EnvironmentPoller`, DB helpers into core services using ports.
   - Ensure no adapter imports in core.

4. **Adapter implementation**
   - Adapt SQLite, Docker, GitHub, stub modules to implement new ports.
   - Keep legacy implementations until migration completes (strangler pattern).

5. **Rewire composition**
   - Update FastAPI endpoints and poller to use new application services.
   - Remove obsolete classes once replaced.

6. **Testing overhaul**
   - Add unit tests for new core services.
   - Add contract tests per adapter.
   - Introduce new test layout and adjust CI.

7. **Cleanup & ADR**
   - Remove deprecated modules.
   - Document architecture decision (ADR) and update READMEs.

## Open Questions / TODOs

- How to manage migrations while refactoring repository layer?
- Do we need a message bus/event system for future scaling?
- Consider dependency injection tooling once ports proliferate.

Track progress by ticking off phases and updating references in this plan.***
