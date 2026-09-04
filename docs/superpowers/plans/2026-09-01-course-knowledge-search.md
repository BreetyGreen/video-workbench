# Course Knowledge and Material Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn ingested tutorials and course materials into cited editing recipes and a shot-level, rights-aware searchable material library.

**Architecture:** A course processor dispatches by asset role. Tutorial assets are transcribed/OCRed and transformed into structured recipe rules with source timecodes; material videos are split into shots and enriched with deterministic metadata first, with optional cloud embeddings behind an adapter.

**Tech Stack:** Python 3.11, FastAPI, SQLModel, ffmpeg/ffprobe, faster-whisper, RapidOCR, NumPy-compatible vector JSON, pytest

## Global Constraints

- Every extracted editing rule must retain a tutorial asset ID and time range or page number.
- Local processing is the default; cloud processing requires explicit task consent and configured credentials.
- Shot records must keep original media provenance and rights status.
- Commercial search excludes `unknown` and `personal_learning` assets.
- No face identity recognition; person detection is limited to anonymous presence/count/framing attributes.
- Similarity results must distinguish perceptual duplicate scores from semantic relevance scores.

---

### Task 1: Recipe and shot models

**Files:**
- Modify: `services/control-plane/app/models.py`
- Create: `services/control-plane/app/schemas/course_knowledge.py`
- Test: `services/control-plane/tests/test_course_knowledge_models.py`

**Interfaces:**
- Produces: `EditingRecipe`, `EditingRule`, `MaterialShot`, `CourseProcessingRun`

- [ ] **Step 1: Write failing model tests** for recipe versioning, cited rule ordering, shot time ranges, pHash, tags JSON, embedding JSON, and processing-run state transitions.
- [ ] **Step 2: Run** `uv run --project services/control-plane pytest services/control-plane/tests/test_course_knowledge_models.py -q`; expect missing models.
- [ ] **Step 3: Implement the four typed models** with foreign keys, indexes on course/asset/status, and a unique `(asset_id, start_ms, end_ms)` shot constraint.
- [ ] **Step 4: Re-run the focused tests** and expect PASS.
- [ ] **Step 5: Commit** with `git commit -m "feat: add course recipe and shot models"`.

### Task 2: Tutorial understanding pipeline

**Files:**
- Create: `services/control-plane/app/services/tutorial_understanding_service.py`
- Modify: `services/control-plane/app/adapters/transcription.py`
- Modify: `services/control-plane/app/adapters/dify.py`
- Test: `services/control-plane/tests/test_tutorial_understanding.py`

**Interfaces:**
- Produces: `TutorialUnderstandingService.process(course_id: str) -> EditingRecipe`
- Consumes: transcription segments `{start_ms, end_ms, text}` and OCR pages `{page, text}`

- [ ] **Step 1: Write failing tests** using deterministic fake ASR/OCR/Dify adapters. Assert recipe sections for hook, pacing, captions, audio, CTA, and negative constraints; assert every rule has a citation.
- [ ] **Step 2: Run** `uv run --project services/control-plane pytest services/control-plane/tests/test_tutorial_understanding.py -q`; expect import failure.
- [ ] **Step 3: Implement local extraction** with sentence segmentation and rule heuristics; call Dify only when configured, merge only schema-valid results, and reject uncited generated rules.
- [ ] **Step 4: Re-run focused tests** and expect PASS.
- [ ] **Step 5: Commit** with `git commit -m "feat: extract cited editing recipes"`.

### Task 3: Shot analysis and enrichment

**Files:**
- Create: `services/control-plane/app/services/course_material_analysis_service.py`
- Modify: `services/control-plane/app/services/media_analysis_service.py`
- Test: `services/control-plane/tests/test_course_material_analysis.py`

**Interfaces:**
- Produces: `CourseMaterialAnalysisService.analyze_asset(asset_id: str) -> list[MaterialShot]`

- [ ] **Step 1: Write failing tests** around a generated fixture video with three color/scene blocks. Assert contiguous shot boundaries, representative frame, OCR text, anonymous person/product/scene tags, pHash, and no out-of-bounds timestamps.
- [ ] **Step 2: Run** `uv run --project services/control-plane pytest services/control-plane/tests/test_course_material_analysis.py -q`; expect missing service.
- [ ] **Step 3: Implement ffmpeg scene detection and enrichment** by reusing current ffprobe/OCR helpers; store thumbnails below the course asset directory.
- [ ] **Step 4: Re-run focused tests** and expect PASS.
- [ ] **Step 5: Commit** with `git commit -m "feat: index course materials by shot"`.

### Task 4: Rights-aware semantic and similarity search

**Files:**
- Create: `services/control-plane/app/services/course_material_search_service.py`
- Modify: `services/control-plane/app/main.py`
- Test: `services/control-plane/tests/test_course_material_search.py`

**Interfaces:**
- Produces: `search(query, course_id, commercial, limit) -> list[ShotSearchResult]`
- Produces: `GET /api/courses/{course_id}/shots/search?q=&commercial=&limit=`
- Produces: `GET /api/courses/{course_id}/shots/{shot_id}/similar`

- [ ] **Step 1: Write failing search tests** with fixed embeddings/pHashes; assert combined ranking, rights filtering, deterministic tie breaks, and duplicate threshold reporting.
- [ ] **Step 2: Run** `uv run --project services/control-plane pytest services/control-plane/tests/test_course_material_search.py -q`; expect route/service failure.
- [ ] **Step 3: Implement normalized cosine similarity, token overlap fallback, Hamming pHash distance, and explicit score fields** `semantic_score`, `text_score`, `duplicate_score`, `combined_score`.
- [ ] **Step 4: Re-run focused tests** and expect PASS.
- [ ] **Step 5: Commit** with `git commit -m "feat: add rights-aware course material search"`.

### Task 5: Course processing API and UI status

**Files:**
- Modify: `services/control-plane/app/main.py`
- Create: `services/control-plane/app/templates/courses.html`
- Create: `services/control-plane/app/static/courses.css`
- Create: `services/control-plane/app/static/courses.js`
- Modify: `services/control-plane/app/templates/_app_nav.html`
- Test: `services/control-plane/tests/test_courses_page.py`

**Interfaces:**
- Produces: `POST /api/courses/{course_id}/process`, `GET /api/courses`, `/courses`

- [ ] **Step 1: Write failing page/API tests** for processing progress, failed-file explanation, recipe citations, shot counts, and rights summary.
- [ ] **Step 2: Run** `uv run --project services/control-plane pytest services/control-plane/tests/test_courses_page.py -q`; expect 404.
- [ ] **Step 3: Implement the orchestration endpoint and accessible course dashboard** without exposing filesystem paths or credentials.
- [ ] **Step 4: Re-run focused tests** and expect PASS.
- [ ] **Step 5: Commit** with `git commit -m "feat: add course knowledge dashboard"`.

