# Automated Video Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a local, UI-backed video production system that accepts materials, analyzes tutorials and trends, produces editable Jianying drafts and MP4 previews, and stops at a human approval gate before publishing.

**Architecture:** Run ArcReel as the production UI, add a focused FastAPI control plane for task state and connectors, use Dify DSL workflows for tutorial and viral analysis, and isolate Jianying/FFmpeg execution behind adapters. Persist all task artifacts locally and make every external credential optional but explicitly observable.

**Tech Stack:** Docker Compose, ArcReel v0.26.0, Python 3.11, FastAPI, SQLModel/SQLite, Pydantic, pytest, Dify 1.16.x DSL, pyJianYingDraft 0.3.0, FFmpeg, DingTalk Stream SDK.

## Global Constraints

- All project files stay under `B:/xiaozhu/全自动视频发布`; do not modify the existing parent website.
- Pin third-party container and Python dependency versions; do not use `latest` in production compose files.
- Do not store API keys, DingTalk secrets, OAuth tokens, browser cookies, or generated passwords in Git.
- Publishing is human-gated; no browser-Cookie unattended publish path is allowed.
- New files are UTF-8, and Windows PowerShell commands must use literal paths for Chinese directories.
- Every task must leave a testable deliverable and update `docs/progress.md` when its state changes.

---

### Task 1: Reproducible ArcReel deployment

**Files:**
- Create: `deploy/arcreel/compose.yml`
- Create: `deploy/arcreel/.env.example`
- Create: `deploy/arcreel/README.md`
- Create: `scripts/start-arcreel.ps1`
- Create: `scripts/verify-arcreel.ps1`

**Interfaces:**
- Consumes: Docker Engine 29+ and Docker Compose v2+.
- Produces: ArcReel HTTP health endpoint at `http://127.0.0.1:1241/health` and persistent directories under `data/arcreel/`.

- [ ] **Step 1: Write the deployment verifier**

```powershell
$response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:1241/health' -TimeoutSec 10
if ($response.StatusCode -ne 200) { throw "ArcReel health check failed" }
```

- [ ] **Step 2: Run the verifier before deployment**

Run: `powershell -ExecutionPolicy Bypass -File scripts/verify-arcreel.ps1`
Expected: FAIL because port 1241 has no ArcReel service.

- [ ] **Step 3: Create pinned Compose and startup script**

The Compose file must mount `.env`, `data/arcreel/projects`, `data/arcreel/logs`, `data/arcreel/vertex_keys`, and `data/arcreel/claude_data`, expose `127.0.0.1:1241:1241`, and use `ghcr.io/arcreel/arcreel:v0.26.0` after verifying the manifest tag.

- [ ] **Step 4: Start and verify ArcReel**

Run: `powershell -ExecutionPolicy Bypass -File scripts/start-arcreel.ps1`
Run: `powershell -ExecutionPolicy Bypass -File scripts/verify-arcreel.ps1`
Expected: container healthy, HTTP 200, and login page reachable.

- [ ] **Step 5: Commit the deployment milestone**

```powershell
git add -- '全自动视频发布/deploy/arcreel' '全自动视频发布/scripts'
git commit -m "feat: add reproducible ArcReel deployment"
```

### Task 2: Task control plane and durable state

**Files:**
- Create: `services/control-plane/pyproject.toml`
- Create: `services/control-plane/app/main.py`
- Create: `services/control-plane/app/config.py`
- Create: `services/control-plane/app/db.py`
- Create: `services/control-plane/app/models.py`
- Create: `services/control-plane/app/schemas.py`
- Create: `services/control-plane/app/services/task_service.py`
- Create: `services/control-plane/tests/test_tasks.py`

**Interfaces:**
- Consumes: multipart upload with `title`, `content_type`, `rights_confirmed`, and one or more files.
- Produces: `POST /api/tasks`, `GET /api/tasks/{task_id}`, `POST /api/tasks/{task_id}/review`, and `GET /health`.

- [ ] **Step 1: Write failing API tests**

