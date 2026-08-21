# Delivery and Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make delivery semantics accurate, verify local Jianying handoff, add a testable official Douyin publishing adapter, and package the server portion for production deployment.

**Architecture:** Separate local editable draft creation from official Douyin upload/create operations. Deploy the web control plane and scheduler as containers, while a Windows-local agent remains responsible for Jianying draft import.

**Tech Stack:** Python 3, FastAPI, httpx, FFmpeg, Jianying Windows client, Docker Compose, reverse proxy, pytest.

## Global Constraints

- Do not label a Douyin video creation response as a draft-box item.
- OAuth consent and platform permission approval remain user actions.
- Server deployment must not imply Jianying is running in a Linux container.
- Secrets remain in environment variables or the existing encrypted local secret store.

---

### Task 1: Delivery State Contract

**Files:**
- Modify: `services/control-plane/app/models/task.py`
- Modify: `services/control-plane/app/schemas/task.py`
- Modify: `services/control-plane/app/services/delivery_service.py`
- Modify: `services/control-plane/app/static/review.js`
- Test: `services/control-plane/tests/test_delivery_states.py`

**Interfaces:**
- Produces: `jianying_draft`, `douyin_self_visible`, and `douyin_published` states with provider IDs and audit timestamps.

- [ ] **Step 1: Write failing semantic contract tests**

```python
def test_delivery_states_do_not_expose_douyin_draft_box():
    assert "douyin_draft" not in DeliveryState.__members__
    assert DeliveryState.JIANYING_DRAFT.value == "jianying_draft"
```

- [ ] **Step 2: Run the test**

Run: `pytest services/control-plane/tests/test_delivery_states.py -v`

Expected: FAIL because the explicit delivery state contract is missing.

- [ ] **Step 3: Implement state persistence and UI copy**

Persist the provider item ID, delivery visibility, submitted time, and last status. Change all copy from “抖音草稿箱” to the precise destination.

- [ ] **Step 4: Run delivery tests**

Run: `pytest services/control-plane/tests/test_delivery_states.py services/control-plane/tests/test_jianying_drafts.py -v`

Expected: PASS with existing Jianying behavior retained.

### Task 2: Official Douyin Upload/Create Adapter

**Files:**
- Create: `services/control-plane/app/adapters/douyin_publish.py`
- Create: `services/control-plane/app/services/douyin_delivery_service.py`
- Modify: `services/control-plane/app/services/integration_service.py`
- Modify: `services/control-plane/app/main.py`
- Modify: `.env.example`
- Test: `services/control-plane/tests/test_douyin_publish_adapter.py`

**Interfaces:**
- Produces: `upload_video(path, access_token) -> video_id` and `create_video(video_id, title, private_status, access_token) -> item_id`.

- [ ] **Step 1: Write failing upload/create tests**

```python
def test_private_delivery_uses_private_status_one(fake_transport, sample_mp4):
    service = DouyinDeliveryService(transport=fake_transport)
    result = service.deliver(sample_mp4, title="宠物梳毛", visibility="self")
    assert result.request_payload["video"]["private_status"] == 1
```

- [ ] **Step 2: Run the test**

Run: `pytest services/control-plane/tests/test_douyin_publish_adapter.py -v`

Expected: FAIL because the adapter is absent.

- [ ] **Step 3: Implement official API flow**

Validate token presence, upload the rendered MP4, create the video with the requested visibility, persist `item_id`, and convert API error codes into actionable diagnostics. Do not store the access token in task records.

- [ ] **Step 4: Expose readiness and delivery endpoint**

Add `POST /api/tasks/{task_id}/deliver/douyin` and return `not_configured`, `oauth_required`, `permission_required`, or the precise provider result.

- [ ] **Step 5: Run mocked adapter and endpoint tests**

Run: `pytest services/control-plane/tests/test_douyin_publish_adapter.py services/control-plane/tests/test_delivery_api.py -v`

Expected: PASS without publishing a live video.

### Task 3: Jianying Local Handoff Verification

**Files:**
- Modify: `connectors/jianying-local/README.md`
- Modify: `services/control-plane/tests/test_jianying_drafts.py`
- Create: `scripts/verify_jianying_handoff.ps1`

