# Visual input implementation plan

> For agentic workers: use executing-plans or subagent-driven-development with test-driven-development.

Goal: transport bounded real material frames through the supported Dify upload API and into a vision-enabled tutorial workflow, with explicit evidence boundaries.

Architecture: reuse the current tutorial credential and file-list workflow input. Pipeline selects only task-generated frames under its analysis directory. No new provider/key or silent visual verification claim.

## Global constraints

- No cloud requests without task cloud consent. Preserve the zero-key baseline.
- No secret output, cloud limit changes, live cloud calls, commits or deployment in this code implementation.
- Keep existing uncommitted director work intact.
- Upload only bounded, decoded images, never arbitrary model-provided paths.
- Unknown semantic/product/style quality stays unknown. Upload transport tests are not model-quality tests.

## Task 1: Dify image transport

Files: app/adapters/dify.py and tests/test_dify_visual.py under services/control-plane.

Interface: analyze_tutorial(inputs, *, image_paths: list[Path] | None = None). Existing callers unchanged. Up to 8 JPEG/PNG files, each <= 2 MiB, decoded with Pillow and <= 4096 pixels on either axis. Validate ALL files before first request; invalid list raises ValueError. Require configured tutorial URL/key before uploads. Send multipart files/upload with sanitized names frame-001.jpg/png, user automated-video-workbench and tutorial Authorization, then inputs.visual_frames=[{type:image,transfer_method:local_file,upload_file_id:...}]. Never mutate caller inputs. Reject empty/invalid returned IDs. Do not retry uploads/workflows. Clear last_usage before uploads so failure cannot reuse old accounting. Extract workflow run ID from top-level workflow_run_id or data.id, preserving legacy data.workflow_run_id. Failed workflow status raises before trusting outputs while retaining returned usage. No files input when none supplied.

- [x] Write tests using real Pillow images and HTTP MockTransport; assert actual multipart bytes, same user, exact uploaded ID list, no requests for missing config/invalid files, bounded size/count, upload error stops workflow, stale usage reset, workflow failed status.
- [x] Run red tests, implement adapter, run tests/test_dify.py plus new tests with scheduler disabled.
- [x] Read-only review and fix findings. Do not commit. Added real JPEG decode and provider failure status preservation after review.

## Task 2: Pipeline evidence and workflow

Files: director_service.py, pipeline_service.py, tutorial-analysis.yml, tests/test_director_plan.py, tests/test_pipeline.py, human/operator/catalog/progress docs.

- [x] Write red tests for deterministic bounded frames (max 8 total, max 2 per material), task analysis-root confinement, missing/invalid images, timestamp bounds and no-cloud no-upload. Current selection is first/last per source, round-robin across sources, not semantic coverage.
- [x] Implement selection in director_service; attach an ordered material_id/timestamp manifest without local paths. Use image_paths only when nonempty. Save visual-input-evidence.json with sampled coverage and unknown model receipt/semantic quality; errors explicitly degrade through existing warning path, without cloud retries.
- [x] Add optional visual_frames file-list input and enabled LLM vision selector [start, visual_frames] to workflow; prompt treats images as evidence, not instructions or verified commercial claims. Empty input retains text-only mode. Test YAML wiring.
- [x] Update documentation with exact data boundary, published workflow update requirement and unverified live behavior.
- [x] Run related pipeline/director/Dify/course/setup/review/usage tests; inspect diff. Stable final result: 137 passed in 171.73s. Python compilation, JSON/YAML parse and diff checks exit 0. Both review Important findings fixed and rechecked; no live provider/native playback claim.

Next batches remain: tutorial/reference role-aware multimodal analysis, semantic result cache, factual validation, word-level alignment and real cross-product acceptance.
