# Licensed Video and Trend Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a rights-aware, video-first material intake and a resilient trend evidence pipeline that does not download unauthorized platform videos.

**Architecture:** Extend licensed assets with auditable rights metadata, add focused Pexels/Pixabay adapters, and introduce a trend aggregator with official, public-metadata, and reviewed-catalog sources. The automation service consumes only normalized evidence and authorized video assets.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, httpx, pytest, FFmpeg, vanilla JavaScript.

## Global Constraints

- Final clips may only use assets with `rights_status=authorized`.
- Public Douyin/Xiaohongshu pages are trend evidence only and must never be downloaded as editing material.
- Video is the default material type; product images are cover, motion-graphic, or generation-reference inputs only.
- Provider failures fall back safely and remain visible in diagnostics.

---

### Task 1: Rights-Aware Licensed Asset Model

**Files:**
- Modify: `services/control-plane/app/models/licensed_asset.py`
- Modify: `services/control-plane/app/schemas/material.py`
- Modify: `services/control-plane/app/services/material_library_service.py`
- Modify: `services/control-plane/app/main.py`
- Test: `services/control-plane/tests/test_licensed_asset_rights.py`

**Interfaces:**
- Produces: `rights_status`, `rights_basis`, `product_id`, `allowed_platforms`, `rights_expires_at`, `sha256`, and `use_count` fields.

- [ ] **Step 1: Write failing selection tests**

```python
def test_material_selector_rejects_pending_rights(material_service, pending_asset):
    selected = material_service.search("宠物", limit=10)
    assert pending_asset.id not in {asset.id for asset in selected}
```

- [ ] **Step 2: Run the test**

Run: `pytest services/control-plane/tests/test_licensed_asset_rights.py -v`

Expected: FAIL because pending rights are not represented.

- [ ] **Step 3: Add fields, migration guards, and selection filter**

Default existing `user_confirmed`, `pexels`, and `pixabay` rows to `authorized`; default unknown sources to `pending`. Increment `use_count` only after a task persists the selected asset.

- [ ] **Step 4: Run material tests**

Run: `pytest services/control-plane/tests/test_licensed_asset_rights.py services/control-plane/tests/test_material_library.py -v`

Expected: PASS and no pending asset returned.

### Task 2: Authorized Merchant and User Video Intake

**Files:**
- Create: `services/control-plane/app/services/authorized_video_intake.py`
- Modify: `services/control-plane/app/main.py`
- Modify: `services/control-plane/app/static/index.html`
- Modify: `services/control-plane/app/static/app.js`
- Test: `services/control-plane/tests/test_authorized_video_intake.py`

**Interfaces:**
- Produces: `POST /api/materials/authorized-video` accepting a video plus rights metadata and returning a licensed asset.

- [ ] **Step 1: Write failing multipart intake tests**

```python
def test_authorized_video_requires_rights_basis(client, sample_mp4):
    response = client.post("/api/materials/authorized-video", files={"file": sample_mp4})
    assert response.status_code == 422
```

- [ ] **Step 2: Run the test**

Run: `pytest services/control-plane/tests/test_authorized_video_intake.py -v`

Expected: FAIL because the route does not exist.

- [ ] **Step 3: Implement validated intake**

Require non-empty rights basis and at least one allowed platform, validate the file as video, compute SHA-256, deduplicate by hash, and store the evidence fields. Reject expired rights.

- [ ] **Step 4: Add a compact UI flow**

Add one “上传授权视频” action that asks only for file, source type, rights basis, product ID if applicable, allowed platforms, and optional expiration. Keep advanced fields collapsed.

- [ ] **Step 5: Verify real upload selection**

Run: `pytest services/control-plane/tests/test_authorized_video_intake.py services/control-plane/tests/test_upload.py -v`

Expected: PASS and the stored asset is selectable by a generated task.

### Task 3: Pixabay Provider and Provider Diagnostics

**Files:**
- Create: `services/control-plane/app/adapters/pixabay.py`
- Modify: `services/control-plane/app/services/material_library_service.py`
- Modify: `services/control-plane/app/services/integration_service.py`
- Modify: `.env.example`
- Test: `services/control-plane/tests/test_pixabay_adapter.py`

