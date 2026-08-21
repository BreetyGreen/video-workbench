# macOS Zero-Config Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a fresh GitHub clone start locally on macOS through one Codex-invoked bootstrap command, without Docker or user-edited configuration, while discovering the user's Jianying installation and draft root safely.

**Architecture:** Add a standard-library platform layer that owns user data paths and Jianying discovery, expose it through a JSON doctor CLI, and wrap the existing FastAPI control plane with idempotent macOS bootstrap/start scripts. Runtime state lives under the user's Library, while the repository remains stateless and portable.

**Tech Stack:** Python 3.12, uv, FastAPI, SQLite, POSIX shell, macOS `mdfind`/`open`/`osascript`, FFmpeg, pytest.

## Global Constraints

- macOS is the first-release platform; Apple Silicon is preferred and Intel remains diagnosable.
- Docker must not be required for the native startup path.
- Users must not edit `.env` or enter project configuration values.
- Required local paths must be generated or discovered; a folder picker is allowed only when discovery is ambiguous.
- Runtime data must live under `~/Library/Application Support/VideoWorkbench`; model cache must live under `~/Library/Caches/VideoWorkbench`.
- Discovery must not traverse the entire disk or rewrite existing Jianying drafts.
- Cloud credentials remain optional and cannot block local startup.
- Existing Windows/Docker startup must continue working while the native macOS path is introduced.

---

### Task 1: Cross-platform runtime paths

**Files:**
- Create: `services/control-plane/app/platforms/__init__.py`
- Create: `services/control-plane/app/platforms/runtime.py`
- Test: `services/control-plane/tests/test_runtime_paths.py`

**Interfaces:**
- Produces: `RuntimePaths` and `resolve_runtime_paths(system: str | None = None, home: Path | None = None) -> RuntimePaths`.
- Consumers: doctor CLI, start scripts, integration diagnostics, and the Jianying locator.

- [ ] **Step 1: Write the failing runtime-path tests**

```python
from pathlib import Path

from app.platforms.runtime import resolve_runtime_paths


def test_macos_runtime_paths_are_outside_the_clone():
    home = Path("/Users/alice")
    paths = resolve_runtime_paths(system="Darwin", home=home)
    assert paths.data_dir == home / "Library/Application Support/VideoWorkbench"
    assert paths.cache_dir == home / "Library/Caches/VideoWorkbench"
    assert paths.inbox_dir == home / "Movies/VideoWorkbench Inbox"


def test_windows_runtime_paths_preserve_a_portable_default():
    paths = resolve_runtime_paths(system="Windows", home=Path("C:/Users/alice"))
    assert paths.data_dir == Path("C:/Users/alice/AppData/Local/VideoWorkbench")
```

- [ ] **Step 2: Run the tests and verify the module is missing**

Run: `services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests/test_runtime_paths.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'app.platforms'`.

- [ ] **Step 3: Implement the immutable runtime-path contract**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import platform


@dataclass(frozen=True)
class RuntimePaths:
    data_dir: Path
    cache_dir: Path
    inbox_dir: Path

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'control-plane.db'}"


def resolve_runtime_paths(*, system: str | None = None, home: Path | None = None) -> RuntimePaths:
    detected = system or platform.system()
    user_home = Path(home) if home is not None else Path.home().expanduser().resolve()
    if detected == "Darwin":
        return RuntimePaths(
            data_dir=user_home / "Library" / "Application Support" / "VideoWorkbench",
            cache_dir=user_home / "Library" / "Caches" / "VideoWorkbench",
            inbox_dir=user_home / "Movies" / "VideoWorkbench Inbox",
        )
    if detected == "Windows":
        return RuntimePaths(
            data_dir=user_home / "AppData" / "Local" / "VideoWorkbench",
            cache_dir=user_home / "AppData" / "Local" / "VideoWorkbench" / "cache",
            inbox_dir=user_home / "Videos" / "VideoWorkbench Inbox",
        )
    return RuntimePaths(
        data_dir=user_home / ".local" / "share" / "VideoWorkbench",
        cache_dir=user_home / ".cache" / "VideoWorkbench",
        inbox_dir=user_home / "Videos" / "VideoWorkbench Inbox",
    )
