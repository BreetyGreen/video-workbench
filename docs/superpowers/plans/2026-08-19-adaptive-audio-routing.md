# Adaptive Audio Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add auditable original/mixed/narration routing and effect-priority Doubao TTS 2.0 voiceover to the automated video pipeline.

**Architecture:** A focused TTS adapter produces local audio, a pure routing service decides when narration is needed, the timeline carries the decision, and the existing FFmpeg renderer mixes original audio and voiceover without changing task persistence. Pipeline orchestration records every decision and fallback in review artifacts.

**Tech Stack:** Python 3.12, Pydantic, httpx, FFmpeg, FastAPI, pytest, Volcengine Doubao Speech V3 HTTP API.

## Global Constraints

- Preserve usable source speech; TTS is conditional rather than mandatory.
- Default to `zh_female_vv_uranus_bigtts`, `seed-tts-2.0`, MP3, 24 kHz.
- Never log or serialize API keys.
- TTS failure must degrade with an explicit warning and must not block rendering.
- All production code follows red-green TDD.

---

### Task 1: TTS adapter

**Files:**
- Create: `services/control-plane/app/adapters/volcano_tts.py`
- Modify: `services/control-plane/app/config.py`
- Test: `services/control-plane/tests/test_volcano_tts.py`

**Interfaces:**
- Produces: `VolcanoTTSClient.synthesize(text: str, output: Path) -> TTSResult` and `TTSResult(path, duration_seconds, voice_type)`.

- [ ] Write tests for API-key headers, concatenated V3 JSON decoding, audio persistence, and non-success response handling.
- [ ] Run `python -m pytest services/control-plane/tests/test_volcano_tts.py -q` and verify failure because the adapter is absent.
- [ ] Implement the minimal adapter and settings fields.
- [ ] Re-run the test and verify all cases pass.

### Task 2: Pure audio routing

**Files:**
- Create: `services/control-plane/app/services/audio_routing_service.py`
- Modify: `services/control-plane/app/schemas/editing.py`
- Test: `services/control-plane/tests/test_audio_routing.py`

**Interfaces:**
- Consumes: `list[MediaAnalysis]`, narration text, and optional `TTSResult`.
- Produces: `AudioRoutingDecision(mode, reason, original_gain_db, voiceover_path, voice_type, captions)`.

- [ ] Write failing tests for `original`, `mixed`, `narration`, and TTS-unavailable fallback.
- [ ] Run the focused tests and verify expected assertion failures.
- [ ] Implement transcript-duration thresholds and deterministic narration captions.
- [ ] Re-run focused tests and verify they pass.

### Task 3: Timeline and render integration

**Files:**
- Modify: `services/control-plane/app/services/timeline_service.py`
- Modify: `services/control-plane/app/services/render_service.py`
- Modify: `services/control-plane/app/schemas/editing.py`
- Test: `services/control-plane/tests/test_render_service.py`
- Test: `services/control-plane/tests/test_timeline_service.py`

**Interfaces:**
- Consumes: `AudioRoutingDecision` from Task 2.
- Produces: `EditingTimeline.audio` with original and voiceover tracks mixed into the preview.

- [ ] Add failing tests that assert voiceover is an independent FFmpeg input and original gain changes by mode.
- [ ] Run focused renderer/timeline tests and verify the new assertions fail.
- [ ] Extend `AudioMixPlan`, timeline construction, FFmpeg filter graph, and render report.
- [ ] Re-run focused tests and verify they pass.

### Task 4: Pipeline orchestration and review evidence

**Files:**
- Modify: `services/control-plane/app/services/pipeline_service.py`
- Modify: `services/control-plane/app/main.py`
- Modify: `services/control-plane/app/templates/review.html`
- Modify: `services/control-plane/tests/test_pipeline.py`

**Interfaces:**
- Consumes: TTS adapter, routing service, current task analyses.
- Produces: `analysis/audio-routing.json`, optional `voiceover.mp3`, and review manifest `audio_route`.

- [ ] Add failing pipeline tests for speech-preserving and narration-generating tasks plus integration status.
- [ ] Run focused pipeline tests and verify failures are caused by missing orchestration.
- [ ] Wire the adapter and routing service, create a conservative narration baseline, and render review evidence.
- [ ] Re-run focused tests and verify they pass.

### Task 5: Documentation and end-to-end verification

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/runbook.md`

**Interfaces:**
- Consumes: completed Tasks 1-4.
- Produces: operator-facing configuration and verified pet-video output.

- [ ] Document TTS variables, automatic routing semantics, and fallback behavior without including secrets.
- [ ] Run all control-plane tests and require zero failures.
- [ ] Probe both health endpoints and the integration status endpoint.
- [ ] Process the downloaded pet footage, inspect the quality report, and inspect one labeled early/middle/late contact sheet.
