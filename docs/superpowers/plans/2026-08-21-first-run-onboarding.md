# First-Run Setup Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an in-app first-run assistant that makes local video creation immediately usable and guides optional account integrations without exposing credentials.

**Architecture:** Add a focused `SetupService` that persists only non-secret onboarding preferences and aggregates runtime/integration facts into provider cards. FastAPI exposes the setup page and status/preferences APIs; a framework-free responsive UI renders the wizard and links back into the existing workbench. Existing provider clients remain the source of truth for connectivity.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, pytest, Jinja2, vanilla JavaScript, existing CSS design system.

## Global Constraints

- A fresh clone must allow local upload, analysis, editing, captions, preview, and Jianying draft generation without `.env`.
- External providers are optional enhancements and must never block local mode.
- No API key, secret, cookie, OAuth token, or unmasked credential may appear in Git, API reads, HTML, browser storage, or logs.
- macOS and Windows use the same setup flow; path discovery stays platform-specific behind existing runtime APIs.
- Do not claim a third-party connection is successful without a provider-backed diagnostic.

---

### Task 1: Setup state service

**Files:**
- Create: `services/control-plane/app/services/setup_service.py`
- Test: `services/control-plane/tests/test_setup_service.py`

**Interfaces:**
- Consumes: `Settings.data_dir: Path`, runtime and integration dictionaries from existing services.
- Produces: `SetupService.preferences() -> dict`, `SetupService.update_preferences(local_mode_confirmed: bool) -> dict`, and `SetupService.status(runtime: dict, integrations: dict, materials: dict) -> dict`.

- [ ] **Step 1: Write failing service tests**

```python
def test_fresh_setup_keeps_external_providers_optional(tmp_path):
    service = SetupService(tmp_path)
    result = service.status(runtime=ready_runtime(), integrations={}, materials={})
    assert result["local_mode"]["ready"] is True
    assert result["local_mode"]["confirmed"] is False
    assert all(card["required"] is False for card in result["providers"])

def test_preferences_round_trip_without_secrets(tmp_path):
    service = SetupService(tmp_path)
    saved = service.update_preferences(local_mode_confirmed=True)
    assert saved == {"local_mode_confirmed": True}
    assert "key" not in (tmp_path / "setup-preferences.json").read_text().lower()
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run --project services/control-plane pytest services/control-plane/tests/test_setup_service.py -q`

Expected: import failure for `app.services.setup_service`.

- [ ] **Step 3: Implement minimal service**

Implement an atomic JSON preference store under `Settings.data_dir / "setup-preferences.json"`. Return four provider cards with stable IDs `volcengine`, `materials`, `douyin`, and `dingtalk`; each card includes `required=False`, local fallback copy, official URL, field labels, status, reason, and next action. Compute progress from local readiness plus configured optional providers, while reporting local usability separately from enhancement completion.

- [ ] **Step 4: Run service tests and confirm GREEN**

Run: `uv run --project services/control-plane pytest services/control-plane/tests/test_setup_service.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/control-plane/app/services/setup_service.py services/control-plane/tests/test_setup_service.py
git commit -m "feat: add first-run setup state service"
```

### Task 2: Setup API and first-run routing

**Files:**
- Modify: `services/control-plane/app/main.py`
- Create: `services/control-plane/app/schemas/setup.py`
- Create: `services/control-plane/tests/test_setup_api.py`
- Modify: `services/control-plane/tests/test_workbench.py`

**Interfaces:**
- Consumes: `SetupService` from Task 1 and the existing runtime/integration/material status builders.
- Produces: `GET /setup`, `GET /api/setup/status`, `PUT /api/setup/preferences`, `POST /api/setup/validate/{provider}`, and conditional redirect from `GET /`.

- [ ] **Step 1: Write failing API and routing tests**

```python
def test_fresh_home_redirects_to_setup(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/setup"

def test_confirmed_local_mode_opens_workbench(client):
    saved = client.put("/api/setup/preferences", json={"local_mode_confirmed": True})
    assert saved.status_code == 200
    assert client.get("/").status_code == 200

def test_setup_status_never_returns_credentials(client):
    response = client.get("/api/setup/status")
    assert response.status_code == 200
    lowered = response.text.lower()
    assert "client_secret" not in lowered
    assert "access_token" not in lowered
    assert "api_key" not in lowered

def test_provider_validation_returns_stable_diagnostic(client):
    response = client.post("/api/setup/validate/materials")
    assert response.status_code == 200
    assert response.json()["status"] in {"configured", "partially_configured", "not_configured"}
```

- [ ] **Step 2: Run API tests and confirm RED**

Run: `uv run --project services/control-plane pytest services/control-plane/tests/test_setup_api.py services/control-plane/tests/test_workbench.py -q`

Expected: `/setup` and setup APIs return 404; home returns 200 before confirmation.

- [ ] **Step 3: Add schemas and routes**

Create `SetupPreferencesUpdate(BaseModel)` with `local_mode_confirmed: bool`. Extract existing runtime, integration and materials response assembly into local helper functions in `create_app` so both old endpoints and `SetupService` consume identical facts. `POST /api/setup/validate/{provider}` recomputes and returns the selected card; unknown IDs return `404` with `code=unknown_setup_provider`. Use `RedirectResponse(url="/setup", status_code=307)` only when preferences are unconfirmed.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `uv run --project services/control-plane pytest services/control-plane/tests/test_setup_api.py services/control-plane/tests/test_workbench.py services/control-plane/tests/test_local_runtime_api.py services/control-plane/tests/test_material_library_api.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/control-plane/app/main.py services/control-plane/app/schemas/setup.py services/control-plane/tests/test_setup_api.py services/control-plane/tests/test_workbench.py
git commit -m "feat: route fresh installs through setup"
```