```python
def test_create_task_persists_safe_material(client):
    response = client.post(
        "/api/tasks",
        data={"title": "demo", "content_type": "pet", "rights_confirmed": "true"},
        files=[("files", ("raw.mp4", b"video", "video/mp4"))],
    )
    assert response.status_code == 201
    task = response.json()
    assert task["status"] == "received"
    assert task["materials"][0]["original_name"] == "raw.mp4"
    assert "raw.mp4" not in task["materials"][0]["stored_path"]
```

- [ ] **Step 2: Run the failing test**

Run: `python -m pytest services/control-plane/tests/test_tasks.py -q`
Expected: FAIL because the application package does not exist.

- [ ] **Step 3: Implement models and API**

Define `TaskStatus` with `received`, `analyzing`, `planning`, `editing`, `reviewing`, `changes_requested`, `approved`, `delivered`, and `failed`. Store task and material records in SQLite, use UUID storage names, calculate SHA-256, and reject approval when `rights_confirmed` is false.

- [ ] **Step 4: Run focused and full tests**

Run: `python -m pytest services/control-plane/tests/test_tasks.py -q`
Expected: all task API tests pass.

- [ ] **Step 5: Commit the control-plane milestone**

```powershell
git add -- '全自动视频发布/services/control-plane'
git commit -m "feat: add durable video task control plane"
```

### Task 3: FFmpeg preview and mechanical quality checks

**Files:**
- Create: `services/control-plane/app/adapters/ffmpeg.py`
- Create: `services/control-plane/app/services/preview_service.py`
- Create: `services/control-plane/tests/test_ffmpeg.py`
- Create: `fixtures/media/generate-fixture.ps1`

**Interfaces:**
- Consumes: task material paths constrained to the task artifact root.
- Produces: `preview.mp4`, `preview.json`, duration, resolution, stream presence, black-frame warnings, and silence warnings.

- [ ] **Step 1: Generate a deterministic test clip and write failing tests**

```python
def test_probe_reports_video_and_audio(ffmpeg_fixture):
    report = probe_media(ffmpeg_fixture)
    assert report.video_streams == 1
    assert report.audio_streams == 1
    assert report.duration_seconds > 1
```

- [ ] **Step 2: Verify the test fails before implementation**

Run: `python -m pytest services/control-plane/tests/test_ffmpeg.py -q`
Expected: FAIL because `probe_media` is missing.

- [ ] **Step 3: Implement subprocess argument-list adapters**

Use `subprocess.run([...], check=True, capture_output=True, text=True)` with no shell interpolation. Parse `ffprobe -of json`, generate a normalized H.264/AAC preview, and store the exact command argument array with secrets removed.

- [ ] **Step 4: Verify preview and QA**

Run: `python -m pytest services/control-plane/tests/test_ffmpeg.py -q`
Expected: deterministic fixture passes probe and preview assertions.

- [ ] **Step 5: Commit the media milestone**

```powershell
git add -- '全自动视频发布/services/control-plane' '全自动视频发布/fixtures/media'
git commit -m "feat: add FFmpeg previews and media QA"
```

### Task 4: Jianying draft adapter

**Files:**
- Create: `services/control-plane/app/adapters/jianying.py`
- Create: `services/control-plane/app/services/draft_service.py`
- Create: `services/control-plane/tests/test_jianying.py`
- Create: `scripts/detect-jianying.ps1`

**Interfaces:**
- Consumes: ordered video/audio/text segments with microsecond ranges.
- Produces: a draft directory and ZIP containing `draft_info.json` or `draft_content.json`, plus a compatibility report.

- [ ] **Step 1: Write a failing draft package test**

```python
def test_build_draft_zip_contains_editable_tracks(tmp_path, sample_plan):
    package = build_draft(sample_plan, tmp_path / "drafts", target="6+")
    assert package.zip_path.exists()
    assert package.track_counts == {"video": 1, "audio": 1, "text": 1}
```