```

- [ ] **Step 4: Run the focused and configuration tests**

Run: `services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests/test_runtime_paths.py services/control-plane/tests/test_scheduler_lifecycle.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the runtime contract**

```bash
git add services/control-plane/app/platforms services/control-plane/tests/test_runtime_paths.py
git commit -m "feat: add portable local runtime paths"
```

### Task 2: Safe macOS Jianying discovery

**Files:**
- Create: `services/control-plane/app/platforms/jianying.py`
- Test: `services/control-plane/tests/test_macos_jianying_discovery.py`

**Interfaces:**
- Consumes: `RuntimePaths` from Task 1.
- Produces: `JianyingLocation`, `discover_jianying(home: Path, system: str, mdfind_output: str = "") -> JianyingLocation`, and `validate_draft_root(path: Path) -> bool`.
- `JianyingLocation` fields: `installed: bool`, `app_path: Path | None`, `draft_root: Path | None`, `candidates: tuple[Path, ...]`, `needs_folder_picker: bool`.

- [ ] **Step 1: Write fixture-based discovery tests**

```python
from pathlib import Path

from app.platforms.jianying import discover_jianying, validate_draft_root


def test_macos_discovers_app_and_valid_draft_root(tmp_path: Path):
    home = tmp_path / "Users" / "alice"
    app = home / "Applications" / "JianyingPro.app"
    draft = home / "Movies" / "JianyingPro" / "com.lveditor.draft"
    app.mkdir(parents=True)
    (draft / "sample").mkdir(parents=True)
    (draft / "sample" / "draft_info.json").write_text("{}", encoding="utf-8")
    result = discover_jianying(home=home, system="Darwin", mdfind_output=str(app))
    assert result.installed is True
    assert result.app_path == app
    assert result.draft_root == draft
    assert result.needs_folder_picker is False


def test_ambiguous_roots_require_one_picker(tmp_path: Path):
    home = tmp_path / "Users" / "alice"
    for parent in (home / "Movies" / "A", home / "Documents" / "B"):
        (parent / "com.lveditor.draft" / "sample").mkdir(parents=True)
        (parent / "com.lveditor.draft" / "sample" / "draft_info.json").write_text("{}")
    result = discover_jianying(home=home, system="Darwin")
    assert result.draft_root is None
    assert result.needs_folder_picker is True


def test_symlink_is_not_a_valid_draft_root(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)
    assert validate_draft_root(link) is False
```

- [ ] **Step 2: Verify the tests fail before implementation**

Run: `services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests/test_macos_jianying_discovery.py -q`

Expected: collection fails because `app.platforms.jianying` does not exist.

- [ ] **Step 3: Implement bounded discovery**

Implement `discover_jianying` with these exact search roots only:

```python
search_roots = (
    home / "Movies",
    home / "Documents",
    home / "Library" / "Application Support",
)
```

Within each root, descend at most four directory levels, skip symlinks, and accept a directory only when its name is `com.lveditor.draft` or one of its direct children contains `draft_info.json`. Parse `mdfind_output` as newline-separated absolute `.app` paths and prefer a path containing `Jianying` over `CapCut`. When exactly one valid draft root exists, select it; zero roots returns `needs_folder_picker=True`; multiple roots return all sorted candidates and require the picker.

- [ ] **Step 4: Run discovery tests**

Run: `services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests/test_macos_jianying_discovery.py -q`

Expected: all tests pass without touching real user folders.

- [ ] **Step 5: Commit discovery**

```bash
git add services/control-plane/app/platforms/jianying.py services/control-plane/tests/test_macos_jianying_discovery.py
git commit -m "feat: discover macOS Jianying safely"
```

### Task 3: JSON doctor CLI

**Files:**
- Create: `scripts/doctor.py`
- Test: `services/control-plane/tests/test_doctor_cli.py`

**Interfaces:**
- Consumes: `resolve_runtime_paths` and `discover_jianying`.
- Produces: process exit code `0` for a usable local environment, `2` when required components are missing; stdout is one JSON object with `platform`, `runtime`, `commands`, `jianying`, and `actions`.

- [ ] **Step 1: Write the CLI contract test**