### Task 3: Responsive setup wizard UI

**Files:**
- Create: `services/control-plane/app/templates/setup.html`
- Create: `services/control-plane/app/static/setup.css`
- Create: `services/control-plane/app/static/setup.js`
- Modify: `services/control-plane/app/templates/_app_nav.html`
- Test: `services/control-plane/tests/test_setup_page.py`

**Interfaces:**
- Consumes: `GET /api/setup/status` and `PUT /api/setup/preferences` from Task 2.
- Produces: accessible four-step UI, provider guidance cards, retry buttons, and “use local mode now” action.

- [ ] **Step 1: Write failing page contract tests**

```python
def test_setup_page_contains_local_first_flow(client):
    page = client.get("/setup")
    assert page.status_code == 200
    assert "本地模式现在就能用" in page.text
    assert 'id="setup-provider-list"' in page.text
    assert 'id="confirm-local-mode"' in page.text
    assert "/static/setup.js" in page.text

def test_setup_assets_are_served(client):
    assert client.get("/static/setup.css").status_code == 200
    script = client.get("/static/setup.js")
    assert script.status_code == 200
    assert "/api/setup/status" in script.text
```

- [ ] **Step 2: Run page tests and confirm RED**

Run: `uv run --project services/control-plane pytest services/control-plane/tests/test_setup_page.py -q`

Expected: setup page lacks required contract or assets return 404.

- [ ] **Step 3: Implement the setup page**

Render runtime checks, a prominent local-ready panel, optional provider cards, official links, required field labels, fallback behavior and diagnostics. Each retry button calls `POST /api/setup/validate/${providerId}` and replaces only that card's status and next-action copy. The local button calls:

```javascript
await api("/api/setup/preferences", {
  method: "PUT",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ local_mode_confirmed: true }),
});
window.location.assign("/");
```

Provider cards must never render secret inputs in this first increment; Volcengine links to the existing encrypted cloud-usage settings page, while the remaining cards link to official application pages and in-repo runbook sections. Add “配置助手” to desktop and mobile navigation.

- [ ] **Step 4: Run page tests and JavaScript syntax check**

Run: `uv run --project services/control-plane pytest services/control-plane/tests/test_setup_page.py -q`

Run: `node --check services/control-plane/app/static/setup.js`

Expected: tests pass and Node exits 0.

- [ ] **Step 5: Commit**

```bash
git add services/control-plane/app/templates/setup.html services/control-plane/app/static/setup.css services/control-plane/app/static/setup.js services/control-plane/app/templates/_app_nav.html services/control-plane/tests/test_setup_page.py
git commit -m "feat: add guided setup interface"
```

### Task 4: Workbench progress, docs, and fresh-clone contract

**Files:**
- Modify: `services/control-plane/app/templates/workbench.html`
- Modify: `services/control-plane/app/static/workbench.js`
- Modify: `services/control-plane/tests/test_workbench.py`
- Modify: `scripts/verify-fresh-clone.py`
- Modify: `README.md`
- Modify: `docs/user-required-actions.md`

**Interfaces:**
- Consumes: setup status and UI from Tasks 1-3.
- Produces: visible setup completion entry on the workbench and an automated fresh-clone check for the no-`.env` local path.

- [ ] **Step 1: Extend failing contracts**

Add this workbench assertion after the test client confirms local mode:

```python
page = client.get("/")
assert page.status_code == 200
assert 'id="setup-progress"' in page.text
assert 'href="/setup"' in page.text
```

Extend the isolated fresh-clone verifier with the exact HTTP sequence:

```python
setup_page = urlopen(f"{base_url}/setup", timeout=10)
assert setup_page.status == 200
request = Request(
    f"{base_url}/api/setup/preferences",
    data=json.dumps({"local_mode_confirmed": True}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="PUT",
)
assert urlopen(request, timeout=10).status == 200
assert urlopen(f"{base_url}/", timeout=10).status == 200
```

- [ ] **Step 2: Run contracts and confirm RED**

Run: `uv run --project services/control-plane pytest services/control-plane/tests/test_workbench.py services/control-plane/tests/test_repo_bootstrap_contract.py -q`

Expected: missing setup progress or verifier behavior.

- [ ] **Step 3: Implement workbench and documentation updates**

Add a compact setup-progress link to the connection strip. Replace README’s scattered optional integration list with a single instruction: start locally, follow `/setup`, and only authorize services the user needs. Keep a table distinguishing automatic local capabilities from account-bound approvals.

- [ ] **Step 4: Run full verification**

Run: `uv run --project services/control-plane pytest services/control-plane/tests -q`

Run: `node --check services/control-plane/app/static/setup.js && node --check services/control-plane/app/static/workbench.js`

Run: `python scripts/verify-fresh-clone.py`

Expected: zero failures; verifier reports setup page reachable, local confirmation saved, home reachable, and real home unchanged.

- [ ] **Step 5: Commit and push**

```bash
git add README.md docs/user-required-actions.md scripts/verify-fresh-clone.py services/control-plane/app/templates/workbench.html services/control-plane/app/static/workbench.js services/control-plane/tests/test_workbench.py services/control-plane/tests/test_repo_bootstrap_contract.py
git commit -m "docs: make guided setup the default start path"
git push
```
