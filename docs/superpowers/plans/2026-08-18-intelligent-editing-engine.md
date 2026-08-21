# Intelligent Editing Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, reproducible multi-source short-video editing engine that transcribes and analyzes all media, plans one authoritative timeline, and renders matching MP4, captions, cover, evidence, and Jianying draft outputs.

**Architecture:** Add typed media-analysis and editing-timeline contracts, then isolate transcription/analysis, deterministic planning, FFmpeg rendering, and Jianying export behind focused services. `PipelineService` orchestrates those units and stores every intermediate JSON artifact so the review UI can explain each edit.

**Tech Stack:** Python 3.11, FastAPI, SQLModel, FFmpeg/FFprobe, faster-whisper 1.2.1, RapidOCR 3.9.2, Pillow, pyJianYingDraft 0.3.0, pytest, Docker Compose.

## Global Constraints

- Original media is read-only and never moved, deleted, or overwritten.
- Preview and Jianying draft must consume the same `EditingTimeline`.
- Default output is 1080×1920, 30fps, H.264/AAC, `yuv420p`, faststart, -14 LUFS, -1.5 dBTP.
- Default target is 30 seconds; automated output is capped at 180 seconds and source availability.
- Only user-provided, rights-confirmed audio may be used as BGM.
- Missing models produce explicit warnings; they never produce invented transcript or OCR.
- Every new behavior follows red-green-refactor and every task ends with a commit.

---

### Task 1: Typed Analysis Contracts and Local Media Understanding

**Files:**
- Create: `services/control-plane/app/schemas/editing.py`
- Create: `services/control-plane/app/adapters/transcription.py`
- Create: `services/control-plane/app/services/media_analysis_service.py`
- Modify: `services/control-plane/app/adapters/ffmpeg.py`
- Modify: `services/control-plane/app/config.py`
- Modify: `services/control-plane/pyproject.toml`
- Modify: `services/control-plane/Dockerfile`
- Test: `services/control-plane/tests/test_media_analysis.py`

**Interfaces:**
- Produces `TranscriptWord`, `TranscriptSegment`, `SceneInterval`, `SilenceInterval`, `FrameEvidence`, `MediaAnalysis` Pydantic models.
- Produces `WhisperTranscriber.transcribe(path: Path) -> TranscriptResult`.
- Produces `MediaAnalysisService.analyze(path: Path, material_id: str) -> MediaAnalysis`.
- Extends `FfmpegAdapter` with `detect_silence`, `detect_scenes`, `extract_frame`, and `measure_frame`.

- [ ] Write failing tests that require word timestamps, scene boundaries, silence intervals, OCR-safe empty results, and persisted analysis JSON.
- [ ] Run `python -m pytest tests/test_media_analysis.py -q` and confirm failures are caused by missing contracts/adapters.
- [ ] Add exact dependencies `faster-whisper==1.2.1` and `rapidocr==3.9.2`, plus persistent model-cache settings.
- [ ] Implement lazy model loading, language/confidence reporting, scene/silence parsing, representative-frame extraction, OCR and measured frame evidence.
- [ ] Run focused and full control-plane tests; commit `feat: analyze speech scenes and keyframes`.

### Task 2: Deterministic Multi-Source Timeline Planner

**Files:**
- Create: `services/control-plane/app/services/timeline_service.py`
- Modify: `services/control-plane/app/schemas/editing.py`
- Test: `services/control-plane/tests/test_timeline_service.py`

**Interfaces:**
- Produces `TimelineClip`, `CaptionCue`, `AudioMixPlan`, `CoverPlan`, `EditingTimeline`.
- Produces `TimelinePlanner.plan(analyses, recipe, target_seconds, bgm_path=None) -> EditingTimeline`.
- Produces `validate_timeline(timeline, analyses) -> None`.

- [ ] Write failing tests for silence inversion, sentence padding, scene candidates, multi-source alternation, hook selection, target clipping, caption remapping, no repeated interval, and invalid source bounds.
- [ ] Run the focused tests and verify expected missing-symbol failures.
- [ ] Implement pure candidate generation and scoring functions; keep all thresholds named and serialized into the plan.
- [ ] Implement planner and validator with 300ms minimum segments, 150ms speech padding, 800ms silence removal, 1.2–4.5s visual candidates, and 180s cap.
- [ ] Run focused and full tests; commit `feat: plan multi-source editing timelines`.

### Task 3: Timeline-Based FFmpeg Renderer

**Files:**
- Create: `services/control-plane/app/services/render_service.py`
- Create: `services/control-plane/app/services/caption_service.py`
- Modify: `services/control-plane/app/adapters/ffmpeg.py`
- Test: `services/control-plane/tests/test_render_service.py`

**Interfaces:**
- Produces `CaptionService.write_ass/write_srt`.
- Produces `RenderService.render(timeline, output_dir) -> RenderArtifacts` with preview, captions, cover and render report paths.
- Extends FFmpeg adapter with filter-complex rendering and cover-frame extraction.

