# Video Workbench Product Redesign Implementation Plan

> **For Codex:** Execute this plan with `executing-plans`, `test-driven-development`, and `verification-before-completion`. Preserve all pre-existing worktree changes.

**Goal:** Turn the current engineering console into a coherent, production-oriented automated video workbench with a compact creation flow, trustworthy usage semantics, a focused review workspace, improved narration/captions, licensed voice selection, and compliant trend inputs.

**Architecture:** Keep the existing FastAPI + Jinja + vanilla JavaScript stack. Add a shared design system and navigation shell, then expose focused routes and APIs for creation, usage, voices, and trends. Extend the existing local pipeline instead of introducing a second frontend or workflow engine. Treat official provider data, configured entitlements, and local metering as separate evidence layers.

**Tech Stack:** FastAPI, Jinja2, vanilla CSS/JS, SQLModel, ffmpeg, ASS/SRT captions, Volcengine/Doubao TTS, Douyin Open Platform, pytest.

---

## Task 1: Shared application shell and responsive design system

**Files:**
- Create: `services/control-plane/app/static/design_system.css`
- Modify: `services/control-plane/app/templates/_app_nav.html`
- Modify: `services/control-plane/app/static/app_nav.css`
- Modify: `services/control-plane/app/templates/workbench.html`
- Modify: `services/control-plane/app/templates/review.html`
- Modify: `services/control-plane/app/templates/cloud_usage_settings.html`
- Test: `services/control-plane/tests/test_workbench.py`
- Test: `services/control-plane/tests/test_review.py`
- Test: `services/control-plane/tests/test_cloud_usage_api.py`

**Steps:**
1. Add failing page tests for the shared sidebar, current-page state, return links, and responsive shell markers.
2. Run the focused tests and confirm the expected failures.
3. Implement neutral OKLCH tokens, Iris accent, semantic status colors, shared sidebar, mobile top navigation, structural breakpoints, visible focus states, and reduced-motion support.
4. Apply the shell to creation, usage, and review pages without changing their route contracts.
5. Run focused tests and full page regression tests.

## Task 2: Compact creation flow

**Files:**
- Modify: `services/control-plane/app/templates/workbench.html`
- Modify: `services/control-plane/app/static/workbench.css`
- Modify: `services/control-plane/app/static/workbench.js`
- Modify: `services/control-plane/app/main.py`
- Test: `services/control-plane/tests/test_workbench.py`

**Steps:**
1. Add failing tests that the default flow exposes only the topic brief, material input, rights acknowledgement, and primary generate action, with existing quality/reference/tutorial controls under an advanced disclosure.
2. Add failing tests for quick project presets and default-compatible task submission.
3. Implement the compact form while keeping the existing `/api/tasks` payload compatible.
4. Show a clear preflight summary: assets, selected preset, cloud processing state, estimated duration, and the next action.
5. Verify task creation and rendering of previous tasks.

## Task 3: Trustworthy usage and cost center

**Files:**
- Modify: `services/control-plane/app/templates/cloud_usage_settings.html`
- Modify: `services/control-plane/app/static/cloud_usage_settings.js`
- Create: `services/control-plane/app/static/cloud_usage_settings.css`
- Modify: `services/control-plane/app/services/cloud_usage_service.py`
- Modify: `services/control-plane/app/services/usage_service.py`
- Modify: `services/control-plane/app/main.py`
- Test: `services/control-plane/tests/test_cloud_usage_api.py`
- Test: `services/control-plane/tests/test_usage_service.py`

**Steps:**
1. Add failing tests for four evidence layers: official cash balance, official gifts/packages, configured budgets, and local measured consumption.
2. Add failing tests that unavailable or unsupported fields return `null` plus an explicit status, never a fabricated zero.
3. Implement a summary view with last-refresh time, source labels, unsupported explanations, and a per-video cost ledger.
4. Move credentials and budget editing into a secondary settings disclosure while keeping local secret handling unchanged.
5. Verify refresh, credential-error rendering, unknown states, and task-level usage totals.

## Task 4: Review workspace and issue positioning

**Files:**
- Modify: `services/control-plane/app/templates/review.html`
- Modify: `services/control-plane/app/static/review.css`
- Modify: `services/control-plane/app/main.py`
- Modify: `services/control-plane/app/services/review_service.py`
- Test: `services/control-plane/tests/test_review.py`

**Steps:**
1. Add failing tests for a dark review stage, persistent back navigation, issue summary, narration coverage, subtitle coverage, timeline issue anchors, and Jianying draft actions.
2. Extend the review manifest read model with derived coverage and issue-location data without changing stored artifacts.
3. Rebuild the page around the video, a compact inspection rail, and secondary evidence drawers.
4. Retain approval quality gates, rights checks, downloads, and audit events.
5. Verify review for complete, incomplete, and missing-artifact tasks.