**Interfaces:**
- Produces: a script that resolves the configured draft directory, verifies `draft_content.json`, source files, and preview metadata, then prints the exact local draft path.

- [ ] **Step 1: Write a failing fixture verification test**

```python
def test_jianying_draft_contains_resolvable_media_paths(jianying_draft):
    for path in jianying_draft.media_paths:
        assert Path(path).exists()
```

- [ ] **Step 2: Run the test**

Run: `pytest services/control-plane/tests/test_jianying_drafts.py -v`

Expected: FAIL on any unresolved or stale media path.

- [ ] **Step 3: Harden draft generation and verifier**

Use absolute Windows paths, validate every referenced file before marking `jianying_draft`, and print a concise recovery instruction if Jianying moved its draft directory.

- [ ] **Step 4: Verify against a real generated task**

Run: `powershell -ExecutionPolicy Bypass -File scripts/verify_jianying_handoff.ps1 -TaskId 3c4bf267-77ad-4dac-9a85-5ee8a25ddbd3`

Expected: exit code 0 and a valid draft directory path.

### Task 4: Production Deployment Package

**Files:**
- Modify: `deploy/docker-compose.yml`
- Create: `deploy/docker-compose.production.yml`
- Create: `deploy/Caddyfile`
- Create: `deploy/.env.production.example`
- Create: `scripts/deploy_server.ps1`
- Create: `scripts/backup_server.ps1`
- Create: `docs/deployment.md`
- Test: `services/control-plane/tests/test_deployment_contract.py`

**Interfaces:**
- Produces: `docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.production.yml up -d` deployment with health checks and persistent data.

- [ ] **Step 1: Write failing deployment contract tests**

```python
def test_production_compose_has_healthchecks_and_persistent_volumes():
    compose = yaml.safe_load(Path("deploy/docker-compose.production.yml").read_text())
    assert compose["services"]["control-plane"]["healthcheck"]
    assert compose["volumes"]
```

- [ ] **Step 2: Run the contract test**

Run: `pytest services/control-plane/tests/test_deployment_contract.py -v`

Expected: FAIL because the production overlay is absent.

- [ ] **Step 3: Implement production overlay and reverse proxy**

Add restart policies, health checks, persistent volumes, localhost-only internal ports, reverse-proxy TLS, log limits, and environment validation. Keep Jianying out of server containers.

- [ ] **Step 4: Add deterministic deploy and backup scripts**

The deploy script must validate the remote host and project directory before copying; the backup script must timestamp database/config/data archives and verify the archive can be listed.

- [ ] **Step 5: Validate deployment configuration locally**

Run: `docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.production.yml config`

Expected: exit code 0 with no unresolved required variables after using the example environment file.

### Task 5: Final System Verification and User-Only Checklist

**Files:**
- Modify: `README.md`
- Modify: `docs/progress.md`
- Create: `docs/user-required-actions.md`

**Interfaces:**
- Produces: one canonical “what works now / what only the user can authorize” handoff.

- [ ] **Step 1: Run the complete automated suite**

Run: `pytest services/control-plane/tests -q`

Expected: zero failures.

- [ ] **Step 2: Validate static JavaScript and compose**

Run: `node --check services/control-plane/app/static/app.js; node --check services/control-plane/app/static/review.js; docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.production.yml config`

Expected: all commands exit 0.

- [ ] **Step 3: Run one end-to-end local production task**

Create a task from an authorized local video, run analysis/render/quality checks, verify preview playback, and verify either a valid Jianying draft or a precise not-configured Douyin diagnostic.

- [ ] **Step 4: Write the user-only action list**

List only server purchase/SSH, platform application and OAuth, merchant authorization, provider API keys/model endpoints, and optional DNS/filing. Every item must include the exact page or configuration field and the system check that turns green afterward.

- [ ] **Step 5: Review the design acceptance criteria**

Map every criterion in `docs/superpowers/specs/2026-08-21-video-workbench-closure-design.md` to fresh test or runtime evidence and record any external-credential limitation as `Open`, not `Complete`.
