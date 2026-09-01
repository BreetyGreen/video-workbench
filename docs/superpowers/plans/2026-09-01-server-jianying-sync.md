# Server and Jianying Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the product as a durable server service and deliver completed Jianying packages to paired Windows or macOS devices through a lightweight sync helper.

**Architecture:** Production Compose separates API, worker, PostgreSQL, Redis, object storage, DingTalk connector, and Caddy. A local sync helper pairs with a one-time code, long-polls signed pending packages, verifies checksums, imports a new draft into a discovered Jianying/CapCut directory, and launches the editor.

**Tech Stack:** Docker Compose, FastAPI, PostgreSQL 16, Redis 7, MinIO, Caddy 2.10, Python 3.11, PyInstaller, Windows PowerShell, macOS launchd

## Global Constraints

- No Codex dependency at runtime.
- Server credentials and device tokens are stored outside Git and displayed only once where required.
- Pairing codes expire after ten minutes and are single-use.
- Delivery packages are signed and checksum-verified before extraction.
- Archive extraction rejects absolute paths, `..`, symlinks, and files outside the staging directory.
- Import always creates a new draft and never overwrites an existing Jianying project.
- Windows and macOS discovery support custom locations and persist the user-confirmed path.
- DingTalk application binaries target `B:\Apps\DingTalk`; unavoidable per-user profile/cache files may remain under Windows AppData.

---

### Task 1: Delivery device and package API

**Files:**
- Modify: `services/control-plane/app/models.py`
- Create: `services/control-plane/app/services/device_delivery_service.py`
- Modify: `services/control-plane/app/main.py`
- Test: `services/control-plane/tests/test_device_delivery_api.py`

**Interfaces:**
- Produces: `POST /api/devices/pairing-codes`, `POST /api/devices/pair`, `GET /api/devices/{device_id}/deliveries/pending`, `GET /api/deliveries/{delivery_id}/package`, `POST /api/deliveries/{delivery_id}/result`

- [ ] **Step 1: Write failing tests** for expiring single-use pairing, hashed bearer tokens, device scoping, signed package metadata, success/failure callbacks, and token redaction.
- [ ] **Step 2: Run** `uv run --project services/control-plane pytest services/control-plane/tests/test_device_delivery_api.py -q`; expect route failures.
- [ ] **Step 3: Implement `DeliveryDevice`, `PairingCode`, `DeliveryPackage` and service/routes**; return tokens only from successful pair response and store only hashes.
- [ ] **Step 4: Re-run tests** and expect PASS.
- [ ] **Step 5: Commit** with `git commit -m "feat: add paired-device delivery API"`.

### Task 2: Cross-platform sync helper

**Files:**
- Create: `sync-helper/pyproject.toml`
- Create: `sync-helper/video_workbench_sync/main.py`
- Create: `sync-helper/video_workbench_sync/client.py`
- Create: `sync-helper/video_workbench_sync/importer.py`
- Create: `sync-helper/video_workbench_sync/platforms.py`
- Create: `sync-helper/tests/test_importer.py`
- Create: `sync-helper/tests/test_client.py`

**Interfaces:**
- Produces: CLI `video-workbench-sync pair|run|doctor`
- Consumes: paired-device delivery API

- [ ] **Step 1: Write failing helper tests** for Windows/macOS discovery, safe extraction, checksum/signature failure, collision-safe draft naming, callback, and editor launch command construction.
- [ ] **Step 2: Run** `uv run --project sync-helper pytest sync-helper/tests -q`; expect import failures.
- [ ] **Step 3: Implement client/importer/platform adapters** with a staging directory, atomic rename, OS keyring when available and permission-restricted token file fallback.
- [ ] **Step 4: Re-run tests** and expect PASS.
- [ ] **Step 5: Commit** with `git commit -m "feat: add Jianying delivery sync helper"`.

### Task 3: Helper packaging and installers

**Files:**
- Create: `sync-helper/build.ps1`
- Create: `sync-helper/build.sh`
- Create: `sync-helper/install-windows.ps1`
- Create: `sync-helper/install-macos.sh`
- Create: `sync-helper/com.video-workbench.sync.plist`
- Create: `.github/workflows/sync-helper-release.yml`
- Test: `services/control-plane/tests/test_sync_helper_packaging.py`

