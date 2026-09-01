# Course Video Learning Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a one-click, zero-key acceptance demo that transcribes a real narrated tutorial video, extracts cited editing rules, applies those rules to separate licensed footage, proves the edit differs from a baseline, renders the final video, and produces a Jianying draft package.

**Architecture:** Extend the existing course-ingestion and timeline pipeline instead of creating a parallel demo renderer. A tutorial-learning service owns transcript evidence and recipe validation; a course-policy compiler converts persisted rules into deterministic timeline constraints; the pipeline renders both baseline and learned timelines and persists a rule trace plus comparison report. A thin demo orchestrator prepares licensed inputs and drives the same production APIs used by ordinary courses.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, FFmpeg/ffprobe, faster-whisper or configured Volcengine ASR, pytest, vanilla JavaScript setup UI, existing Jianying draft and device-delivery services.

## Global Constraints

- Keep the local baseline loopback-only and free of required cloud credentials.
- Never read the bundled tutorial script after the narrated MP4 has been handed to course processing.
- Never label synthetic fallback footage as public or real footage.
- Never overwrite an existing Jianying draft.
- Windows defaults to `%LOCALAPPDATA%\VideoWorkbench`; `B:` remains an explicit local override only.
- Every learned edit decision must cite a persisted rule and tutorial time range.
- A learned timeline with no meaningful difference from the baseline fails closed.
- Use tests first for every behavior change and commit each completed task.

---

### Task 1: Remove the implicit Windows B-drive default

**Files:**
- Modify: `sync-helper/install-windows.ps1`
- Modify: `services/control-plane/tests/test_sync_helper_packaging.py`
- Modify: `docs/codex-operator-guide.md`
- Modify: `docs/capabilities-and-configuration.md`

- [ ] **Step 1: Add a failing packaging assertion**

Add a test that reads `install-windows.ps1` and asserts the default install root is `LOCALAPPDATA`, no `Test-Path 'B:\'` branch exists, and explicit `InstallDir`/`DataDir` parameters remain supported.

- [ ] **Step 2: Run the focused test and confirm the expected failure**

Run:

```powershell
$env:VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED='false'
services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests/test_sync_helper_packaging.py -q
```

