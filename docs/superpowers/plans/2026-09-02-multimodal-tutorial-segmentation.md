# Multimodal Tutorial Segmentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and expose evidence-backed tutorial segments that distinguish instructor explanation, editing-software operation, finished-example playback, intro/outro, and unknown footage, then prevent example narration from being misread as editing instructions.

**Architecture:** Reuse the existing `MediaAnalysisService` so one analysis pass provides transcript, scenes, keyframes, and OCR. `TutorialUnderstandingService` converts that evidence into durable `TutorialSegment` rows, applies a deterministic stateful classifier, links nearby finished examples to the preceding instructional rule, and emits rules only from instructional explanation. Course APIs and demo artifacts expose the segment ledger without copying tutorial footage into the edit.

**Tech Stack:** FastAPI, SQLModel, FFmpeg/ffprobe, RapidOCR, existing routed ASR, pytest, Jinja2.

## Global Constraints

- Keep the zero-Key local fallback and reuse the existing routed ASR.
- Never send tutorial media to a new provider without task-level cloud consent.
- Never treat finished-example narration as an editing instruction.
- Persist time ranges, OCR cues, classification confidence, and rule links.
- Do not copy tutorial frames into the final edit; examples are evidence only.
- Add no required configuration fields.
- Follow TDD and preserve existing databases by adding a new table instead of new required columns to existing tables.

---

### Task 1: Durable tutorial segment ledger

**Files:**
- Modify: `services/control-plane/app/models.py`
- Modify: `services/control-plane/app/schemas/course_knowledge.py`
- Test: `services/control-plane/tests/test_tutorial_understanding.py`

**Interfaces:**
- Produces: `TutorialSegmentType`, `TutorialSegment`, and `TutorialSegmentRead`.
- `TutorialSegment` stores recipe/asset IDs, type, transcript/OCR evidence, start/end, confidence, related rule IDs, and ordering.

- [x] Write a failing model/service test that expects persisted `lecture`, `software_operation`, and `finished_example` segments.
- [x] Run the focused test and confirm it fails because the segment contract does not exist.
- [x] Add the new enum, table, and read schema.
- [x] Re-run the focused test.

### Task 2: Evidence-backed stateful classification

**Files:**
- Modify: `services/control-plane/app/services/tutorial_understanding_service.py`
- Modify: `services/control-plane/app/main.py`
- Test: `services/control-plane/tests/test_tutorial_understanding.py`

**Interfaces:**
- Consumes: existing `MediaAnalysisService.analyze(...) -> MediaAnalysis`.
- Produces: persisted segment rows and editing rules sourced only from lecture segments.

- [x] Write a failing test with UI OCR, an example cue, example sales narration, and later instructor explanation.
- [x] Verify the example sales narration currently becomes a rule or no segments exist.
- [x] Add media-analyzer injection, temporal evidence matching, deterministic classification, example-state carry-forward, and nearest-rule linking.
- [x] Keep the transcriber-only path for text tutorials and isolated tests.
- [x] Re-run tutorial-understanding tests.

### Task 3: API and task artifact exposure

**Files:**
- Modify: `services/control-plane/app/schemas/course_knowledge.py`
- Modify: `services/control-plane/app/main.py`
- Modify: `services/control-plane/app/services/tutorial_demo_service.py`
- Modify: `services/control-plane/app/services/review_service.py`
- Test: `services/control-plane/tests/test_course_processing_api.py`
- Test: `services/control-plane/tests/test_tutorial_demo_service.py`

**Interfaces:**
- `EditingRecipeRead.segments` returns the ordered segment ledger.
- Demo task writes `tutorial-segments.json` and includes the same rows in `learned-course-recipe.json`.

- [x] Write failing API/artifact assertions.
- [x] Run them and confirm missing segment output.
- [x] Query and serialize ordered segments; allow the new artifact download.
- [x] Re-run focused tests.

### Task 4: Human-visible evidence and capability truth

**Files:**
- Modify: `services/control-plane/app/templates/review.html`
- Modify: `services/control-plane/app/main.py`
- Modify: `services/control-plane/tests/test_review.py`
- Modify: `services/control-plane/app/capability_catalog.json`
- Modify: `docs/capabilities-and-configuration.md`
- Modify: `docs/codex-operator-guide.md`
- Modify: `docs/progress.md`

**Interfaces:**
- Review page receives `tutorial_segments` parsed from the task artifact and labels each type in Chinese.

- [x] Write a failing review-page assertion for the segment evidence section.
- [x] Render the segment ledger with time ranges, OCR/text evidence, confidence, and linked rules.
- [x] Document the local heuristic boundary and that semantic visual understanding remains a later cloud/local-model enhancement.
- [x] Re-run review tests and syntax checks.

### Task 5: Verification

**Files:**
- No production changes unless verification reveals a regression.

- [x] Run all control-plane tests with the scheduler disabled (`261 passed` on 2026-09-04).
- [x] Run JavaScript syntax checks.
- [ ] Run `python scripts/verify-fresh-clone.py --dry-run` after committing the complete tracked snapshot.
- [x] Run the tutorial demo and inspect segment, rule-trace, comparison, quality, and final media artifacts.
- [x] Record confirmed evidence and remaining Mac/server/user-action boundaries in `docs/progress.md`.