## Task 5: Full narration and intelligent captions

**Files:**
- Modify: `services/control-plane/app/schemas/editing.py`
- Modify: `services/control-plane/app/services/audio_routing_service.py`
- Modify: `services/control-plane/app/services/caption_service.py`
- Modify: `services/control-plane/app/services/pipeline_service.py`
- Modify: `services/control-plane/app/services/render_service.py`
- Modify: `services/control-plane/app/services/quality_gate_service.py`
- Test: `services/control-plane/tests/test_audio_routing.py`
- Create or modify: `services/control-plane/tests/test_caption_service.py`
- Modify: `services/control-plane/tests/test_pipeline.py`
- Modify: `services/control-plane/tests/test_render_service.py`

**Steps:**
1. Add failing tests for narration policies: preserve meaningful original speech, fully narrate stock/product footage, and mix brief natural sound below narration.
2. Add failing tests for duration-aware narration coverage and captions covering the entire generated voiceover.
3. Add failing tests for semantic Chinese caption segmentation, maximum visual line length, keyword emphasis, safe-area placement, and valid ASS escaping.
4. Implement content-aware narration policy and template-specific scripts for product introduction and tutorial explanation.
5. Implement caption style metadata and ASS rendering with readable hierarchy, restrained keyword highlighting, and safe-area presets.
6. Add quality gates for narration coverage and caption timing coverage.
7. Run focused pipeline/render tests and a local ffmpeg artifact test.

## Task 6: Licensed voice center

**Files:**
- Create: `services/control-plane/app/services/voice_catalog_service.py`
- Create: `services/control-plane/app/templates/voices.html`
- Create: `services/control-plane/app/static/voices.css`
- Create: `services/control-plane/app/static/voices.js`
- Modify: `services/control-plane/app/config.py`
- Modify: `services/control-plane/app/adapters/volcano_tts.py`
- Modify: `services/control-plane/app/main.py`
- Modify: `services/control-plane/app/templates/_app_nav.html`
- Test: `services/control-plane/tests/test_volcano_tts.py`
- Create: `services/control-plane/tests/test_voice_catalog.py`

**Steps:**
1. Verify current official Volcengine voice identifiers from primary documentation before adding presets.
2. Add failing tests for catalog source/licensing labels, content presets, configured availability, and explicit unavailable states.
3. Add a voice catalog API and preview endpoint with a deliberate user action and usage recording.
4. Add a voice center page with product/tutorial recommendations and preview controls.
5. Allow the compact creation form to select a voice preset without exposing raw provider identifiers.
6. Verify preview failure handling and metering.

## Task 7: Compliant trend inputs

**Files:**
- Create: `services/control-plane/app/templates/trends.html`
- Create: `services/control-plane/app/static/trends.css`
- Create: `services/control-plane/app/static/trends.js`
- Modify: `services/control-plane/app/main.py`
- Modify: `services/control-plane/app/services/automation_service.py`
- Modify: `services/control-plane/app/templates/_app_nav.html`
- Modify: `services/control-plane/app/schemas/automation.py`
- Test: `services/control-plane/tests/test_automation.py`
- Test: `services/control-plane/tests/test_workbench.py`

**Steps:**
1. Add failing tests for an authorized Douyin topic discovery action and a user-supplied Xiaohongshu URL/evidence import action.
2. Implement a manual Douyin refresh endpoint using the existing Open Platform client and clear not-configured states.
3. Implement URL/evidence import for Xiaohongshu without cookies, private APIs, or automated page scraping.
4. Add source, capture time, evidence type, and freshness labels to every trend card.
5. Verify configured, not-configured, empty, duplicate, and failed-provider states.

## Task 8: End-to-end pet product acceptance

**Files:**
- Modify: `services/control-plane/tests/test_pipeline.py`
- Modify: `services/control-plane/tests/test_review.py`
- Modify: `docs/progress.md`
- Modify: `README.md`

**Steps:**
1. Create a pet grooming product task using the compact flow and licensed/available local assets.
2. Process it end to end and verify preview, cover, captions, edit timeline, review manifest, quality report, task usage, and Jianying draft package.
3. Inspect the video and representative UI states at desktop, tablet, and narrow mobile widths.
4. Run the complete pytest suite, static asset checks, and live HTTP route checks.
5. Document confirmed capabilities, remaining external-account requirements, and exact user entry points.

## Completion gate

Do not mark the project complete until:
- The full test suite passes.
- The live app exposes coherent navigation among creation, usage, voices, trends, and review.
- Unknown provider data is never presented as a numeric zero.
- Narration/caption coverage is visible in both quality data and review UI.
- A real pet product task produces a playable preview and downloadable Jianying draft.
- Responsive screenshots show no horizontal overflow at representative widths.
- Any remaining external platform limitation is explicit and does not masquerade as a completed integration.
