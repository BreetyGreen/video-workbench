# Video Workbench Local Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the user's existing local cloud configuration, add a safe provider configuration center, and turn Jianying delivery from a ZIP download into a real host-aware import-and-open workflow on Windows and macOS.

**Architecture:** Optional provider credentials are encrypted in the existing local SQLite database and applied on service startup; setup pages expose only masked state and never return stored values. Jianying detection is performed by the native launcher, written to a shared runtime manifest, and consumed by the control plane so Docker does not mistake the host for Linux. Draft import remains bounded and non-overwriting, while a native helper handles opening the desktop client.

**Tech Stack:** FastAPI, SQLModel, Fernet, vanilla JavaScript, PowerShell, Python stdlib, Docker Compose, pytest.

## Global Constraints

- Local editing remains usable with no cloud credentials.
- No secret value may appear in API responses, logs, commits, screenshots, or documentation.
- Existing tasks, artifacts, licensed media, and Jianying drafts are never deleted or overwritten.
- Provider changes are stored locally and take effect after a controlled service restart.
- Jianying automation stops at safe draft import and opening the client; it does not automate export or publishing.
- Windows and macOS must share the same runtime-manifest and handoff-state contract.

---

### Task 1: Encrypted optional-provider configuration center

**Files:**
- Modify: `services/control-plane/app/models.py`
- Create: `services/control-plane/app/schemas/provider_settings.py`
- Create: `services/control-plane/app/services/provider_settings_service.py`
- Modify: `services/control-plane/app/main.py`
- Create: `services/control-plane/app/templates/provider_settings.html`
- Create: `services/control-plane/app/static/provider_settings.js`
- Create: `services/control-plane/app/static/provider_settings.css`
- Modify: `services/control-plane/app/templates/setup.html`
- Modify: `services/control-plane/app/templates/capabilities.html`
- Test: `services/control-plane/tests/test_provider_settings.py`

**Interfaces:**
- Produces: `ProviderCredential` SQLModel table.
- Produces: `ProviderSettingsService.status(session)`, `save(session, provider_id, values)`, `apply(session, settings)`.
- Produces: `GET /api/provider-settings`, `PUT /api/provider-settings/{provider_id}`, `DELETE /api/provider-settings/{provider_id}`.

- [ ] Write API and service tests proving masked-only reads, encrypted-at-rest storage, merge semantics, unknown-field rejection, delete behavior, and startup application.
- [ ] Run focused tests and confirm they fail because the table, service, and routes do not exist.
- [ ] Implement the minimal model, schemas, registry, encrypted service, API routes, and provider settings page.
- [ ] Run focused tests, JavaScript syntax checks, and confirm green.
- [ ] Commit the provider configuration center.

### Task 2: Host runtime manifest and bounded Jianying import service

**Files:**
- Create: `services/control-plane/app/services/jianying_runtime_service.py`
- Create: `services/control-plane/app/services/jianying_handoff_service.py`
- Modify: `services/control-plane/app/config.py`
- Modify: `services/control-plane/app/main.py`
- Modify: `services/control-plane/app/services/pipeline_service.py`
- Modify: `services/control-plane/app/templates/review.html`
- Modify: `services/control-plane/app/static/review.js`
- Test: `services/control-plane/tests/test_jianying_runtime.py`
- Test: `services/control-plane/tests/test_jianying_handoff.py`
- Modify: `services/control-plane/tests/test_review.py`

**Interfaces:**
- Produces: `JianyingRuntimeService.snapshot()` backed by `runtime/jianying.json` with Docker fallback.
- Produces: `JianyingHandoffService.import_task(task_id) -> dict[str, object]` with idempotent state.
- Produces: `GET/POST /api/tasks/{task_id}/handoff/jianying`.

- [ ] Write failing tests for host-manifest precedence, valid import, path rewriting, media validation, idempotency, traversal rejection, and truthful review actions.
- [ ] Run focused tests and confirm the intended failures.
- [ ] Implement runtime loading and safe staging-to-destination import without overwriting existing drafts.
- [ ] Trigger import after non-blocking quality completion when the runtime is ready; otherwise record a waiting state.
- [ ] Replace the deceptive ZIP action with real handoff status/retry/open controls and keep ZIP as a separate recovery download.
- [ ] Run focused tests and confirm green.
- [ ] Commit the control-plane handoff implementation.

### Task 3: Native Windows/macOS launcher integration

**Files:**
- Create: `scripts/jianying-host-helper.py`
- Modify: `scripts/detect-jianying.ps1`
- Modify: `scripts/bootstrap.ps1`
- Modify: `scripts/bootstrap.sh`
- Modify: `scripts/start-local.sh`
- Modify: `deploy/compose.yml`
- Test: `services/control-plane/tests/test_native_script_contract.py`
- Test: `services/control-plane/tests/test_macos_jianying_discovery.py`

**Interfaces:**
- Produces: native `runtime/jianying.json` and consumes `runtime/open-requests/*.json`.
- Produces: a bounded host helper that launches only the detected Jianying/CapCut executable or app bundle.
- Produces: Docker bind mount `/jianying-drafts` plus a host-path environment value used only for JSON media relinking.

- [ ] Write failing contract tests for native manifest generation, helper startup, draft mount, and open-request processing.
- [ ] Run tests and confirm red.
- [ ] Implement Windows and macOS detection/manifest writing and start the helper hidden/backgrounded.
- [ ] Add the validated draft-root mount with a private fallback directory.
- [ ] Run script-contract and platform tests and confirm green.
- [ ] Commit native launcher integration.

### Task 4: Local migration, full verification, and live acceptance

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/capabilities-and-configuration.md`
- Modify: `docs/codex-operator-guide.md`
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: the three completed feature tasks.
- Produces: current-machine runtime with migrated ASR/Dify configuration and verified Jianying handoff.

- [ ] Safely migrate only non-empty legacy ASR/Dify values into the ignored current `.env` without printing them; preserve a recoverable pre-change copy.
- [ ] Rebuild/restart the local service and verify masked provider states, ASR route availability, and host Jianying readiness.
- [ ] Run full pytest, JavaScript syntax, `git diff --check`, and fresh-clone verification.
- [ ] Generate a multi-source acceptance task, verify preview/captions/quality/draft, import it into a new Jianying draft, and verify all media paths exist.
- [ ] Update human/Codex documentation and commit fresh verification evidence.
