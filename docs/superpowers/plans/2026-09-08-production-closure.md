# Reference-driven production closure

Approved by user: continue without staged handoffs, finish in-scope work and list only genuinely external blockers.

Global constraints: preserve dirty work, source media and old drafts; no secret output; no account-limit changes or model switching to bypass limits; zero-key baseline remains; no unattended publication. Real consented task/model calls may be used for bounded acceptance, but stop on authentication/quota errors. No remote Git push unless explicitly requested. Never claim sampled or mocked results as full visual understanding/client playback.

## 1. Speech alignment helper

Own new services/control-plane/app/services/narration_alignment_service.py and tests/test_narration_alignment.py; no pipeline edits in delegated task.

Interface: align_narration(text: str, transcript: TranscriptResult, duration_seconds: float) -> AlignmentResult dataclass with captions: list[CaptionCue], status: str, reason: str. Accept actual timed words only if normalized alphanumeric/CJK text exactly matches full narration (punctuation/whitespace ignored), finite timestamps ordered/nonoverlapping and within duration with 0.05s tolerance. Reject empty/partial/hallucinated word sequences; never invent word times. Group using CaptionService.segment_text, preserve original narration punctuation, assign each group actual first/last matched word times. Return status word_aligned on success; otherwise unavailable with empty captions and specific reason. No cloud calls in helper. Tests must prove leading silence preserved, punctuation/case normalization, Chinese multi-character words across group boundaries, full mismatch, truncated speech, invalid/nonfinite/overlap/out-of-duration, long caption splits. If word crossing group boundary makes exact timing ambiguous merge groups rather than interpolate fictitious times. TDD red/green; scheduler disabled.

- [x] helper implement and review
- [x] main: transcribe generated narration once via configured RoutedTranscriber, respect cloud consent, record real usage/provider, use aligned cues in final timeline/preview/draft; report explicit estimated fallback.

## 2. Role-aware visual planning and evidence cache

- [x] main: inspect actual course/reference paths and existing public Dify workflow state, using supported interface and preserving backup.
- [x] feed sampled reference frames independently marked reference_not_editable and tutorial roles when available, bounded counts; editable source validation only material IDs. Preserve source/time and input role. No sample ad claims become product facts.
- [x] cache valid director outputs on exact bounded input/image content plus workflow revision; no persistent reuse without known workflow revision. No account limit changes. Cache hits and preflight errors do not record stale cloud usage.
- [x] factual/semantic evidence markers remain unknown, distinct from technical quality; no verified score invented. Independent factual verification and automated style rework remain Open in the original design.

## 3. Runtime and real acceptance

- [x] update local runtime and deployed workflow only after backing up exact target and confirming no active work; current local service 8330, final DSL published and public parameters confirm visual_frames. See 2026-09-08-dify-live-verification.md. The first real two-frame request is blocked by confirmed SetLimitExceeded; full film acceptance remains unchecked.
- [ ] run original course/material user flow with supplied reference using a bounded real task, preserve evidence/cost/result and editable draft. Diagnose/fix actual failures, no special-case output script substituting for platform.
- [x] regression/review/documents; final full control-plane suite: 404 passed in 161.48s; independent review fixes covered by regression. Runtime and real acceptance above remain incomplete, with blockers documented.

Runtime blockers observed 2026-09-08: native startup command rejected by execution policy before execution (database backup in same command did not execute either). Do not retry via another shell/background mechanism. Old Docker runtime and its data untouched. Dify old DSL backed up and new draft imported via UI, but editor WebSocket synchronization never completes; Publish Update has no observed effect. GET /v1/parameters still returns only four text variables. Backend socket handshake independently returns HTTP 101; no unsupported database publish, auth/CORS bypass or model-limit changes attempted. New live model/film/client acceptance is not passed.

Progress and exact commands/results belong in docs/progress.md. The completed director/visual-input plans remain done, not reimplemented.
