# Unified Console Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the workbench, cloud-usage settings page, and task review page one consistent top navigation and deterministic return-to-workbench actions.

**Architecture:** Add a single Jinja partial for navigation and a single shared stylesheet, then include them from all three existing templates. Keep page-specific layout styles intact and add a static Access Key guidance card only to the settings page.

**Tech Stack:** FastAPI, Jinja2, HTML, CSS, pytest/TestClient

## Global Constraints

- All return links point to `/`; do not use browser history.
- Do not change task, review, credential-save, or cloud-query APIs.
- The settings guide must direct users to the existing `video-usage-monitor` Access Key and explicitly say not to create an API Key.
- Mobile navigation must preserve the Workbench and Cloud Usage entries.

---

### Task 1: Shared navigation contract

**Files:**
- Create: `services/control-plane/app/templates/_app_nav.html`
- Create: `services/control-plane/app/static/app_nav.css`
- Modify: `services/control-plane/tests/test_workbench.py`
- Modify: `services/control-plane/tests/test_cloud_usage_api.py`
- Modify: `services/control-plane/tests/test_review.py`

**Interfaces:**
- Consumes: Jinja variable `nav_active` with values `workbench`, `cloud_usage`, or `review`.
- Produces: `<nav aria-label="主导航">` with deterministic links to `/` and `/settings/cloud-usage`.

- [ ] **Step 1: Write failing page contract tests**

```python
assert 'aria-label="主导航"' in response.text
assert 'href="/"' in response.text
assert 'href="/settings/cloud-usage"' in response.text
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_workbench.py tests/test_cloud_usage_api.py::test_cloud_usage_settings_page_exists tests/test_review.py::test_review_page_displays_video_copy_evidence_and_warnings -q`

Expected: FAIL because the settings and review pages do not contain the shared navigation contract.

- [ ] **Step 3: Implement the partial and responsive stylesheet**

```html
<header class="app-topbar">
  <a class="app-brand" href="/">视频生产控制台</a>
  <nav aria-label="主导航">
    <a href="/" aria-current="{{ 'page' if nav_active == 'workbench' else 'false' }}">工作台</a>
    <a href="/settings/cloud-usage" aria-current="{{ 'page' if nav_active == 'cloud_usage' else 'false' }}">云端余量</a>
  </nav>
</header>
```

Include the complete partial in all three templates and load `/static/app_nav.css` after each page stylesheet so the shared navigation rules win consistently.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_workbench.py tests/test_cloud_usage_api.py::test_cloud_usage_settings_page_exists tests/test_review.py::test_review_page_displays_video_copy_evidence_and_warnings -q`

Expected: PASS.

### Task 2: Settings guidance and page-level return actions

**Files:**
- Modify: `services/control-plane/app/templates/cloud_usage_settings.html`
- Modify: `services/control-plane/app/templates/review.html`
- Modify: `services/control-plane/app/static/workbench.css`
- Modify: `services/control-plane/app/static/review.css`
- Test: `services/control-plane/tests/test_cloud_usage_api.py`
- Test: `services/control-plane/tests/test_review.py`

**Interfaces:**
- Consumes: the shared navigation from Task 1.
- Produces: a settings instruction card and deterministic `返回工作台` links.

- [ ] **Step 1: Extend failing assertions for the guidance copy**

```python
assert "video-usage-monitor" in response.text
assert "不要创建 API Key" in response.text
assert "返回工作台" in response.text
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_cloud_usage_api.py::test_cloud_usage_settings_page_exists tests/test_review.py::test_review_page_displays_video_copy_evidence_and_warnings -q`

Expected: FAIL on the missing guidance and review return action.

- [ ] **Step 3: Add explicit instructions and deterministic links**

Add an ordered list that routes `用户管理 → 用户 → video-usage-monitor → 密钥`, identifies Access Key ID and Secret Access Key, warns `不要创建 API Key`, and tells the user to rotate the sub-user key if its secret is no longer visible. Add `href="/"` return actions to settings and review title areas.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_cloud_usage_api.py::test_cloud_usage_settings_page_exists tests/test_review.py::test_review_page_displays_video_copy_evidence_and_warnings -q`

Expected: PASS.

### Task 3: Regression and deployed smoke verification

**Files:**
- Verify: `services/control-plane/app/templates/*.html`
- Verify: `services/control-plane/app/static/*.css`

**Interfaces:**
- Consumes: completed templates and styles.
- Produces: deployed, reachable navigation across all three page types.

- [ ] **Step 1: Run the complete test suite**

Run: `.venv\\Scripts\\python.exe -m pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Rebuild the control-plane container**

Run: `docker compose -p automated-video-workbench -f deploy/compose.yml up -d --build control-plane`

Expected: `automated-video-workbench-control-plane-1` starts successfully.

- [ ] **Step 3: Smoke-test deployed pages**

Request `/`, `/settings/cloud-usage`, and an existing `/review/{task_id}` URL. Assert HTTP 200 and that every response includes `aria-label="主导航"`, `/settings/cloud-usage`, and the expected current-page label.

- [ ] **Step 4: Commit the implementation**

```bash
git add services/control-plane/app/templates services/control-plane/app/static services/control-plane/tests
git commit -m "feat: unify console navigation"
```
