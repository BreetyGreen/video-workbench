from pathlib import Path

import yaml


def test_production_compose_has_reverse_proxy_healthchecks_and_persistent_data():
    compose = yaml.safe_load(Path("deploy/compose.production.yml").read_text(encoding="utf-8"))

    assert compose["services"]["control-plane"]["healthcheck"]
    assert compose["services"]["control-plane"]["restart"] == "unless-stopped"
    assert compose["services"]["caddy"]["healthcheck"]
    assert "control-plane-data" in compose["volumes"]
    assert "caddy-data" in compose["volumes"]
    assert "basic_auth" in Path("deploy/Caddyfile").read_text(encoding="utf-8")


def test_production_runbook_keeps_jianying_on_user_devices():
    runbook = Path("docs/deployment.md").read_text(encoding="utf-8")

    assert "剪映保留在 Windows/Mac 用户电脑" in runbook
    assert "docker compose" in runbook
    assert "backup-server.ps1" in runbook


def test_production_environment_template_exists_without_real_credentials():
    template_path = Path("deploy/.env.production.example")

    assert template_path.is_file()
    template = template_path.read_text(encoding="utf-8")
    assert "AUTH_USERNAME=replace-with-admin-user" in template
    assert "VIDEO_WORKBENCH_BASIC_AUTH_HASH=replace-with-caddy-hash" in template
    assert "VIDEO_WORKBENCH_DOMAIN=video.example.com" in template
    assert "VIDEO_WORKBENCH_USAGE_SECRET_MASTER_KEY=replace-with-random-secret" in template
    assert "AKLT" not in template
    assert "gho_" not in template
