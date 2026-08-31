# Capability and Configuration Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a fresh clone self-explanatory by documenting and displaying exactly which editing functions need no Key, which are optional enhancements, and which require external authorization.

**Architecture:** Store the static capability contract in one package-local JSON catalog, expose it through the existing setup status API, and render it in the setup assistant. Keep live provider diagnostics separate from the static contract. Add a human guide and a Codex operator guide that use the same IDs, tiers, configuration names, fallbacks, and safety boundaries.

**Tech Stack:** FastAPI, Python 3.11, Pydantic settings, vanilla JavaScript/CSS, pytest, Markdown, JSON.

## Global Constraints

- The local editing baseline must run without `.env`, Dify, Volcengine, Douyin, DingTalk, Pexels, Pixabay, or Seedance credentials.
- Never return, print, document, or commit real secrets.
- OAuth, platform approval, paid-service activation, system permissions, and opening Jianying once remain explicit user actions.
- Jianying delivery means draft generation and safe import; it does not claim automatic export on unsupported Jianying versions.
- Static capability facts must have one machine-readable source of truth.

---

### Task 1: Define the capability contract with failing tests

**Files:**
- Modify: `services/control-plane/tests/test_setup_service.py`
- Modify: `services/control-plane/tests/test_setup_api.py`
- Modify: `services/control-plane/tests/test_setup_page.py`

**Interfaces:**
- Consumes: existing `SetupService.status(...)` and `/api/setup/status`.
- Produces: expected `capabilities` array with `tier`, `requires`, `fallback`, `data_boundary`, and `docs_url` fields.

- [ ] **Step 1: Write the failing service assertions**

Add assertions that the result contains all three tiers (`local_no_key`, `optional_key`, `external_authorization`), at least five local capabilities, and that every item has a non-empty fallback and documentation URL.

- [ ] **Step 2: Write the failing API security assertions**

Assert the setup API exposes capability IDs but still contains no `client_secret`, `access_token`, or `api_key` field names.

- [ ] **Step 3: Write the failing page assertions**

Assert the HTML contains `id="setup-capability-list"`, the text `本地剪辑无需 Key`, and a link to `/docs/capabilities-and-configuration`.

- [ ] **Step 4: Run focused tests and confirm RED**

Run:

```powershell
uv run --project services/control-plane --extra test pytest services/control-plane/tests/test_setup_service.py services/control-plane/tests/test_setup_api.py services/control-plane/tests/test_setup_page.py -q
```

Expected: failures because `capabilities` and the new page section do not exist.

### Task 2: Add one machine-readable capability catalog

**Files:**
- Create: `services/control-plane/app/capability_catalog.json`
- Create: `services/control-plane/app/services/capability_catalog_service.py`
- Modify: `services/control-plane/app/services/setup_service.py`

**Interfaces:**
- Produces: `CapabilityCatalogService.list() -> list[dict[str, object]]`.
- Produces: `SetupService.status(...)["capabilities"]`.

- [ ] **Step 1: Create the JSON catalog**

Define local intake/analysis/editing/audio/quality-draft, Volcengine ASR/TTS/usage, Dify, public materials, Seedance, Douyin search/publish, DingTalk, and remote deployment. Each item contains `id`, `name`, `tier`, `summary`, `features`, `requires`, `fallback`, `data_boundary`, and `docs_url`.

- [ ] **Step 2: Implement strict loading**

Load with `Path(__file__).resolve().parents[1] / "capability_catalog.json"`, reject duplicate IDs or unsupported tiers, and return fresh dictionaries so callers cannot mutate cached state.

- [ ] **Step 3: Expose the catalog from setup status**

Instantiate the catalog service in `SetupService.__init__` and include `capabilities` in `status()` without adding any credential values.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run the Task 1 command. Expected: service and API assertions pass; page remains red until Task 3.

### Task 3: Render the capability center in the setup assistant

**Files:**
- Modify: `services/control-plane/app/templates/setup.html`
- Modify: `services/control-plane/app/static/setup.js`
- Modify: `services/control-plane/app/static/setup.css`
- Modify: `services/control-plane/tests/test_setup_page.py`

**Interfaces:**
- Consumes: `status.capabilities`.
- Produces: three grouped, responsive capability sections and a human-guide link.

- [ ] **Step 1: Add semantic page structure**

Add a section headed `本地剪辑无需 Key`, an explanatory paragraph, `id="setup-capability-list"`, and a guide link.

- [ ] **Step 2: Render grouped cards safely**

Add escaped rendering for tier labels, supported features, required configuration, fallback, and data boundary. Do not render secret values or accept credential input.

- [ ] **Step 3: Add responsive styles**

Use the existing design tokens, `auto-fit` grids, wrapping text, and mobile single-column behavior without introducing fixed widths that can overflow 390 px.

- [ ] **Step 4: Run page tests and JavaScript syntax**

Run:

```powershell
uv run --project services/control-plane --extra test pytest services/control-plane/tests/test_setup_page.py -q
node --check services/control-plane/app/static/setup.js
```

Expected: all pass with exit code 0.

### Task 4: Write human-readable and Codex-readable guides

**Files:**
- Create: `docs/capabilities-and-configuration.md`
- Create: `docs/codex-operator-guide.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `.env.example`
- Modify: `docs/user-required-actions.md`
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: IDs and facts from `capability_catalog.json`.
- Produces: one human decision guide and one agent operating contract.

- [ ] **Step 1: Write the human guide**

Explain the end-to-end editing chain, exact outputs, three-tier matrix, every environment variable group, fallback behavior, privacy/data movement, costs, first-use model downloads, Jianying boundary, and task recipes for no-Key/local-production/cloud-enhanced/platform-delivery modes.

- [ ] **Step 2: Write the Codex operator guide**

Define discovery order, bootstrap commands for macOS/Windows, never-request-secret rules, capability decision tree, environment-variable-to-feature mapping, user-only actions, diagnostics, evidence requirements, and completion wording.

- [ ] **Step 3: Align entry documents**

Put the zero-Key statement and links near the top of README; make `AGENTS.md` require reading the operator guide; group `.env.example` by optional capability and clarify all values are blank by default.

- [ ] **Step 4: Update state and user-action boundaries**

Record the documentation/capability center as Confirmed in `docs/progress.md`; keep platform approval and credentials External in `docs/user-required-actions.md`.

- [ ] **Step 5: Validate links and catalog terminology**

Search for every capability ID and ensure no document calls an optional enhancement mandatory for local editing.

### Task 5: Full verification and clone readiness

**Files:**
- Verify only: repository worktree.

**Interfaces:**
- Consumes: completed implementation and documentation.
- Produces: fresh evidence for handoff.

- [ ] **Step 1: Run full tests**

```powershell
$env:VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED='false'
uv run --project services/control-plane --extra test pytest services/control-plane/tests -q
```

Expected: zero failures.

- [ ] **Step 2: Run static checks**

```powershell
node --check services/control-plane/app/static/setup.js
node --check services/control-plane/app/static/workbench.js
git diff --check
```

Expected: exit code 0.

- [ ] **Step 3: Run fresh-clone verification**

```powershell
python scripts/verify-fresh-clone.py --dry-run
```

Expected: JSON with `status=ok`, `setup_smoke=passed`, and `real_home_modified=false`.

- [ ] **Step 4: Review tracked files and secrets**

Confirm `.env`, generated media, runtime data, model caches, credentials, and browser state remain untracked.

- [ ] **Step 5: Commit the implementation**

```powershell
git add .env.example AGENTS.md README.md docs services/control-plane/app services/control-plane/tests
git commit -m "feat: explain editing capabilities and optional configuration"
```