**Interfaces:**
- Produces: signed-release-ready Windows `.exe` and macOS universal app/CLI archives

- [ ] **Step 1: Write failing packaging contract tests** for pinned PyInstaller, launchd template, Windows startup registration, architecture matrix, checksum generation, and no embedded server token.
- [ ] **Step 2: Run** `uv run --project services/control-plane pytest services/control-plane/tests/test_sync_helper_packaging.py -q`; expect missing files.
- [ ] **Step 3: Implement packaging/install scripts**; unsigned local builds must clearly state that code signing/notarization is required before public distribution.
- [ ] **Step 4: Re-run contract tests and local helper build**; expect PASS and executable `doctor` output.
- [ ] **Step 5: Commit** with `git commit -m "build: package Jianying sync helper"`.

### Task 4: Production Compose topology

**Files:**
- Modify: `deploy/compose.production.yml`
- Modify: `deploy/compose.yml`
- Create: `services/worker/Dockerfile`
- Create: `services/worker/pyproject.toml`
- Create: `services/worker/worker/main.py`
- Modify: `.env.example`
- Modify: `docs/deployment.md`
- Test: `services/control-plane/tests/test_server_topology.py`

**Interfaces:**
- Produces: API, worker, PostgreSQL, Redis, MinIO, DingTalk, Caddy services with health checks and durable volumes

- [ ] **Step 1: Write failing topology tests** that parse rendered Compose config and assert service names, dependencies, health checks, named volumes, internal-only data ports, secret env requirements, and backup targets.
- [ ] **Step 2: Run** `uv run --project services/control-plane pytest services/control-plane/tests/test_server_topology.py -q`; expect topology mismatch.
- [ ] **Step 3: Implement production topology and worker queue**; worker consumes course-process/edit-job IDs and delegates to control-plane service code.
- [ ] **Step 4: Run** `docker compose -f deploy/compose.yml -f deploy/compose.production.yml config` and the focused tests; expect success.
- [ ] **Step 5: Commit** with `git commit -m "feat: add durable server worker topology"`.

### Task 5: Backup, restore, and server acceptance

**Files:**
- Modify: `scripts/deploy-server.ps1`
- Modify: `scripts/backup-server.ps1`
- Create: `scripts/restore-server.ps1`
- Create: `scripts/verify-server.ps1`
- Modify: `docs/user-required-actions.md`
- Test: `services/control-plane/tests/test_server_operations_contract.py`

**Interfaces:**
- Produces: repeatable deploy, backup, restore, and health verification commands

- [ ] **Step 1: Write failing operations tests** for explicit target directories, backup manifest/checksum, restore dry-run, and refusal to operate on empty/root targets.
- [ ] **Step 2: Run** `uv run --project services/control-plane pytest services/control-plane/tests/test_server_operations_contract.py -q`; expect failure.
- [ ] **Step 3: Implement safe operations scripts** with validated absolute paths, no destructive defaults, database/object-store backup, and post-restore health checks.
- [ ] **Step 4: Run focused tests and `scripts/verify-server.ps1` against local Compose**; expect all services healthy.
- [ ] **Step 5: Commit** with `git commit -m "ops: complete server backup and restore"`.

### Task 6: DingTalk B-drive installation and smoke test

**Files:**
- Modify: `docs/runbooks/dingtalk.md`
- Create: `scripts/doctor-dingtalk.ps1`
- Test: `services/control-plane/tests/test_dingtalk_install_contract.py`

**Interfaces:**
- Produces: local installation evidence and diagnostic command without capturing credentials

- [ ] **Step 1: Write failing contract tests** for `B:\Apps\DingTalk` default, Authenticode verification guidance, process/version reporting, and AppData caveat.
- [ ] **Step 2: Run** `uv run --project services/control-plane pytest services/control-plane/tests/test_dingtalk_install_contract.py -q`; expect missing doctor.
- [ ] **Step 3: Download only from the official DingTalk download page, verify publisher/signature and SHA-256, install binaries to `B:\Apps\DingTalk`, and implement the read-only doctor script.**
- [ ] **Step 4: Launch once and run doctor**; expect detected install path/version/process state without secrets.
- [ ] **Step 5: Commit documentation and doctor** with `git commit -m "docs: verify DingTalk B-drive installation"`.

