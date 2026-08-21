# Cloud Usage Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add secure local credential configuration, official Volcengine balance/Ark usage queries, and task-attributed ASR/TTS/Dify usage reporting to the video workbench.

**Architecture:** Persist encrypted management credentials and immutable usage events in the existing SQLModel database. A focused Volcengine management client signs read-only OpenAPI requests, while a usage service aggregates official snapshots and local events for the workbench and review pages. Existing adapters expose measured usage metadata; the pipeline records events without making usage persistence a hard dependency of video generation.

**Tech Stack:** Python 3.11, FastAPI, SQLModel/SQLite, httpx, cryptography/Fernet, Jinja2, vanilla JavaScript/CSS, pytest.

## Global Constraints

- Never return, log, place in URLs, or store in browser storage any AK/SK plaintext.
- Every displayed metric must identify `official`, `local_measured`, or `local_estimated` as its source.
- Official API failures must preserve and label the last successful snapshot; they must never become a zero balance.
- Usage-ledger failures must not fail the video pipeline.
- No purchase, recharge, IAM mutation, resource deletion, or quota-changing actions.
- Existing uncommitted audio-routing and production changes are user work and must be preserved.

---

### Task 1: Encrypted credentials and usage tables

**Files:**
- Modify: `services/control-plane/pyproject.toml`
- Modify: `services/control-plane/app/config.py`
- Modify: `services/control-plane/app/models.py`
- Create: `services/control-plane/app/services/secret_store.py`
- Test: `services/control-plane/tests/test_cloud_usage_store.py`

**Interfaces:**
- Produces: `SecretStore(master_secret: str)`, `encrypt(value: str) -> str`, `decrypt(token: str) -> str`, SQLModel tables `CloudCredential`, `UsageEvent`, `UsageBudget`, `OfficialUsageSnapshot`.

- [ ] Write failing tests proving ciphertext excludes plaintext, decrypt round-trips, masked IDs expose only prefix/suffix, and SQLModel creates all four tables.
- [ ] Run `pytest tests/test_cloud_usage_store.py -v` and verify failures are caused by missing models/store.
- [ ] Add `cryptography==46.0.1`, `usage_secret_master_key` setting, focused models, and Fernet encryption derived with SHA-256 and urlsafe base64.
- [ ] Run the focused tests and the existing database tests; expect PASS.
- [ ] Commit only Task 1 files with `feat: add secure cloud usage storage`.

### Task 2: Immutable local usage ledger

**Files:**
- Create: `services/control-plane/app/services/usage_service.py`
- Create: `services/control-plane/app/schemas/usage.py`
- Test: `services/control-plane/tests/test_usage_service.py`

**Interfaces:**
- Consumes: `UsageEvent`, `UsageBudget`.
- Produces: `record_event(session, *, task_id, provider, service, metric, quantity, unit, status, request_id='', metadata=None)`, `task_usage(session, task_id)`, `local_summary(session)`.

- [ ] Write failing tests for successful, failed, and `succeeded_not_applied` events; task isolation; ASR/TTS/token aggregation; and 20%/10% thresholds.
- [ ] Verify RED with `pytest tests/test_usage_service.py -v`.
- [ ] Implement Pydantic response schemas and pure aggregation helpers; never place prompt, transcript, narration, or secrets in metadata.
- [ ] Verify GREEN and run `pytest tests/test_tasks.py tests/test_review.py -v`.
- [ ] Commit Task 2 as `feat: record task cloud usage events`.

### Task 3: Read-only Volcengine management client

**Files:**
- Create: `services/control-plane/app/adapters/volcengine_usage.py`
- Test: `services/control-plane/tests/test_volcengine_usage.py`

**Interfaces:**
- Produces: `VolcengineUsageClient(access_key_id, secret_access_key, transport=None, now=None)`, `query_balance() -> BalanceSnapshot`, `get_inference_usage(start_time, end_time, interval='Day') -> ArkUsageSnapshot`.

- [ ] Write deterministic failing tests asserting canonical query ordering, HMAC-SHA256 authorization scope, no secret in request/exception text, parsed balance fields, parsed input/output/total tokens, and permission errors.
- [ ] Verify RED.
- [ ] Implement the signer with standard-library hashlib/hmac and httpx; use service `billing` for `QueryBalanceAcct` and service `ark`, region `cn-beijing`, version `2024-01-01` for `GetInferenceUsage`.
- [ ] Verify GREEN and run adapter tests.
- [ ] Commit Task 3 as `feat: query official volcengine usage`.

### Task 4: Credential settings and summary APIs

