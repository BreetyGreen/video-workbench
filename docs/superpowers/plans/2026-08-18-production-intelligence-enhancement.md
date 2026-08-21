# Production Intelligence Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add production/local/preview model routing, ByteDance BigASR, reference-video intelligence, and approval-blocking quality gates to the existing video workbench.

**Architecture:** A new per-task settings table persists quality and reference choices. Focused adapters and services enrich the existing media-analysis and timeline contracts while the renderer and Jianying generator remain authoritative. All cloud calls require both configured credentials and per-task consent.

**Tech Stack:** Python 3.11, FastAPI, SQLModel, Pydantic 2, httpx, faster-whisper, FFmpeg, Jinja2, vanilla JavaScript, pytest.

## Global Constraints

- Do not copy AGPL OpenMontage code into the product.
- Never upload task media unless `cloud_processing_allowed` is true.
- `small` is preview/fallback only; production quality prefers BigASR or `large-v3`.
- Reference media never enters the edit timeline.
- Approval must be blocked by failed mechanical quality gates.

---

### Task 1: Persist production settings

**Files:**
- Modify: `services/control-plane/app/models.py`
- Modify: `services/control-plane/app/services/task_service.py`
- Modify: `services/control-plane/app/schemas/__init__.py`
- Modify: `services/control-plane/app/main.py`
- Test: `services/control-plane/tests/test_tasks.py`

**Interfaces:**
- Consumes: existing `create_task(...)` intake path.
- Produces: `TaskProductionSettings` and `VideoTask.quality_profile`, `cloud_processing_allowed`, `reference_path`, `reference_name` properties.

- [ ] Write an API test that posts `quality_profile=local_privacy`, cloud consent, and a reference file, then asserts the task response preserves the profile and reference name.
- [ ] Run the focused test and confirm it fails because the fields are not accepted or returned.
- [ ] Add the one-to-one settings table, safe reference-file storage with SHA-256, request fields, and response fields.
- [ ] Run task tests and confirm they pass.
- [ ] Commit the task with `feat: persist video production profiles`.

### Task 2: Route transcription providers

**Files:**
- Modify: `services/control-plane/app/config.py`
- Modify: `services/control-plane/app/schemas/editing.py`
- Modify: `services/control-plane/app/adapters/transcription.py`
- Modify: `services/control-plane/app/services/media_analysis_service.py`
- Modify: `.env.example`
- Test: `services/control-plane/tests/test_media_analysis.py`

**Interfaces:**
- Consumes: quality profile and cloud consent from `TaskProductionSettings`.
- Produces: `RoutedTranscriber.transcribe(source, *, quality_profile, cloud_processing_allowed) -> TranscriptResult` and `VolcanoBigASRTranscriber.transcribe(source) -> TranscriptResult`.

- [ ] Add failing tests for preview routing, production cloud routing, privacy non-network behavior, official BigASR response parsing, and fallback metadata.
- [ ] Run the focused tests and verify each fails for missing routing behavior.
- [ ] Implement lazy Whisper providers, the official BigASR synchronous request, provider selection, and audited fallback fields.
- [ ] Pass profile and consent through `MediaAnalysisService.analyze`.
- [ ] Run media-analysis tests and confirm they pass.
- [ ] Commit with `feat: route production transcription providers`.

### Task 3: Build reference-video intelligence

**Files:**
- Modify: `services/control-plane/app/schemas/editing.py`
- Create: `services/control-plane/app/services/reference_intelligence_service.py`
- Modify: `services/control-plane/app/services/timeline_service.py`
- Test: `services/control-plane/tests/test_reference_intelligence.py`
- Test: `services/control-plane/tests/test_timeline_service.py`

**Interfaces:**
- Consumes: a separately analyzed `MediaAnalysis`.
- Produces: `ReferenceVideoBrief`, JSON artifact, `preferred_clip_seconds`, and `hook_window_seconds` used by `TimelinePlanner.plan(..., reference_brief=...)`.

- [ ] Add a failing test for a complete five-aspect reference brief and derived pacing values.
- [ ] Add a failing timeline test proving reference pacing changes clip segmentation without importing reference media.
- [ ] Implement the reference schemas and deterministic intelligence service.
- [ ] Integrate the brief into candidate splitting and hook selection.
- [ ] Run both focused suites and confirm they pass.
- [ ] Commit with `feat: guide edits from reference videos`.

### Task 4: Add blocking post-render quality gates

**Files:**
- Create: `services/control-plane/app/services/quality_gate_service.py`
- Modify: `services/control-plane/app/services/review_service.py`
- Modify: `services/control-plane/app/main.py`
- Test: `services/control-plane/tests/test_quality_gates.py`
- Test: `services/control-plane/tests/test_review.py`

**Interfaces:**
- Consumes: rendered preview, timeline, source analyses, caption path, and configured thresholds.
- Produces: `QualityReport` with pass/warn/fail gates and `blocking_failures`.

- [ ] Add failing tests for a passing fixture and for approval rejection when a blocking gate fails.
- [ ] Implement FFprobe/black/silence/caption/timeline gates and JSON persistence.
- [ ] Require a valid passing quality report for approval and expose it as a downloadable artifact.
- [ ] Run quality and review tests and confirm they pass.
- [ ] Commit with `feat: enforce rendered video quality gates`.

### Task 5: Wire the enhanced pipeline and UI

**Files:**
- Modify: `services/control-plane/app/services/pipeline_service.py`
- Modify: `services/control-plane/app/main.py`
- Modify: `services/control-plane/app/templates/workbench.html`
- Modify: `services/control-plane/app/static/workbench.js`
- Modify: `services/control-plane/app/static/workbench.css`
- Modify: `services/control-plane/app/templates/review.html`
- Modify: `services/control-plane/app/static/review.css`
- Modify: `services/control-plane/app/services/review_service.py`
- Test: `services/control-plane/tests/test_pipeline.py`
- Test: `services/control-plane/tests/test_workbench.py`

**Interfaces:**
- Consumes: all previous task services.
- Produces: reference brief and quality report artifacts, model evidence in `review.json`, intake controls, integration status, and review-page gate display.

- [ ] Add failing pipeline/UI assertions for profile controls, model status, reference artifact, quality report, and gate rendering.
- [ ] Wire task settings through analysis, reference intelligence, planning, rendering, gating, and review manifest creation.
- [ ] Add intake controls and quality/provider evidence panels.
- [ ] Run pipeline and workbench tests and confirm they pass.
- [ ] Commit with `feat: expose production intelligence in workbench`.

### Task 6: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/runbook.md`
- Modify: `docs/progress.md`
- Create: `docs/runbooks/volcano-bigasr.md`

**Interfaces:**
- Consumes: completed runtime behavior and environment keys.
- Produces: operator instructions for all three profiles and evidence-backed current state.

- [ ] Document profile behavior, cloud-consent boundary, BigASR configuration, reference upload, quality gates, and fallback evidence.
- [ ] Run the complete control-plane test suite.
- [ ] Run the complete DingTalk connector test suite.
- [ ] Run a real FFmpeg fixture through the enhanced API and inspect all artifacts with ffprobe.
- [ ] Verify the intake and review pages in a browser at desktop and narrow viewport sizes.
- [ ] Confirm `git status`, inspect the final diff, and commit documentation with `docs: operate production intelligence enhancements`.