```python
import json
from pathlib import Path
import subprocess
import sys


def test_doctor_emits_machine_readable_actions(tmp_path: Path):
    script = Path(__file__).parents[3] / "scripts" / "doctor.py"
    result = subprocess.run(
        [sys.executable, str(script), "--system", "Darwin", "--home", str(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(result.stdout)
    assert payload["platform"]["system"] == "Darwin"
    assert payload["runtime"]["data_dir"].endswith("Library/Application Support/VideoWorkbench")
    assert set(payload["commands"]) == {"ffmpeg", "ffprobe"}
    assert isinstance(payload["actions"], list)
    assert result.stderr == ""
```

- [ ] **Step 2: Run the CLI test and see it fail**

Run: `services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests/test_doctor_cli.py -q`

Expected: failure because `scripts/doctor.py` is absent.

- [ ] **Step 3: Implement doctor without third-party imports**

At process start, add `services/control-plane` to `sys.path`, parse `--system` and `--home`, use `shutil.which` for FFmpeg binaries, and call `mdfind` only on real Darwin runs. The action vocabulary is fixed:

```python
actions = []
if not commands["ffmpeg"]["available"] or not commands["ffprobe"]["available"]:
    actions.append("install_ffmpeg")
if not jianying.installed:
    actions.append("install_or_open_jianying")
elif jianying.needs_folder_picker:
    actions.append("choose_jianying_draft_root")
```

Do not include environment values, tokens, `.env` content, or directory listings in the JSON.

- [ ] **Step 4: Run doctor tests and a real read-only doctor call**

Run: `services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests/test_doctor_cli.py services/control-plane/tests/test_macos_jianying_discovery.py -q`

Run: `services/control-plane/.venv/Scripts/python.exe scripts/doctor.py`

Expected: tests pass; the real call prints valid JSON and does not modify the workspace.

- [ ] **Step 5: Commit doctor**

```bash
git add scripts/doctor.py services/control-plane/tests/test_doctor_cli.py
git commit -m "feat: add machine-readable local doctor"
```

### Task 4: Idempotent native macOS bootstrap and lifecycle

**Files:**
- Create: `.python-version`
- Create: `services/control-plane/uv.lock`
- Create: `scripts/bootstrap.sh`
- Create: `scripts/start-local.sh`
- Create: `scripts/stop-local.sh`
- Modify: `services/control-plane/pyproject.toml`
- Modify: `.gitignore`
- Test: `services/control-plane/tests/test_native_script_contract.py`

**Interfaces:**
- Consumes: doctor JSON and current FastAPI `app.main:app`.
- Produces: `bootstrap.sh` and `start-local.sh` exit `0` only after `/health` is healthy; PID is stored at `~/Library/Application Support/VideoWorkbench/run/control-plane.pid`.

- [ ] **Step 1: Write static safety-contract tests**

```python
from pathlib import Path


ROOT = Path(__file__).parents[3]


def test_native_start_is_loopback_and_not_docker_based():
    source = (ROOT / "scripts" / "start-local.sh").read_text()
    assert "127.0.0.1" in source
    assert "uv run uvicorn app.main:app" in source
    assert "docker" not in source.lower()


def test_stop_uses_only_the_recorded_pid():
    source = (ROOT / "scripts" / "stop-local.sh").read_text()
    assert "control-plane.pid" in source
    assert "pkill" not in source
    assert "killall" not in source


def test_bootstrap_pins_python_and_creates_runtime_directories():
    source = (ROOT / "scripts" / "bootstrap.sh").read_text()
    assert "uv python install 3.12" in source
    assert "VideoWorkbench Inbox" in source
    assert "brew install ffmpeg" in source
```

- [ ] **Step 2: Run the contract tests and verify scripts are absent**

Run: `services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests/test_native_script_contract.py -q`

Expected: failures for missing shell scripts.

- [ ] **Step 3: Implement bootstrap**

`bootstrap.sh` must use `set -euo pipefail`, resolve the repository relative to the script, reject non-Darwin systems with an actionable message, and perform these idempotent steps:

```sh
UV_VERSION="0.12.5"
PYTHON_VERSION="3.12"
DATA_DIR="$HOME/Library/Application Support/VideoWorkbench"
INBOX_DIR="$HOME/Movies/VideoWorkbench Inbox"
UV_BIN="${UV_BIN:-$HOME/.local/bin/uv}"

mkdir -p "$DATA_DIR" "$DATA_DIR/run" "$DATA_DIR/logs" "$INBOX_DIR"
if command -v uv >/dev/null 2>&1; then UV_BIN="$(command -v uv)"; fi
test -x "$UV_BIN" || curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh
"$UV_BIN" python install "$PYTHON_VERSION"
command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1 || brew install ffmpeg
"$UV_BIN" sync --project "$REPO_ROOT/services/control-plane" --python "$PYTHON_VERSION" --locked
exec "$REPO_ROOT/scripts/start-local.sh"
```

If both Homebrew and FFmpeg are absent, print one instruction to install Homebrew and exit `2`; do not execute an unpinned Homebrew installer. Inspecting and running the pinned uv installer is allowed by the design.

- [ ] **Step 4: Implement safe start and stop scripts**

`start-local.sh` exports these values before launching:

```sh
export VIDEO_WORKBENCH_DATA_DIR="$DATA_DIR"
export VIDEO_WORKBENCH_DATABASE_URL="sqlite:///$DATA_DIR/control-plane.db"
export VIDEO_WORKBENCH_FFMPEG_BIN="$(command -v ffmpeg)"
export VIDEO_WORKBENCH_FFPROBE_BIN="$(command -v ffprobe)"
export VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED="true"
```

Launch from `services/control-plane` with `nohup uv run uvicorn app.main:app --host 127.0.0.1 --port 8130`, write the child PID atomically, poll `/health` for at most 120 seconds, and use `open http://127.0.0.1:8130/` after health succeeds. If the recorded PID is alive and health is already good, return success without starting a duplicate process.

`stop-local.sh` resolves the same PID file, validates numeric PID content, sends `TERM` only to that PID, waits up to 20 seconds, and leaves the PID file in place with an error if the process cannot stop. Remove the PID file only after the process exits or is already absent.

- [ ] **Step 5: Run native script contract and existing lifecycle tests**

Run: `services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests/test_native_script_contract.py services/control-plane/tests/test_scheduler_lifecycle.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit native lifecycle**

```bash
git add .python-version .gitignore scripts/bootstrap.sh scripts/start-local.sh scripts/stop-local.sh services/control-plane/pyproject.toml services/control-plane/uv.lock services/control-plane/tests/test_native_script_contract.py
git commit -m "feat: bootstrap the workbench natively on macOS"
```

### Task 5: Surface zero-config diagnostics in the control plane

**Files:**
- Modify: `services/control-plane/app/main.py`
- Modify: `services/control-plane/app/templates/workbench.html`
- Modify: `services/control-plane/app/static/workbench.js`
- Test: `services/control-plane/tests/test_local_runtime_api.py`
- Test: `services/control-plane/tests/test_workbench.py`

**Interfaces:**
- Consumes: runtime paths and Jianying discovery.
- Produces: `GET /api/local-runtime` returning only non-secret runtime status.

- [ ] **Step 1: Write the API test**

```python
def test_local_runtime_status_is_non_secret_and_actionable(client):
    response = client.get("/api/local-runtime")
    assert response.status_code == 200
    payload = response.json()
    assert payload["platform"]
    assert "jianying" in payload
    assert "data_dir" in payload["runtime"]
    assert "api_key" not in response.text.lower()
    assert "access_token" not in response.text.lower()