**Files:**
- Modify: `services/control-plane/app/main.py`
- Create: `services/control-plane/app/services/cloud_usage_service.py`
- Modify: `services/control-plane/app/schemas/usage.py`
- Test: `services/control-plane/tests/test_cloud_usage_api.py`

**Interfaces:**
- Produces endpoints `GET/PUT /api/cloud-usage/settings`, `POST /api/cloud-usage/verify`, `GET /api/cloud-usage/summary`, `POST /api/cloud-usage/refresh`, `GET /api/tasks/{task_id}/usage`.

- [ ] Write failing API tests that prove secret fields never appear, invalid new credentials preserve old credentials, localhost origin rules reject cross-site writes, summaries label sources, and cached official snapshots survive upstream failure.
- [ ] Verify RED.
- [ ] Implement settings validation, encrypted persistence, five-minute official cache, refresh throttling, and task usage endpoint.
- [ ] Verify GREEN and run all API tests.
- [ ] Commit Task 4 as `feat: expose cloud usage APIs`.

### Task 5: Instrument ASR, TTS, and Dify without losing fallback usage

**Files:**
- Modify: `services/control-plane/app/adapters/dify.py`
- Modify: `services/control-plane/app/adapters/volcano_tts.py`
- Modify: `services/control-plane/app/services/pipeline_service.py`
- Modify: `services/control-plane/app/services/media_analysis_service.py`
- Test: `services/control-plane/tests/test_dify.py`
- Test: `services/control-plane/tests/test_volcano_tts.py`
- Test: `services/control-plane/tests/test_pipeline.py`

**Interfaces:**
- Dify responses expose `WorkflowUsage(workflow_run_id, input_tokens, output_tokens, total_tokens, elapsed_time)` even when output parsing fails.
- TTS results expose `character_count` in addition to duration and voice type.
- Pipeline records cloud ASR only when `TranscriptResult.provider == 'volcano_bigasr'`.

- [ ] Add failing tests for Dify success usage, Dify parse failure retaining usage, TTS character count, cloud ASR seconds, and non-cloud transcriptions producing no cloud event.
- [ ] Verify RED.
- [ ] Add usage metadata without recording content; inject `UsageService` into the pipeline and wrap ledger writes so persistence failure becomes a warning.
- [ ] Verify GREEN, then run pipeline/audio/transcription tests.
- [ ] Commit Task 5 as `feat: meter video cloud calls`.

### Task 6: Workbench, settings, and review UI

**Files:**
- Modify: `services/control-plane/app/templates/workbench.html`
- Modify: `services/control-plane/app/templates/review.html`
- Create: `services/control-plane/app/templates/cloud_usage_settings.html`
- Modify: `services/control-plane/app/static/workbench.js`
- Modify: `services/control-plane/app/static/workbench.css`
- Modify: `services/control-plane/app/static/review.css`
- Create: `services/control-plane/app/static/cloud_usage_settings.js`
- Test: `services/control-plane/tests/test_workbench.py`
- Test: `services/control-plane/tests/test_review.py`
- Test: `services/control-plane/tests/test_cloud_usage_api.py`

**Interfaces:**
- Produces route `GET /settings/cloud-usage` and renders official balance, Ark usage, local ASR/TTS estimates, source badges, stale/error state, per-task usage, masked credential state, clipboard import, verify, and save.

- [ ] Write failing HTML/API tests for headings, source labels, no plaintext secret, settings asset delivery, and task-specific metrics.
- [ ] Verify RED.
- [ ] Implement semantic responsive markup, JS data loading, same-origin credential submission, clipboard buttons using `navigator.clipboard.readText()` only on explicit user clicks, and threshold styles.
- [ ] Verify GREEN and run workbench/review/API tests.
- [ ] Commit Task 6 as `feat: show cloud usage dashboard`.

### Task 7: Documentation, migration verification, and live smoke test

**Files:**
- Modify: `.env.example`
- Modify: `docs/progress.md`
- Create: `docs/runbooks/cloud-usage.md`
- Modify: `README.md`

**Interfaces:**
- Documents the local setup page, permission modes, official-vs-estimated meanings, rotation, and troubleshooting without example secrets.

- [ ] Add documentation assertions or static checks for required environment names and no secret literals.
- [ ] Rebuild/start the control-plane service and verify `/health`, `/`, `/settings/cloud-usage`, and the current task review page.
- [ ] Run the full suite with `pytest -q`; expect all tests PASS.
- [ ] Verify the existing current task still opens and its artifacts remain intact.
- [ ] Commit Task 7 as `docs: operate cloud usage monitoring`.
