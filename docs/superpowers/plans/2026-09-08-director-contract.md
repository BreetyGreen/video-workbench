# Unified director contract — implementation batch 1

> Execute inline with executing-plans and test-driven-development. This is the first independently testable slice of the approved full-flow design, not its completion.

**Goal:** Make a validated Dify shot plan drive both narration and timeline selection in the production pipeline, while reporting evidence limitations.

**Architecture:** Add optional versioned director beats to EditRecipe for backwards compatibility. Validate material IDs/ranges against analyzed task media before synthesis; reuse TimelinePlanner and existing audio/subtitle/render/draft consumers. Legacy providers remain available but explicitly lack content/style verification.

**Tech Stack:** Pydantic, Python, pytest, existing Dify HTTP workflow and FFmpeg.

## Constraints

- No cloud calls without per-task consent; no live account limit changes.
- No private media or credentials committed; no published workflow mutation.
- Keep original-audio/local fallback and existing drafts.
- Do not equate source range validation with semantic truth or creative quality.

## Tasks

- [x] Add failing tests in `services/control-plane/tests/test_director_plan.py`: narration comes from plan; all beats survive shorter duration; unknown/out-of-bounds/overlapping sources reject; old recipe remains compatible.
- [x] Add `app/schemas/director.py` with strict version 1 beat contract and `app/services/director_service.py` validating ranges and overlap against MediaAnalysis; add optional `EditRecipe.director_plan`.
- [x] Integrate validated plan in `timeline_service.py` candidates and pipeline narration, expose bounded material catalog to tutorial workflow, respect cloud consent for both Dify workflows.
- [x] Update tutorial YAML prompt to request director beats from supplied IDs/time ranges, never infer labels from filenames or treat OCR as verified claims.
- [x] Add production-path tests and run director, timeline, Dify, pipeline regressions with scheduler disabled.
- [x] Update human/operator/catalog/progress boundaries: plan provenance present; semantic verification, actual multimodal input, word alignment and finite rework are still separate work.

Read-only review identified floating-point loss of the closing beat for 3/20 beat minimum-duration plans. Added red regression cases and tolerant duration comparisons plus an explicit all-beats-survive invariant. Combined pipeline test now verifies director text reaches a test TTS adapter and final routing/timeline. This remains synthetic-media/Mock-provider verification, not real speech or reference-effect acceptance.

Run from repository: `$env:VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED='false'; services/control-plane/.venv/Scripts/python.exe -m pytest services/control-plane/tests/test_director_plan.py -q`.

## Remaining full-flow batches

Actual multimodal upload plus cache and quota circuit breaker; shot semantic indexing and verified product facts; word-level alignment; content/style gate and bounded repair; user-entry multi-product live/cloud/desktop acceptance. Do not mark these complete from contract tests.
