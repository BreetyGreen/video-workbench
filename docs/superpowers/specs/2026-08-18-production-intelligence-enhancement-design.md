# Production Intelligence Enhancement Design

## Goal

Upgrade the running video workbench from a single local Whisper-small path and heuristic-only edit selection into a production-oriented system with explicit quality profiles, ByteDance cloud ASR support, reference-video structural intelligence, and approval-blocking post-render quality gates.

## Decisions

- Keep the existing FastAPI workbench, deterministic FFmpeg renderer, unified edit timeline, Jianying draft generator, DingTalk intake, and Douyin evidence boundary.
- Do not copy OpenMontage AGPL source into the product. Reimplement the useful public workflow ideas as focused, independently tested services: provider routing, reference brief, decision evidence, and quality gates.
- Codex or another frontier agent remains the creative orchestrator. Dify stays optional for tutorial and trend workflows.
- `small` becomes preview/fallback only. Production prefers ByteDance Volcano BigASR when configured and explicitly allowed for the task, otherwise local `large-v3`. Private mode never calls cloud services.
- Cloud upload requires a per-task consent flag. Credentials alone never authorize uploading a task's media.
- A reference video is a separate optional upload, not a source clip, so it can guide pacing without accidentally appearing in the final timeline.

## User-visible profiles

### Production quality

1. Try Volcano BigASR when credentials exist and the task allows cloud processing.
2. Otherwise use local Whisper `large-v3`.
3. If the selected provider fails, fall back to local Whisper `small` and record the provider failure in the transcript and review evidence.

### Local privacy

1. Use local Whisper `large-v3`.
2. Never invoke a network model.
3. Fall back to local Whisper `small` only when `large-v3` cannot load or transcribe.

### Fast preview

Use local Whisper `small` directly. The review page must label this as preview-grade evidence.

## Components

### TaskProductionSettings

A new one-to-one table stores `quality_profile`, `cloud_processing_allowed`, and optional reference-video metadata. This avoids modifying existing SQLite tables and remains compatible with already-created local databases.

### RoutedTranscriber

`RoutedTranscriber` owns lazy local transcribers and an optional `VolcanoBigASRTranscriber`. It returns a normal `TranscriptResult` enriched with provider, model, quality profile, and fallback reason. Volcano input uses the official synchronous BigASR endpoint with base64 audio and parses utterance/word timestamps into the existing transcript schema.

### ReferenceIntelligenceService

The service analyzes an uploaded reference video using the existing local media analyzer and creates a structured reference brief containing:

- content and transcript summary;
- pacing profile and cut density;
- hook window;
- caption and audio treatment;
- five-aspect shot groups: subject, subject motion, scene, spatial framing, and camera;
- replication guidance that explicitly separates what to retain from what must change.

The local brief contains only defensible structural inference. If a configured frontier multimodal provider is added later, it can enrich the same schema without changing the timeline or UI contracts.

### TimelinePlanner integration

The reference brief influences maximum clip length and hook selection window. It does not directly inject reference media or override source bounds. Every selected clip still carries a score and reason.

### QualityGateService

After rendering, the service writes `quality-report.json`. Blocking gates cover required files, playable video, 1080x1920 canvas, duration agreement, contiguous timeline, hook placement, black-frame duration, long silence, and caption presence when speech exists. Warnings cover preview-grade ASR and unverified Jianying compatibility. Approval is disabled when any blocking gate fails.

## Data flow

1. User creates a task, chooses a profile, optionally permits cloud processing, and optionally uploads a reference video.
2. Source videos are analyzed through the routed transcriber.
3. The optional reference is analyzed separately and written to `analysis/reference-video-brief.json`.
4. Tutorial/trend analysis runs when Dify is configured.
5. Timeline planning consumes source analyses, tutorial recipe, and optional reference pacing profile.
6. The deterministic renderer produces preview, captions, cover, and render report.
7. The quality gate inspects the rendered package and writes a blocking report.
8. The review manifest exposes the chosen providers, reference guidance, quality gates, warnings, and three publish-copy candidates.

## Failure handling

- Missing cloud credentials: production falls back to local quality without attempting a request.
- Cloud not authorized for the task: production uses local quality and records that cloud was intentionally skipped.
- Cloud or large model failure: fall back to small and expose the exact provider class and failure type, without leaking credentials.
- Invalid or unsupported reference upload: source processing continues with a warning; the reference file is never treated as edit footage.
- A failed blocking quality gate leaves the task in reviewing state but prevents approval until reprocessing succeeds.

## Verification

- Unit tests prove profile routing, cloud-consent enforcement, Volcano response parsing, fallback audit fields, reference pacing derivation, timeline influence, and gate pass/fail behavior.
- API tests prove profile/reference persistence, integration-status visibility, review manifest fields, and approval blocking.
- Full pytest suites for the control plane and DingTalk connector remain green.
- A real local fixture run must produce preview, draft, reference brief, and quality report.
- Browser verification must show the profile controls on intake and quality evidence on review.
