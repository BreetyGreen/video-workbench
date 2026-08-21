# Gifted Entitlement Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Volcengine gifted/free entitlements visible without ever presenting missing data as a real zero.

**Architecture:** Extend the existing signed read-only Volcengine client with independently queried entitlement sources. Aggregate each source into an isolated cached section and render explicit official, cached, manual-estimate, unavailable, and unknown states in the existing workbench.

**Tech Stack:** Python 3.11, FastAPI, SQLModel, httpx, vanilla JavaScript, pytest.

## Global Constraints

- Never return or log plaintext credentials.
- A missing provider field must be `null`/unknown, never numeric zero.
- Failure of one official source must not hide successful sources.
- Existing uncommitted project work must be preserved.

---

### Task 1: Correct official usage semantics

**Files:**
- Modify: `services/control-plane/app/adapters/volcengine_usage.py`
- Test: `services/control-plane/tests/test_volcengine_usage.py`

**Interfaces:**
- Produces: `BalanceSnapshot.credit_limit: float | None`, `InferenceUsageSnapshot.data_count: int`, and `list_model_activations() -> ModelEntitlementSnapshot`.

- [ ] Add a failing test where `GetInferenceUsage` returns only `DataCount` and assert Token fields are `None` rather than `0`.
- [ ] Run `pytest tests/test_volcengine_usage.py -q` and confirm the assertion fails because the adapter currently fabricates zero Token values.
- [ ] Add a failing signed-request test for `ListModelActivations` with `WithFreeUsage=true` and parsing of `FreeResourcePackItems`.
- [ ] Implement nullable usage fields, `CreditLimit`, and model entitlement parsing without exposing raw provider payloads.
- [ ] Re-run the focused tests and expect all to pass.

### Task 2: Isolate and aggregate entitlement sources

**Files:**
- Modify: `services/control-plane/app/services/cloud_usage_service.py`
- Modify: `services/control-plane/tests/test_cloud_usage_api.py`

**Interfaces:**
- Consumes: `query_balance()`, `get_inference_usage()`, `list_model_activations()`.
- Produces: `/api/cloud-usage/summary` sections `balance`, `ark_usage`, `ark_entitlements`, and `local` with per-section availability/error state.

- [ ] Add a failing API test proving `ark_usage.total_tokens is None`, `credit_limit` is preserved, and free entitlement items are returned.
- [ ] Add a failing API test proving entitlement permission failure leaves balance and local metrics available.
- [ ] Implement per-section refresh/cache/error isolation; save successful snapshots independently.
- [ ] Re-run `pytest tests/test_cloud_usage_api.py tests/test_volcengine_usage.py -q` and expect all to pass.

### Task 3: Render truthful entitlement cards and verify live service

**Files:**
- Modify: `services/control-plane/app/static/workbench.js`
- Modify: `services/control-plane/app/templates/workbench.html`
- Modify: `services/control-plane/tests/test_workbench.py`
- Modify: `docs/runbooks/cloud-usage.md`
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: `/api/cloud-usage/summary`.
- Produces: separate cards for balance/credit, Ark free entitlements, Ark activity, ASR/TTS manual fallback, with unknown values rendered as `未知`.

- [ ] Add failing HTML/static assertions that the misleading “方舟 30 天 Token” label is absent and unknown semantics are present.
- [ ] Implement the new cards, concise details, and source/error badges.
- [ ] Run focused tests, then full `pytest -q`.
- [ ] Rebuild `control-plane`, verify `/health`, `/api/cloud-usage/summary`, and `/` from the running service.
- [ ] Confirm the live HTML references the current versioned JavaScript asset and the summary never turns an absent official field into zero.