- [ ] **Step 2: Verify the draft test fails**

Run: `python -m pytest services/control-plane/tests/test_jianying.py -q`
Expected: FAIL because the adapter is missing.

- [ ] **Step 3: Implement the adapter on pyJianYingDraft 0.3.0**

Build a 1080x1920 draft from a typed `EditPlan`; copy materials into a task-owned assets folder; choose `draft_info.json` for `6+`; reject paths outside the task root; include a report field `opened_in_local_jianying` defaulting to false until inspected.

- [ ] **Step 4: Verify package structure**

Run: `python -m pytest services/control-plane/tests/test_jianying.py -q`
Expected: ZIP structure, track counts, safe paths, and compatibility report pass.

- [ ] **Step 5: Commit the draft milestone**

```powershell
git add -- '全自动视频发布/services/control-plane' '全自动视频发布/scripts/detect-jianying.ps1'
git commit -m "feat: generate editable Jianying draft packages"
```

### Task 5: Dify workflow definitions and client

**Files:**
- Create: `workflows/dify/tutorial-analysis.yml`
- Create: `workflows/dify/viral-analysis.yml`
- Create: `services/control-plane/app/adapters/dify.py`
- Create: `services/control-plane/app/schemas/analysis.py`
- Create: `services/control-plane/tests/test_dify.py`
- Create: `docs/runbooks/dify.md`

**Interfaces:**
- Consumes: transcript, tutorial text, sampled-frame descriptions, content category, and trend records.
- Produces: validated `EditRecipe`, `ViralAnalysis`, and three `PublishCopy` alternatives.

- [ ] **Step 1: Write schema and mocked-client failure tests**

```python
def test_invalid_dify_json_fails_with_raw_response(mock_transport):
    mock_transport.reply(200, {"data": {"outputs": {"text": "not-json"}}})
    with pytest.raises(AnalysisOutputError) as error:
        DifyClient(settings()).analyze_tutorial({"text": "tutorial"})
    assert error.value.raw_response == "not-json"
```

- [ ] **Step 2: Run the test before implementing the client**

Run: `python -m pytest services/control-plane/tests/test_dify.py -q`
Expected: FAIL because the client and schemas are missing.

- [ ] **Step 3: Implement versioned DSL and typed client**

The tutorial workflow returns hook rules, duration, pacing, track layout, caption style, audio rules, prohibited elements, and QA thresholds. The viral workflow separates public metrics from owner-authorized metrics and returns evidence strings for each recommendation.

- [ ] **Step 4: Verify configured and unconfigured states**

Run: `python -m pytest services/control-plane/tests/test_dify.py -q`
Expected: mocked success validates typed output; malformed output fails; missing API key reports `not_configured`.

- [ ] **Step 5: Commit the AI milestone**

```powershell
git add -- '全自动视频发布/workflows/dify' '全自动视频发布/services/control-plane' '全自动视频发布/docs/runbooks/dify.md'
git commit -m "feat: add versioned Dify analysis workflows"
```

### Task 6: DingTalk Stream intake

**Files:**
- Create: `connectors/dingtalk/pyproject.toml`
- Create: `connectors/dingtalk/dingtalk_connector/main.py`
- Create: `connectors/dingtalk/dingtalk_connector/downloader.py`
- Create: `connectors/dingtalk/tests/test_intake.py`
- Create: `docs/runbooks/dingtalk.md`

**Interfaces:**
- Consumes: official DingTalk Stream bot message callbacks and official file download metadata.
- Produces: calls to `POST /api/tasks` with downloaded files, source user, source conversation, message id, and deduplication key.

- [ ] **Step 1: Write failing callback and deduplication tests**

```python
def test_duplicate_message_creates_one_task(connector, control_plane):
    event = fixture_file_message(message_id="m-1")
    connector.handle(event)
    connector.handle(event)
    assert control_plane.created_task_count == 1
```

- [ ] **Step 2: Run the connector tests before implementation**

Run: `python -m pytest connectors/dingtalk/tests/test_intake.py -q`
Expected: FAIL because the connector package is missing.

