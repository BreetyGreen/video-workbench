# Automated Course Editing Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a complete 9:16 video from a course recipe and authorized material shots, pass quality gates, and automatically produce the delivery package without a manual review requirement.

**Architecture:** A job planner freezes recipe version, brief, rights mode, and selected shot evidence into a job manifest. Existing timeline, caption, audio, render, quality, and draft services execute from that manifest; successful jobs move directly to delivery while failed quality gates remain blocked with actionable diagnostics.

**Tech Stack:** FastAPI, SQLModel, ffmpeg, ASS/SRT, pyJianYingDraft, pytest

## Global Constraints

- Commercial jobs use only `commercial_authorized` material shots.
- Each selected timeline segment must record source asset ID, shot ID, score, and selection reason.
- Output defaults to 1080x1920 H.264/AAC with duration driven by the job brief.
- Quality failures never auto-deliver.
- Manual review is optional, not required for a passing job.
- MP4, captions, manifest, and Jianying draft are generated from the same frozen timeline.

---

### Task 1: Edit job and manifest models

**Files:**
- Modify: `services/control-plane/app/models.py`
- Create: `services/control-plane/app/schemas/course_jobs.py`
- Test: `services/control-plane/tests/test_course_job_models.py`

**Interfaces:**
- Produces: `CourseEditJob`, `CourseEditJobState`, `CourseEditManifest`

- [ ] **Step 1: Write failing model tests** for immutable recipe version, brief JSON, selected shot evidence JSON, timestamps, error code, and delivery state.
- [ ] **Step 2: Run** `uv run --project services/control-plane pytest services/control-plane/tests/test_course_job_models.py -q`; expect missing models.
- [ ] **Step 3: Implement models and schemas** with explicit state values `queued, planning, rendering, quality_check, delivering, completed, failed`.
- [ ] **Step 4: Re-run tests** and expect PASS.
- [ ] **Step 5: Commit** with `git commit -m "feat: add course edit job model"`.

### Task 2: Recipe-driven shot planner

**Files:**
- Create: `services/control-plane/app/services/course_edit_planner.py`
- Modify: `services/control-plane/app/services/timeline_service.py`
- Test: `services/control-plane/tests/test_course_edit_planner.py`

**Interfaces:**
- Produces: `CourseEditPlanner.plan(job_id: str) -> EditTimeline`
- Consumes: recipe rules and `ShotSearchResult`

- [ ] **Step 1: Write failing planner tests** asserting hook placement in first three seconds, target duration tolerance, shot diversity, no overlap, rights filtering, rule citations, and deterministic output with a fixed seed.
- [ ] **Step 2: Run** `uv run --project services/control-plane pytest services/control-plane/tests/test_course_edit_planner.py -q`; expect missing planner.
- [ ] **Step 3: Implement constrained selection** using search scores, recipe pacing ranges, maximum repeated source duration, and deterministic fallback when fewer shots exist.
- [ ] **Step 4: Re-run tests** and expect PASS.
- [ ] **Step 5: Commit** with `git commit -m "feat: plan edits from course recipes"`.

### Task 3: Automated execution and quality transition

**Files:**
- Create: `services/control-plane/app/services/course_edit_job_service.py`
- Modify: `services/control-plane/app/services/render_service.py`
- Modify: `services/control-plane/app/services/quality_gate_service.py`
- Modify: `services/control-plane/app/services/draft_service.py`
- Test: `services/control-plane/tests/test_course_edit_job_service.py`

**Interfaces:**
- Produces: `CourseEditJobService.run(job_id: str) -> CourseEditJob`

- [ ] **Step 1: Write failing orchestration tests** with fake adapters; assert state order, artifact checksums, same timeline hash in MP4/draft manifests, quality failure blocking, and idempotent retry.
- [ ] **Step 2: Run** `uv run --project services/control-plane pytest services/control-plane/tests/test_course_edit_job_service.py -q`; expect missing service.
- [ ] **Step 3: Implement stateful execution** with atomic manifest writes and durable error codes; preserve current local ASR/TTS fallbacks.
- [ ] **Step 4: Re-run tests** and expect PASS.
- [ ] **Step 5: Commit** with `git commit -m "feat: execute course editing jobs"`.

### Task 4: Job API and no-review delivery behavior

**Files:**
- Modify: `services/control-plane/app/main.py`
- Modify: `services/control-plane/app/templates/workbench.html`
- Modify: `services/control-plane/app/static/workbench.js`
- Test: `services/control-plane/tests/test_course_edit_jobs_api.py`

**Interfaces:**
- Produces: `POST /api/course-edit-jobs`, `GET /api/course-edit-jobs/{job_id}`, `POST /api/course-edit-jobs/{job_id}/retry`

- [ ] **Step 1: Write failing API tests** for create, progress, completed artifacts, blocked quality, retry, and absence of mandatory approval.
- [ ] **Step 2: Run** `uv run --project services/control-plane pytest services/control-plane/tests/test_course_edit_jobs_api.py -q`; expect 404.
- [ ] **Step 3: Implement routes and workbench progress UI**; keep existing review page available for diagnostics but do not gate delivery on approval.
- [ ] **Step 4: Re-run tests** and expect PASS.
- [ ] **Step 5: Commit** with `git commit -m "feat: expose automatic course edit jobs"`.

### Task 5: Real fixture render acceptance

**Files:**
- Create: `scripts/verify-course-editing.py`
- Modify: `scripts/verify.ps1`
- Test: `services/control-plane/tests/test_course_editing_acceptance_contract.py`

**Interfaces:**
- Consumes: course intake, course processing, job APIs
- Produces: verified MP4, SRT/ASS, timeline JSON, quality report, Jianying draft package

- [ ] **Step 1: Write failing contract test** that inspects the verification script and expected artifact list.
- [ ] **Step 2: Run** `uv run --project services/control-plane pytest services/control-plane/tests/test_course_editing_acceptance_contract.py -q`; expect failure.
- [ ] **Step 3: Implement the verifier** to generate legal synthetic media, execute the complete chain, use ffprobe for 1080x1920/audio/duration assertions, and print artifact paths.
- [ ] **Step 4: Run verifier and focused test**; expect exit code 0 and all quality gates passing.
- [ ] **Step 5: Commit** with `git commit -m "test: verify automatic course editing chain"`.