```

Extend `test_workbench.py` to require `id="local-runtime-status"` and user copy that says paths are discovered automatically.

- [ ] **Step 2: Run the API/UI tests and verify failure**

Run: `services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests/test_local_runtime_api.py services/control-plane/tests/test_workbench.py -q`

Expected: `/api/local-runtime` returns 404 and the UI assertion fails.

- [ ] **Step 3: Implement runtime status**

Add a small endpoint that returns:

```python
{
    "platform": platform.system(),
    "architecture": platform.machine(),
    "runtime": {
        "data_dir": str(runtime_paths.data_dir),
        "inbox_dir": str(runtime_paths.inbox_dir),
    },
    "jianying": {
        "installed": location.installed,
        "app_path": str(location.app_path) if location.app_path else None,
        "draft_root": str(location.draft_root) if location.draft_root else None,
        "needs_folder_picker": location.needs_folder_picker,
    },
}
```

Do not return command output, home-directory listings, credentials, or stored configuration content. Add a compact status block to the workbench and load it from `workbench.js`; missing Jianying is an actionable warning, not a service failure.

- [ ] **Step 4: Run focused and full control-plane tests**

Run: `services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests/test_local_runtime_api.py services/control-plane/tests/test_workbench.py -q`

Run: `services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests -q`

Expected: focused tests and the full suite pass.

- [ ] **Step 5: Commit diagnostics**

```bash
git add services/control-plane/app/main.py services/control-plane/app/templates/workbench.html services/control-plane/app/static/workbench.js services/control-plane/tests/test_local_runtime_api.py services/control-plane/tests/test_workbench.py
git commit -m "feat: show local runtime readiness"
```

### Task 6: Fresh-clone contract, documentation, and CI

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Create: `docs/runbooks/macos-local.md`
- Create: `.github/workflows/macos-native.yml`
- Create: `scripts/verify-fresh-clone.py`
- Test: `services/control-plane/tests/test_repo_bootstrap_contract.py`

**Interfaces:**
- Consumes: all earlier tasks.
- Produces: a repository-level instruction contract that lets Codex select `bootstrap.sh` on Darwin and a CI job that tests the same path without real Jianying.

- [ ] **Step 1: Write repository-contract tests**

```python
from pathlib import Path


ROOT = Path(__file__).parents[3]


def test_agents_uses_relative_portable_commands():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "scripts/bootstrap.sh" in text
    assert "scripts/bootstrap.ps1" in text
    assert "B:\\" not in text
    assert "Docker" not in text.split("## First run", 1)[1].split("##", 1)[0]


def test_readme_leads_with_clone_and_codex_startup():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "git clone" in text
    assert "Codex" in text
    assert "不需要填写 .env" in text
```

- [ ] **Step 2: Run the contract tests and verify current documentation fails**

Run: `services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests/test_repo_bootstrap_contract.py -q`

Expected: `AGENTS.md` still contains the developer-specific `B:` path and tests fail.

- [ ] **Step 3: Generalize repository instructions**

The `AGENTS.md` first-run section must tell Codex:

```text
1. Run `python3 scripts/doctor.py` when Python exists; otherwise run the platform bootstrap directly.
2. On macOS run `bash scripts/bootstrap.sh`.
3. On Windows run `powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1`.
4. Never request API keys for the local baseline and never print existing secrets.
5. Treat system permission prompts and official OAuth as user-confirmed actions, not configuration fields.
```

Move machine-specific recovery notes out of `AGENTS.md`. Update README so clone + Codex is the primary path and Docker is an advanced compatibility path.

- [ ] **Step 4: Add macOS CI and fresh-clone verifier**

The GitHub Actions job uses `runs-on: macos-14`, installs the pinned uv version, runs `uv sync --project services/control-plane --python 3.12 --locked`, then executes runtime/Jianying/doctor/script tests and `python scripts/verify-fresh-clone.py --dry-run`.

The verifier copies tracked files into a temporary directory using `git archive HEAD`, asserts `.env`, `.venv`, `data`, and user paths are absent, runs doctor with a temporary home, and checks that every doctor action has a bootstrap handler. It must not download models or modify the real home during `--dry-run`.

- [ ] **Step 5: Run final verification**

Run:

```powershell
services/control-plane/.venv/Scripts/pytest.exe services/control-plane/tests -q
connectors/dingtalk/.venv/Scripts/pytest.exe connectors/dingtalk/tests -q
node --check services/control-plane/app/static/workbench.js
python scripts/verify-fresh-clone.py --dry-run
git diff --check
```

Expected: all Python tests pass, JavaScript syntax passes, fresh-clone dry run returns exit code `0`, and Git reports no whitespace errors.

- [ ] **Step 6: Commit the repository contract**

```bash
git add AGENTS.md README.md docs/runbooks/macos-local.md .github/workflows/macos-native.yml scripts/verify-fresh-clone.py services/control-plane/tests/test_repo_bootstrap_contract.py
git commit -m "docs: make Codex bootstrap the primary workflow"
```
