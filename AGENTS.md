# Automated Video Workbench Agent Guide

This repository is designed to be started by Codex from a fresh clone. Keep the local baseline private, loopback-only, and free of required cloud credentials.

Before changing startup, configuration, provider, editing, or delivery behavior, read `docs/codex-operator-guide.md` and the machine-readable contract at `services/control-plane/app/capability_catalog.json`. Human-facing explanations live in `docs/capabilities-and-configuration.md`; keep all three aligned.

## First run

1. If Python is already available, run `python3 scripts/doctor.py`; otherwise continue directly to the platform bootstrap.
2. On macOS run `bash scripts/bootstrap.sh`.
3. On Windows run `powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1`.
4. Never request API keys for the local baseline and never print existing secrets.
5. Treat system permission prompts and official OAuth as user-confirmed actions, not project configuration fields.
6. Do not treat an optional provider's `not_configured` state as a local editing failure. Report its documented fallback.

The bootstrap must be idempotent. It may install pinned local tooling, create user-owned runtime directories, and open the loopback application after `/health` succeeds.

## Verification

- macOS focused tests: `uv run --project services/control-plane --extra test pytest services/control-plane/tests -q`
- Windows existing environment: `services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests -q`
- JavaScript: `node --check services/control-plane/app/static/workbench.js`
- Read-only doctor: `python3 scripts/doctor.py`
- Health: `http://127.0.0.1:8130/health`

Run tests with `VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED=false` so unit tests never start the persisted daily schedule.

## Persistent data

- macOS state: `~/Library/Application Support/VideoWorkbench`
- macOS model cache: `~/Library/Caches/VideoWorkbench`
- macOS watched inbox: `~/Movies/VideoWorkbench Inbox`
- Repository-local `data/`, `.env`, virtual environments, credentials, and generated media must never be committed.

## Safety and state rules

- Never delete task rows, artifacts, licensed media, or Jianying drafts as cleanup. Archive tasks so records remain recoverable.
- Never print `.env`, API keys, access tokens, AK/SK, OAuth tokens, or decrypted secret-store values.
- Do not crawl private or logged-in media, bypass signatures, defeat risk controls, or treat public Douyin/Xiaohongshu video frames as licensed editing material.
- Discovery may inspect only bounded user folders and must not rewrite an existing Jianying draft.
- Keep Confirmed, Open, and External-user-action states separate in `docs/progress.md`.
- When the user asks what needs a Key, answer from the three tiers in `capability_catalog.json`: `local_no_key`, `optional_key`, and `external_authorization`.
- On macOS, do not make the native bootstrap read a repository `.env`; optional secrets are user-supplied process environment values. Windows/Docker may use the ignored root `.env`.