Expected: failure naming the implicit `B:\` preference.

- [ ] **Step 3: Change the installer default and documentation**

Set the default install directory under `$env:LOCALAPPDATA\VideoWorkbench`, preserve explicit parameters, and document that another drive is a user-selected override.

- [ ] **Step 4: Re-run the focused test**

Expected: all sync-helper packaging tests pass.

- [ ] **Step 5: Commit**

```powershell
git add sync-helper/install-windows.ps1 services/control-plane/tests/test_sync_helper_packaging.py docs/codex-operator-guide.md docs/capabilities-and-configuration.md
git commit -m "fix: make Windows runtime path portable"
```

### Task 2: Persist tutorial evidence and transcribe video assets

**Files:**
- Modify: `services/control-plane/app/models.py`
- Modify: `services/control-plane/app/db.py`
- Modify: `services/control-plane/app/schemas/course_knowledge.py`
- Modify: `services/control-plane/app/services/tutorial_understanding_service.py`
- Modify: `services/control-plane/app/main.py`
- Modify: `services/control-plane/tests/test_tutorial_understanding.py`
- Modify: `services/control-plane/tests/test_course_api.py`

- [ ] **Step 1: Write failing evidence and video-ASR tests**

Cover a tutorial MP4 processed through a fake routed transcriber, transcript SHA-256 persistence, evidence text/time ranges, confidence bounds, unknown categories, empty evidence, and evidence ranges beyond the transcript duration. Assert that the parser receives the ASR result and cannot read a source script path.

- [ ] **Step 2: Run focused tests and observe failure**

Run:

```powershell
$env:VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED='false'
services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests/test_tutorial_understanding.py services/control-plane/tests/test_course_api.py -q
```

Expected: missing evidence fields and missing video transcriber wiring.

- [ ] **Step 3: Add backward-compatible database fields**

Add recipe-level tutorial asset/transcript hash fields and rule-level evidence text/confidence fields. Extend the idempotent SQLite migration in `db.py` so existing installations upgrade without data loss.

- [ ] **Step 4: Implement routed transcription and validation**

Accept the existing media-analysis transcriber, transcribe audio/video with task privacy settings, hash the normalized transcript, persist timestamped evidence, and reject invalid rules. Text tutorial assets remain supported but are explicitly marked as text evidence.

- [ ] **Step 5: Wire the production transcriber in app startup**

Construct `TutorialUnderstandingService` with the same routed transcriber used by `PipelineService`; do not create a second cloud configuration path.

- [ ] **Step 6: Re-run tests and commit**

```powershell
git add services/control-plane/app services/control-plane/tests/test_tutorial_understanding.py services/control-plane/tests/test_course_api.py
git commit -m "feat: learn cited rules from tutorial video audio"
```

### Task 3: Compile course rules into timeline policy and proof

**Files:**
- Create: `services/control-plane/app/services/course_recipe_service.py`
- Modify: `services/control-plane/app/schemas/editing.py`
- Modify: `services/control-plane/app/services/timeline_service.py`
- Modify: `services/control-plane/app/services/pipeline_service.py`
- Modify: `services/control-plane/app/services/course_edit_job_service.py`
- Modify: `services/control-plane/app/models.py`
- Modify: `services/control-plane/app/db.py`
- Create: `services/control-plane/tests/test_course_recipe_service.py`
- Modify: `services/control-plane/tests/test_timeline_service.py`
- Modify: `services/control-plane/tests/test_course_edit_job_service.py`

- [ ] **Step 1: Write failing policy, trace, and comparison tests**

Using the same analyzed shots, assert that the learned policy changes at least two of hook position, average clip length, problem/solution ordering, and CTA ending. Assert every `rule_trace` entry references an existing persisted rule and copied tutorial evidence. Assert an unchanged learned plan raises `course_rules_not_applied`.

- [ ] **Step 2: Run focused tests and observe failure**

Run:

```powershell
$env:VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED='false'
services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests/test_course_recipe_service.py services/control-plane/tests/test_timeline_service.py services/control-plane/tests/test_course_edit_job_service.py -q
```

- [ ] **Step 3: Implement a deterministic course-policy compiler**

Compile persisted hook, pacing, structure, close-up, comparison, caption, audio, and CTA rules into a typed local policy. Do not require Dify. Reject unsupported rules before planning.

- [ ] **Step 4: Carry recipe identity through a video task**

Add a nullable `course_recipe_id` to `VideoTask`; set it in `CourseEditJobService`. In `PipelineService`, load and validate the exact recipe version used by the job.

- [ ] **Step 5: Generate baseline, learned timeline, trace, and comparison**

Plan once without policy and once with policy. Persist `baseline-timeline.json`, `course-rule-trace.json`, and `course-comparison.json`. Render only the learned timeline after the comparison quality gate succeeds.

- [ ] **Step 6: Re-run tests and commit**

```powershell
git add services/control-plane/app services/control-plane/tests
git commit -m "feat: prove learned course rules affect editing"
```

### Task 4: Prepare auditable tutorial and licensed demo footage

**Files:**
- Create: `services/control-plane/app/demo/tutorial-learning-manifest.json`
- Create: `services/control-plane/app/demo/tutorial-script.json`
- Create: `services/control-plane/app/services/tutorial_demo_assets.py`
- Create: `services/control-plane/tests/test_tutorial_demo_assets.py`

- [ ] **Step 1: Write failing manifest and downloader tests**

Validate file page URL, redirect download URL, author, license identifier, license URL, attribution requirement, media type, duration bounds, expected SHA-256 when pinned, and explicit `synthetic_fallback` records. Use an in-process fake HTTP transport; unit tests must not depend on the network.

- [ ] **Step 2: Run the focused test and observe failure**

Run:

```powershell
services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests/test_tutorial_demo_assets.py -q
```

- [ ] **Step 3: Implement the asset preparer**

Download bounded Wikimedia Commons footage, verify it with ffprobe, compute SHA-256, and write `rights-ledger.json`. On failure, use FFmpeg to generate visibly labeled synthetic pet-care shots and record the original failure reason.

- [ ] **Step 4: Generate a narrated tutorial MP4**

Generate narration through configured TTS, platform speech, or the bundled regenerable narration asset; combine it with tutorial cards using FFmpeg. Return only the MP4 path to course processing. Persist preparation provenance separately from learned ASR artifacts.

- [ ] **Step 5: Re-run tests and commit**

```powershell
git add services/control-plane/app/demo services/control-plane/app/services/tutorial_demo_assets.py services/control-plane/tests/test_tutorial_demo_assets.py
git commit -m "feat: prepare auditable tutorial demo media"
```

### Task 5: Add the one-click demo orchestrator and UI

**Files:**
- Create: `services/control-plane/app/services/tutorial_demo_service.py`
- Modify: `services/control-plane/app/main.py`
- Modify: `services/control-plane/app/static/setup.js`
- Modify: `services/control-plane/app/templates/setup.html`
- Create: `services/control-plane/tests/test_tutorial_demo_service.py`
- Modify: `services/control-plane/tests/test_setup_page.py`

- [ ] **Step 1: Write failing service, API, and UI tests**

Assert `POST /api/tutorial-learning-demo` creates an isolated demo course and returns a run identifier; `GET /api/tutorial-learning-demo/{id}` exposes stage, failure code, evidence links, task/review link, and Jianying handoff state. Assert the setup page includes a non-mandatory “运行完整教学演示” control and polling behavior.

- [ ] **Step 2: Run the focused tests and observe failure**

Run:

```powershell
$env:VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED='false'
services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests/test_tutorial_demo_service.py services/control-plane/tests/test_setup_page.py -q
```

- [ ] **Step 3: Implement orchestration using production services**

Prepare the tutorial and footage, create course assets and source records, process the tutorial, create a course edit job, wait for the production pipeline, and expose all acceptance artifacts. Persist stages so a browser refresh does not lose state.

- [ ] **Step 4: Implement the first-run entry and result panel**

Add one optional button with progress, explicit local/cloud provider labels, tutorial transcript and rules links, baseline comparison link, final video link, and Jianying delivery action/state.

- [ ] **Step 5: Re-run tests and commit**

```powershell
git add services/control-plane/app services/control-plane/tests
git commit -m "feat: add one-click tutorial learning demo"
```

### Task 6: Run the real acceptance flow and update operator truth

**Files:**
- Modify: `README.md`
- Modify: `docs/codex-operator-guide.md`
- Modify: `docs/capabilities-and-configuration.md`
- Modify: `docs/progress.md`
- Modify: `services/control-plane/app/capability_catalog.json`

- [ ] **Step 1: Run the real demo on the development machine**

Start the control plane, invoke the one-click endpoint, and wait for completion. Use the actual narrated tutorial MP4, actual ASR path, separate licensed or explicitly synthetic fallback footage, the production timeline planner, renderer, caption generator, quality gate, and Jianying handoff.

- [ ] **Step 2: Inspect acceptance artifacts**

Verify with ffprobe that the tutorial and result have video/audio streams and expected duration. Inspect transcript timestamps, recipe evidence, rule trace, comparison report, rights ledger, subtitles, quality report, and draft ZIP. Confirm the learned timeline differs in at least two asserted dimensions.

- [ ] **Step 3: Exercise Jianying delivery when available**

Use discovery and import through the existing sync helper. Record `imported`, `client_opened`, `not_installed`, or `needs_one_time_path_selection` truthfully; do not report a ZIP download as automatic import.

- [ ] **Step 4: Run all repository verification**

Run:

```powershell
$env:VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED='false'
services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests -q
node --check services/control-plane/app/static/workbench.js
node --check services/control-plane/app/static/setup.js
python scripts/doctor.py
```

Expected: tests pass, JavaScript parses, doctor reports a usable local baseline or precise optional-provider warnings.

- [ ] **Step 5: Update documentation and commit**

Document the exact one-click route, artifacts, provider used in the real run, offline fallback behavior, current Jianying state, and remaining external-user actions. Keep Confirmed, Open, and External User Action separate.

```powershell
git add README.md docs services/control-plane/app/capability_catalog.json
git commit -m "docs: publish tutorial learning acceptance evidence"
```
