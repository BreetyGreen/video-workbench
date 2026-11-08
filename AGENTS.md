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

## Sample-standard product cut (tools/sample-cut)

When the user asks for a product video "to the sample standard" (样片标准), or hands over raw product footage and wants a finished Douyin-style clip, use the script pipeline in `tools/sample-cut/README.md` instead of the web workbench. It reproduces the teacher's measured sample (about 24 s, about 22 shots of about 1.1 s, push-in, grade, action sound, subtitles at about 20% height, licensed BGM). New-machine handoff for Mac + Codex: `docs/mac-codex-handoff.md`.

**Fully automatic requests** ("用 <folder> 做视频", "全自动做一条", footage folder + "make a video"): follow `tools/sample-cut/AUTOPILOT.md` end to end and do not ask the user anything between the trigger and the delivery. Make the judgement calls (shot types, takes, package facts, copy) yourself, record them in `notes.md`, and report at the end.

- Setup: `uv sync --project tools/sample-cut`, then `autopilot_setup.py` once (fonts, BGM library, settings). Run every script from the product's work dir (or set `SAMPLE_CUT_WORK`), and keep work dirs outside git-tracked paths.
- Copy uses only facts printed on the package. Never add price, stock, efficacy or competitor claims. Record what was left out in `copy.json` `not_claimed`.
- Voice: a cloud DashScope voice, or local CosyVoice (`tools/cosyvoice`) cloning only the user's own voice or one with written permission. Never clone a voice extracted from other people's videos or a third-party "community" model of a real or branded voice, whatever the stated purpose.
- BGM: only CC BY tracks from `bgm_pick.py`/`bgm_download.py` (Incompetech). Always tell the user to paste the `.credit.txt` line into the post caption. Never download Douyin/Jianying library music to mix outside those apps.
- QA before delivery: `copy_check.py` must pass before any voice is made; `qa.py` (run by `produce.py`) checks duration, shots, speaking rate, ASR match, -14 LUFS, true peak, black frames and captions. Write material problems into `notes.md`, which goes into the delivery's `先看这里.md`.
- Captions: style comes from `styles.json` (auto-picked per product, or `copy.json` "style"). Fonts are SIL OFL only (`fonts_download.py`); never copy fonts, 花字 or templates out of Jianying into rendered videos. In Jianying drafts, use Jianying's own bundled fonts and animations.
- Publishing stays manual: the user presses Publish in Douyin themself.
- macOS is code-adapted but not yet verified on a real Mac (aac_at encoder, PingFang subtitles, Jianying draft import, CosyVoice install). Report the first results in `docs/progress.md`.

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