- [ ] **Step 3: Implement official SDK adapter**

Read `DINGTALK_CLIENT_ID` and `DINGTALK_CLIENT_SECRET` from the environment, download only accepted media/document MIME types, enforce the configured size limit, calculate SHA-256, and acknowledge messages without exposing secrets.

- [ ] **Step 4: Verify fixture and not-configured behavior**

Run: `python -m pytest connectors/dingtalk/tests/test_intake.py -q`
Expected: deduplication, MIME rejection, size rejection, and missing-credential status pass.

- [ ] **Step 5: Commit the connector milestone**

```powershell
git add -- '全自动视频发布/connectors/dingtalk' '全自动视频发布/docs/runbooks/dingtalk.md'
git commit -m "feat: add DingTalk Stream material intake"
```

### Task 7: Review package and human approval gate

**Files:**
- Create: `services/control-plane/app/services/review_service.py`
- Create: `services/control-plane/app/templates/review.html`
- Create: `services/control-plane/app/static/review.css`
- Create: `services/control-plane/tests/test_review.py`

**Interfaces:**
- Consumes: preview, draft package, analysis output, publish copy, rights status, and AIGC declaration.
- Produces: browser review page, approval audit record, change request, and downloadable manifest.

- [ ] **Step 1: Write approval-gate tests**

```python
def test_approval_requires_rights_and_required_artifacts(client, review_task):
    review_task.rights_confirmed = False
    response = client.post(f"/api/tasks/{review_task.id}/review", json={"decision": "approve"})
    assert response.status_code == 409
    assert response.json()["code"] == "rights_not_confirmed"
```

- [ ] **Step 2: Verify tests fail before implementation**

Run: `python -m pytest services/control-plane/tests/test_review.py -q`
Expected: FAIL because review routes and templates are missing.

- [ ] **Step 3: Implement review page and manifest**

Display the MP4, draft link, cover, three copy/topic variants, source/evidence list, AIGC declaration, rights status, and warnings. Approval must be a POST action and write an immutable audit event.

- [ ] **Step 4: Verify review workflow**

Run: `python -m pytest services/control-plane/tests/test_review.py -q`
Expected: approval, rejection, missing-rights, missing-artifact, and audit assertions pass.

- [ ] **Step 5: Commit the review milestone**

```powershell
git add -- '全自动视频发布/services/control-plane'
git commit -m "feat: add human-gated video review packages"
```

### Task 8: Unified deployment and end-to-end verification

**Files:**
- Create: `deploy/compose.yml`
- Create: `.env.example`
- Create: `scripts/start.ps1`
- Create: `scripts/stop.ps1`
- Create: `scripts/verify.ps1`
- Create: `docs/runbook.md`
- Modify: `README.md`
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: Docker, FFmpeg, optional Dify and DingTalk credentials.
- Produces: one start command, one verification command, local URLs, test report, and current-state handoff.

- [ ] **Step 1: Write the end-to-end verifier**

The verifier checks Docker services, ArcReel health, control-plane health, task creation, deterministic fixture preview, Jianying ZIP structure, review page HTTP 200, and explicit `not_configured` states for missing external credentials.

- [ ] **Step 2: Verify failure before the unified deployment exists**

Run: `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`
Expected: FAIL with the first missing service or artifact.

- [ ] **Step 3: Implement Compose and runbook**

Expose services only on `127.0.0.1`, persist all data under `data/`, and document exact start, stop, backup, restore, upgrade, credential, and troubleshooting commands.

- [ ] **Step 4: Run the full acceptance suite**

Run: `python -m pytest services/control-plane/tests connectors/dingtalk/tests -q`
Run: `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`
Expected: all local tests pass; ArcReel and control plane are healthy; sample review package exists; unconfigured external services are reported honestly.

- [ ] **Step 5: Commit the verified system state**

```powershell
git add -- '全自动视频发布'
git commit -m "feat: deliver local automated video workbench"
```