- [ ] Write failing tests using two generated videos with different aspect ratios and audio availability; assert multi-source render, 1080×1920, duration tolerance, audio stream, ASS/SRT and cover.
- [ ] Verify tests fail because renderer is absent.
- [ ] Implement ASS escaping and safe-area line wrapping; render subtitles from remapped cues.
- [ ] Implement per-clip trim, blurred-background vertical layout, restrained correction, concat, optional rights-confirmed BGM ducking, loudnorm and H.264/AAC output.
- [ ] Implement cover extraction and Pillow title layout using an available CJK font with deterministic fallback.
- [ ] Run focused and full tests; commit `feat: render polished vertical video packages`.

### Task 4: Jianying Timeline Parity and Pipeline Orchestration

**Files:**
- Modify: `services/control-plane/app/adapters/jianying.py`
- Modify: `services/control-plane/app/services/draft_service.py`
- Modify: `services/control-plane/app/services/pipeline_service.py`
- Modify: `services/control-plane/app/services/review_service.py`
- Test: `services/control-plane/tests/test_jianying.py`
- Test: `services/control-plane/tests/test_pipeline.py`

**Interfaces:**
- Adds `EditPlan.from_timeline(timeline)` conversion.
- Pipeline writes `analysis/media-analysis.json`, `analysis/edit-recipe.json`, `edit-timeline.json`, `captions.ass`, `captions.srt`, `cover.jpg`, `preview.mp4`, `draft.zip`, `render-report.json`, `review.json`.

- [ ] Write failing tests proving multiple source clips, exact source in/out ranges, caption count/text, optional BGM track and preview/draft duration parity.
- [ ] Verify focused failures.
- [ ] Extend Jianying text styling and clip metadata; map every timeline clip and caption without regenerating timing.
- [ ] Refactor pipeline into analyze → plan → render → draft → review stages and pass transcript/frame evidence into Dify when configured.
- [ ] Extend review manifest validation and downloadable artifact allowlist.
- [ ] Run focused and full tests; commit `feat: synchronize rendered and Jianying timelines`.

### Task 5: Analysis and Timeline Review UI

**Files:**
- Modify: `services/control-plane/app/templates/review.html`
- Modify: `services/control-plane/app/static/review.css`
- Modify: `services/control-plane/app/templates/workbench.html`
- Modify: `services/control-plane/app/static/workbench.js`
- Modify: `services/control-plane/app/static/workbench.css`
- Modify: `services/control-plane/app/main.py`
- Test: `services/control-plane/tests/test_workbench.py`

**Interfaces:**
- Adds safe download routes for timeline, captions, cover and render report.
- Review page consumes summary fields from the validated manifest, not arbitrary artifact HTML.

- [ ] Write failing HTML/API tests for analysis summary, timeline rows, engine badge and all artifact downloads.
- [ ] Verify focused failures.
- [ ] Add compact evidence and timeline sections, source labels, chosen reasons, removed-silence duration, transcript language and Dify/local engine badge.
- [ ] Add accessible download actions, loading/error states and responsive overflow behavior.
- [ ] Run Node syntax check, UI detector and full tests; commit `feat: explain intelligent edits in review UI`.

### Task 6: Runtime, Real-Model E2E and Completion Audit

**Files:**
- Modify: `deploy/compose.yml`
- Modify: `.env.example`
- Modify: `scripts/verify.ps1`
- Create: `scripts/verify-intelligent-edit.ps1`
- Modify: `README.md`
- Modify: `docs/runbook.md`
- Modify: `docs/progress.md`

**Interfaces:**
- Persists `/models` and exposes model/language/performance settings.
- Verification script creates two distinct source videos, at least one with real synthesized speech, then asserts transcript, multi-source timeline, captions, cover, preview and draft parity.

- [ ] Write verifier assertions before updating runtime code and run once to confirm missing-artifact failure.
- [ ] Add persistent model cache and pinned runtime dependencies; rebuild containers.
- [ ] Run real faster-whisper transcription and multi-source end-to-end verification without mocking the model.
- [ ] Run all control-plane, DingTalk and parent tests; validate Compose, JS, UI detector, health, persistence and clean Git status.
- [ ] Update documentation with measured runtime, model download expectations, quality controls and honest remaining external-account boundaries.
- [ ] Commit `feat: deliver intelligent editing engine` and perform requirement-by-requirement completion audit.

## Self-Review

- Spec coverage: all media understanding, multi-source planning, render, subtitles, audio, cover, Jianying parity, UI and real-model verification requirements map to Tasks 1–6.
- Placeholder scan: no deferred implementation placeholders are present.
- Type consistency: Tasks 1–4 consistently pass `MediaAnalysis[]` into `TimelinePlanner` and one `EditingTimeline` into both render and draft adapters.
