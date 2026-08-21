# Project Recovery and Task Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the current worktree, eliminate the scheduler test race, and make historical validation tasks recoverably invisible by default.

**Architecture:** Add an explicit scheduler runtime switch and a recoverable task archive field. Keep migration compatibility with the existing SQLite database and expose archive/restore through focused service and HTTP interfaces.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, SQLite, pytest, vanilla JavaScript.

## Global Constraints

- Existing task rows and artifacts must not be deleted.
- Tests must never start the daily scheduler.
- The default task query hides archived rows; `include_archived=true` reveals them.
- Every behavior change follows a red-green test cycle.

---

### Task 1: Disable Daily Scheduler in Tests

**Files:**
- Modify: `services/control-plane/app/config.py`
- Modify: `services/control-plane/app/main.py`
- Modify: `services/control-plane/tests/conftest.py`
- Test: `services/control-plane/tests/test_scheduler_lifecycle.py`

**Interfaces:**
- Consumes: `Settings` environment loading.
- Produces: `settings.automation_scheduler_enabled: bool` and a lifespan that starts the scheduler only when true.

- [ ] **Step 1: Write the failing lifecycle test**

```python
def test_test_client_does_not_start_scheduler(client, monkeypatch):
    assert client.app.state.automation_scheduler_started is False
```

- [ ] **Step 2: Run the test and confirm the state is absent or true**

Run: `pytest services/control-plane/tests/test_scheduler_lifecycle.py -v`

Expected: FAIL because the explicit scheduler-started state is not implemented.

- [ ] **Step 3: Add the runtime switch and lifecycle state**

```python
automation_scheduler_enabled: bool = True

app.state.automation_scheduler_started = False
if settings.automation_scheduler_enabled:
    automation_scheduler.start()
    app.state.automation_scheduler_started = True
```

Set `AUTOMATION_SCHEDULER_ENABLED=false` before importing the app in the test fixture.

- [ ] **Step 4: Run lifecycle and original regression tests**

Run: `pytest services/control-plane/tests/test_scheduler_lifecycle.py services/control-plane/tests/test_review.py::test_approval_writes_immutable_audit_event -v`

Expected: both tests PASS repeatedly without a temporary-directory collision.

- [ ] **Step 5: Record the checkpoint**

Run: `git diff --check`

Expected: no whitespace errors.

### Task 2: Recoverable Task Archive

**Files:**
- Modify: `services/control-plane/app/models/task.py`
- Modify: `services/control-plane/app/schemas/task.py`
- Modify: `services/control-plane/app/services/task_service.py`
- Modify: `services/control-plane/app/main.py`
- Test: `services/control-plane/tests/test_task_archive.py`

**Interfaces:**
- Consumes: existing task IDs and list endpoint.
- Produces: `Task.archived_at`, `Task.archive_reason`, `POST /api/tasks/{task_id}/archive`, `POST /api/tasks/{task_id}/restore`, `GET /api/tasks?include_archived=true`.

- [ ] **Step 1: Write archive behavior tests**

```python
def test_archived_task_is_hidden_and_can_be_restored(client, task_factory):
    task = task_factory(title="素材上传验证")
    assert client.post(f"/api/tasks/{task.id}/archive", json={"reason": "validation"}).status_code == 200
    assert str(task.id) not in {row["id"] for row in client.get("/api/tasks").json()}
    archived = client.get("/api/tasks?include_archived=true").json()
    assert str(task.id) in {row["id"] for row in archived}
    assert client.post(f"/api/tasks/{task.id}/restore").status_code == 200
```

- [ ] **Step 2: Run the archive test**

Run: `pytest services/control-plane/tests/test_task_archive.py -v`

Expected: FAIL because archive endpoints and fields do not exist.

- [ ] **Step 3: Implement compatible migration and service methods**

Use nullable `archived_at` and `archive_reason` columns, add startup `ALTER TABLE` guards for an existing SQLite database, and implement idempotent `archive_task()` / `restore_task()` methods.

- [ ] **Step 4: Run task API tests**

Run: `pytest services/control-plane/tests/test_task_archive.py services/control-plane/tests/test_tasks.py -v`

Expected: PASS with archived rows hidden only from the default list.

- [ ] **Step 5: Archive historical validation rows using the HTTP API**

Archive only rows whose titles explicitly contain `验证`, `验收`, or `端到端` and whose creation date precedes 2026-08-21. Record reason `historical_validation`; do not archive daily automation tasks.

### Task 3: Task Archive UI and Recovery Documentation

**Files:**
- Modify: `services/control-plane/app/static/index.html`
- Modify: `services/control-plane/app/static/app.js`
- Modify: `services/control-plane/app/static/styles.css`
- Create: `AGENTS.md`
- Modify: `docs/progress.md`
- Test: `services/control-plane/tests/test_static_console.py`

**Interfaces:**
- Consumes: archive HTTP endpoints.
- Produces: “查看归档”, “归档”, and “恢复” controls with visible counts.

- [ ] **Step 1: Add a failing static contract test**

```python
def test_console_contains_archive_controls():
    html = Path("services/control-plane/app/static/index.html").read_text(encoding="utf-8")
    js = Path("services/control-plane/app/static/app.js").read_text(encoding="utf-8")
    assert "查看归档" in html
    assert "include_archived" in js
    assert "/restore" in js
```

- [ ] **Step 2: Run the static contract test**

Run: `pytest services/control-plane/tests/test_static_console.py::test_console_contains_archive_controls -v`

Expected: FAIL because the controls are absent.

- [ ] **Step 3: Implement the minimal UI**

Add a single toggle beside the task count. In normal mode show an archive action; in archive mode show restore. Preserve current responsive layout and never delete tasks.

- [ ] **Step 4: Update recoverability documents**

`AGENTS.md` must contain the canonical worktree path, startup command, test command, data directories, secret-handling rule, and “do not delete tasks/artifacts” rule. `docs/progress.md` must begin with Outcome, Confirmed, Open, and Next Action sections dated 2026-08-21.

- [ ] **Step 5: Verify the recovery slice**

Run: `pytest services/control-plane/tests/test_scheduler_lifecycle.py services/control-plane/tests/test_task_archive.py services/control-plane/tests/test_static_console.py -v`

Expected: all selected tests PASS.
