from pathlib import Path


ROOT = Path(__file__).parents[3]


def test_agents_uses_relative_portable_commands():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    first_run = text.split("## First run", 1)[1].split("##", 1)[0]

    assert "scripts/bootstrap.sh" in first_run
    assert "scripts/bootstrap.ps1" in first_run
    assert "B:\\" not in text
    assert "Docker" not in first_run


def test_readme_leads_with_clone_and_codex_startup():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    first_screen = "\n".join(text.splitlines()[:45])

    assert "git clone" in first_screen
    assert "Codex" in first_screen
    assert "不需要填写 .env" in first_screen
    assert "/setup" in text
    assert "本地模式" in text


def test_fresh_clone_verifier_exercises_setup_activation():
    text = (ROOT / "scripts" / "verify-fresh-clone.py").read_text(encoding="utf-8")

    assert '"/setup"' in text
    assert '"/api/setup/preferences"' in text
    assert '"local_mode_confirmed": True' in text
    assert '"setup_smoke": "passed"' in text
    assert "_prepare_smoke_tool_path" in text
    assert '"smoke-bin"' in text
    assert '("Darwin", "Windows")' in text


def test_repository_has_windows_native_contract_ci():
    text = (ROOT / ".github" / "workflows" / "windows-native.yml").read_text(encoding="utf-8")

    assert "windows-latest" in text
    assert "scripts/verify-fresh-clone.py --dry-run" in text
    assert "test_doctor_cli.py" in text
    assert "Parser]::ParseFile" in text
    assert "${path}:" in text


def test_fresh_clone_verifier_stops_the_service_process_tree():
    text = (ROOT / "scripts" / "verify-fresh-clone.py").read_text(encoding="utf-8")

    assert "CREATE_NEW_PROCESS_GROUP" in text
    assert "start_new_session" in text
    assert "killpg" in text
    assert '"taskkill"' in text


def test_macos_runbook_documents_real_runtime_locations():
    text = (ROOT / "docs" / "runbooks" / "macos-local.md").read_text(encoding="utf-8")

    assert "~/Library/Application Support/VideoWorkbench" in text
    assert "~/Movies/VideoWorkbench Inbox" in text
    assert "scripts/doctor.py" in text