**Interfaces:**
- Produces: `PixabayClient.search_videos(query, limit)` normalized to provider asset candidates.

- [ ] **Step 1: Write response normalization tests**

```python
def test_pixabay_prefers_vertical_large_video(fake_transport):
    client = PixabayClient(api_key="test", transport=fake_transport)
    result = client.search_videos("cat", limit=1)[0]
    assert result.media_type == "video"
    assert result.source_url.startswith("https://")
```

- [ ] **Step 2: Run the test**

Run: `pytest services/control-plane/tests/test_pixabay_adapter.py -v`

Expected: FAIL because the adapter is absent.

- [ ] **Step 3: Implement adapter and fallback order**

Search Pexels then Pixabay, rank vertical/high-resolution video first, download only from documented provider URLs, and persist license/source metadata. Expose `configured`, `not_configured`, and `last_error` in diagnostics.

- [ ] **Step 4: Run provider tests**

Run: `pytest services/control-plane/tests/test_pixabay_adapter.py services/control-plane/tests/test_material_library.py -v`

Expected: PASS for normalization and safe fallback.

### Task 4: Trend Evidence Aggregator

**Files:**
- Create: `services/control-plane/app/adapters/public_trend_web.py`
- Create: `services/control-plane/app/services/trend_aggregator.py`
- Modify: `services/control-plane/app/services/automation_service.py`
- Modify: `services/control-plane/app/services/integration_service.py`
- Test: `services/control-plane/tests/test_trend_aggregator.py`

**Interfaces:**
- Produces: `TrendEvidence(source, title, url, keyword, summary, discovered_at, confidence)` and `TrendAggregator.fetch(keyword, limit)`.

- [ ] **Step 1: Write source-order and non-download tests**

```python
def test_aggregator_falls_back_to_reviewed_catalog(aggregator):
    result = aggregator.fetch("宠物", limit=3)
    assert result[0].source == "reviewed_catalog"
    assert aggregator.material_downloader.calls == []
```

- [ ] **Step 2: Run the tests**

Run: `pytest services/control-plane/tests/test_trend_aggregator.py -v`

Expected: FAIL because the aggregator is absent.

- [ ] **Step 3: Implement official/public/catalog fallback**

Use official search when configured, parse only title/link/snippet from public search metadata when enabled, and finally query reviewed stored evidence with fuzzy keyword aliases. Never call the material downloader for social-platform URLs.

- [ ] **Step 4: Connect daily automation**

Store the selected evidence ID and source on the task, include evidence in Dify analysis input, and emit a visible warning when the chain reaches catalog fallback.

- [ ] **Step 5: Verify daily task creation**

Run: `pytest services/control-plane/tests/test_trend_aggregator.py services/control-plane/tests/test_automation.py -v`

Expected: PASS and an automatic task can be created without Douyin official credentials.

### Task 5: Seedance Supplemental Video Boundary

**Files:**
- Create: `services/control-plane/app/adapters/seedance.py`
- Modify: `services/control-plane/app/services/material_library_service.py`
- Modify: `services/control-plane/app/services/integration_service.py`
- Modify: `.env.example`
- Test: `services/control-plane/tests/test_seedance_adapter.py`

**Interfaces:**
- Produces: `SeedanceClient.create_vertical_clip(prompt, reference_url=None)` and a diagnostic state that is disabled until API key and model endpoint are present.

- [ ] **Step 1: Write disabled-state and payload tests**

```python
def test_seedance_is_disabled_without_model_endpoint():
    assert SeedanceClient(api_key="", model="").configured is False
```

- [ ] **Step 2: Run the test**

Run: `pytest services/control-plane/tests/test_seedance_adapter.py -v`

Expected: FAIL because the adapter is absent.

- [ ] **Step 3: Implement asynchronous create/poll/download**

Submit 9:16 clips, poll with bounded retries, verify the returned media type, persist generation provenance, and select generation only when authorized library assets are insufficient.

- [ ] **Step 4: Verify adapter behavior with mocked HTTP**

Run: `pytest services/control-plane/tests/test_seedance_adapter.py -v`

Expected: PASS without making a paid live request.
