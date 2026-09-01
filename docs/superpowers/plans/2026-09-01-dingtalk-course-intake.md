# DingTalk Course Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Receive a dedicated DingTalk course-ingest group event, persist its tutorial/reference/material attachments as one auditable course, and provide a development-only fixture path that exercises the same production intake service.

**Architecture:** Extend the existing DingTalk connector with explicit course roles and forward a normalized multipart request to the control plane. The control plane owns validation, SHA-256 deduplication, durable course records, and provenance; a CLI fixture adapter constructs the same normalized event without exposing a production simulation endpoint.

**Tech Stack:** Python 3.11, FastAPI 0.116.1, SQLModel 0.0.24, httpx 0.28.1, pytest 8.4.1, DingTalk Stream SDK 0.24.3

## Global Constraints

- Users must not need Codex to operate the deployed product.
- The simulation boundary is the DingTalk event source only; persistence and downstream processing must use production code.
- Duplicate DingTalk `message_id` and duplicate file SHA-256 values must not create duplicate course assets.
- Accepted course files are video, audio, image, PDF, DOCX, PPTX, and plain text; executable payloads are rejected.
- Maximum declared and downloaded file size defaults to 500 MiB.
- Rights default to `unknown`; commercial jobs may consume only `commercial_authorized` assets.
- Secrets never appear in logs, API responses, fixtures, or Git.

---

### Task 1: Course persistence model

**Files:**
- Modify: `services/control-plane/app/models.py`
- Modify: `services/control-plane/app/db.py`
- Create: `services/control-plane/app/schemas/courses.py`
- Test: `services/control-plane/tests/test_course_repository.py`

**Interfaces:**
- Produces: `Course`, `CourseAsset`, `CourseAssetRole`, `RightsStatus`
- Produces: `CourseAssetRead`, `CourseRead`

- [ ] **Step 1: Write failing persistence tests**

Create tests that save one `Course` with tutorial, reference, and material assets; assert `source_message_id` is unique and role/rights values round-trip.

- [ ] **Step 2: Run the focused test**

Run: `uv run --project services/control-plane pytest services/control-plane/tests/test_course_repository.py -q`

Expected: FAIL because `Course` and `CourseAsset` do not exist.

- [ ] **Step 3: Implement minimal typed models**

Add string enums `CourseAssetRole(tutorial, reference, material)` and `RightsStatus(unknown, personal_learning, commercial_authorized)`. Add `Course(id, title, source_type, source_user, source_conversation, source_message_id, status, created_at, updated_at)` and `CourseAsset(id, course_id, role, original_name, stored_path, mime_type, size_bytes, sha256, rights_status, source_message_id, created_at)` with unique constraints on course message and `(course_id, sha256, role)`.

- [ ] **Step 4: Run the focused test**

Run: `uv run --project services/control-plane pytest services/control-plane/tests/test_course_repository.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add services/control-plane/app/models.py services/control-plane/app/db.py services/control-plane/app/schemas/courses.py services/control-plane/tests/test_course_repository.py && git commit -m "feat: add course intake persistence"`

### Task 2: Normalized course intake service and API

**Files:**
- Create: `services/control-plane/app/services/course_intake_service.py`
- Modify: `services/control-plane/app/main.py`
- Test: `services/control-plane/tests/test_course_intake_api.py`

**Interfaces:**
- Consumes: `Course`, `CourseAsset`, `CourseAssetRole`, `RightsStatus`
- Produces: `CourseIntakeService.create_course(...) -> Course`
- Produces: `POST /api/courses/intake` and `GET /api/courses/{course_id}`

- [ ] **Step 1: Write failing API tests**

Post multipart fields `title`, source provenance, `asset_roles` JSON, `rights_statuses` JSON, and four files. Assert 201, three roles persisted, filenames are sanitized, executable MIME is 415, oversize is 413, and repeated source message returns the existing course with 200.

- [ ] **Step 2: Verify failure**

Run: `uv run --project services/control-plane pytest services/control-plane/tests/test_course_intake_api.py -q`

Expected: FAIL with route not found.

- [ ] **Step 3: Implement intake service**

Store files under `{data_dir}/courses/{course_id}/assets/{asset_id}{suffix}` using streamed reads, compute SHA-256 during write, reject path traversal and empty files, create database rows in one transaction, and delete newly written files if the transaction fails.

- [ ] **Step 4: Verify API behavior**

Run: `uv run --project services/control-plane pytest services/control-plane/tests/test_course_intake_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add services/control-plane/app/main.py services/control-plane/app/services/course_intake_service.py services/control-plane/tests/test_course_intake_api.py && git commit -m "feat: add normalized course intake API"`

### Task 3: DingTalk role mapping and client

**Files:**
- Modify: `connectors/dingtalk/dingtalk_connector/intake.py`
- Modify: `connectors/dingtalk/dingtalk_connector/main.py`
- Modify: `connectors/dingtalk/dingtalk_connector/control_plane.py`
- Modify: `connectors/dingtalk/tests/test_intake.py`

**Interfaces:**
- Produces: `DingTalkFile.role: str`, `DingTalkFile.rights_status: str`
- Consumes: `POST /api/courses/intake`

- [ ] **Step 1: Add failing connector tests**

Cover explicit tags `#教程`, `#案例`, `#素材`, default-to-material behavior, mixed attachment events, no implicit rights confirmation, and duplicate message handling.

- [ ] **Step 2: Verify failure**

Run: `uv run --project connectors/dingtalk pytest connectors/dingtalk/tests/test_intake.py -q`

Expected: FAIL because role metadata is absent.

- [ ] **Step 3: Implement mapping and normalized request**

Parse tags from message text without trusting filenames, attach roles to every downloaded file, and change the client call from task creation to course intake. Preserve sender/conversation/message provenance and current MIME/size validation.

- [ ] **Step 4: Verify connector tests**

Run: `uv run --project connectors/dingtalk pytest connectors/dingtalk/tests/test_intake.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add connectors/dingtalk && git commit -m "feat: ingest DingTalk course attachments"`

### Task 4: Development fixture and audit documentation

**Files:**
- Create: `fixtures/dingtalk/course-event.json`
- Create: `scripts/simulate-dingtalk-course.py`
- Modify: `docs/runbooks/dingtalk.md`
- Modify: `scripts/verify.ps1`
- Test: `services/control-plane/tests/test_dingtalk_fixture_contract.py`

**Interfaces:**
- Consumes: `POST /api/courses/intake`
- Produces: CLI `python scripts/simulate-dingtalk-course.py --base-url URL --fixture PATH`

- [ ] **Step 1: Write failing fixture contract test**

Assert the fixture contains no credentials, names at least one tutorial/reference/material file, and the CLI refuses non-loopback targets unless `--allow-remote` is explicitly present.

- [ ] **Step 2: Verify failure**

Run: `uv run --project services/control-plane pytest services/control-plane/tests/test_dingtalk_fixture_contract.py -q`

Expected: FAIL because fixture and CLI do not exist.

- [ ] **Step 3: Implement fixture CLI**

Load the fixture, open local files, submit the normalized multipart request, print only course ID/status/counts, and never print request headers or file bytes.

- [ ] **Step 4: Verify and smoke-test**

Run: `uv run --project services/control-plane pytest services/control-plane/tests/test_dingtalk_fixture_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add fixtures/dingtalk scripts/simulate-dingtalk-course.py docs/runbooks/dingtalk.md scripts/verify.ps1 services/control-plane/tests/test_dingtalk_fixture_contract.py && git commit -m "test: add DingTalk course intake fixture"`

