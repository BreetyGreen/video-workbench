from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.adapters.volcengine_usage import (
    ArkUsageSnapshot,
    BalanceSnapshot,
    CouponItem,
    CouponSnapshot,
    ModelEntitlementSnapshot,
    ModelFreeEntitlement,
    ResourcePackageItem,
    ResourcePackageSnapshot,
)
from app.config import Settings
from app.main import create_app


class FakeUsageClient:
    def query_balance(self):
        return BalanceSnapshot(available_balance=88.5, cash_balance=90, freeze_amount=1.5, arrears_balance=0, credit_limit=200)

    def get_inference_usage(self, start_time, end_time, interval="Day"):
        return ArkUsageSnapshot(total_tokens=1441, input_tokens=1000, output_tokens=441, data_count=2)

    def list_model_activations(self):
        return ModelEntitlementSnapshot(
            total_count=1,
            models_with_initial_free_usage=1,
            initial_total_tokens=1_000_000,
            initial_consumed_tokens=250_000,
            initial_remaining_tokens=750_000,
            resource_pack_count=0,
            items=(
                ModelFreeEntitlement(
                    foundation_model_name="doubao-seed-1.6",
                    display_name="Doubao Seed 1.6",
                    initial_total_tokens=1_000_000,
                    initial_consumed_tokens=250_000,
                    initial_remaining_tokens=750_000,
                    resource_pack_count=0,
                ),
            ),
            total_remaining_tokens=750_000,
        )

    def list_resource_packages(self):
        return ResourcePackageSnapshot(
            count=1,
            items=(ResourcePackageItem("豆包语音", "赠送资源包", 14018, 20000, "字符", "2026-11-19T00:00:00Z", "Effective"),),
        )

    def list_coupons(self):
        return CouponSnapshot(
            count=1,
            total_remaining_amount=18.5,
            items=(CouponItem("新用户代金券", 18.5, 20, "2026-09-01T00:00:00Z", 1),),
        )


class FakeProviderError(Exception):
    action = "QueryBalanceAcct"
    status_code = 403
    provider_code = "AccessDenied"
    request_id = "req-safe-123"


class BalanceDeniedUsageClient(FakeUsageClient):
    def query_balance(self):
        raise FakeProviderError("provider rejected request")


class EntitlementDeniedUsageClient(FakeUsageClient):
    def list_model_activations(self):
        error = FakeProviderError("entitlement permission denied")
        error.action = "ListModelActivations"
        raise error


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'usage-api.db').as_posix()}",
        usage_secret_master_key="test-secret-master-key-123456789",
        automation_enabled=False,
    )
    return TestClient(create_app(settings, usage_client_factory=lambda _ak, _sk: FakeUsageClient()))


def make_denied_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "denied-data",
        database_url=f"sqlite:///{(tmp_path / 'denied-usage-api.db').as_posix()}",
        usage_secret_master_key="test-secret-master-key-123456789",
        automation_enabled=False,
    )
    return TestClient(create_app(settings, usage_client_factory=lambda _ak, _sk: BalanceDeniedUsageClient()))


def make_entitlement_denied_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "entitlement-denied-data",
        database_url=f"sqlite:///{(tmp_path / 'entitlement-denied.db').as_posix()}",
        usage_secret_master_key="test-secret-master-key-123456789",
        automation_enabled=False,
    )
    return TestClient(create_app(settings, usage_client_factory=lambda _ak, _sk: EntitlementDeniedUsageClient()))


def test_cloud_usage_settings_masks_secrets_and_summary_labels_sources(tmp_path: Path):
    with make_client(tmp_path) as client:
        saved = client.put(
            "/api/cloud-usage/settings",
            json={
                "access_key_id": "TEST1234567890XYZ",
                "secret_access_key": "secret-value-never-return",
                "asr_total_seconds": 3600,
                "tts_total_characters": 100000,
            },
            headers={"Origin": "http://testserver"},
        )
        settings = client.get("/api/cloud-usage/settings")
        summary = client.get("/api/cloud-usage/summary")

        assert saved.status_code == 200
        assert saved.json()["access_key_id_masked"] == "TEST****0XYZ"
        assert "secret-value" not in saved.text + settings.text + summary.text
        assert settings.json()["configured"] is True
        assert summary.json()["balance"]["available_balance"] == 88.5
        assert summary.json()["balance"]["credit_limit"] == 200
        assert summary.json()["balance"]["source"] == "official"
        assert summary.json()["ark_usage"]["total_tokens"] == 1441
        assert summary.json()["ark_entitlements"]["initial_remaining_tokens"] == 750_000
        assert summary.json()["ark_entitlements"]["total_remaining_tokens"] == 750_000
        assert summary.json()["ark_entitlements"]["items"][0]["display_name"] == "Doubao Seed 1.6"
        assert summary.json()["resource_packages"]["items"][0]["available_amount"] == 14018
        assert summary.json()["coupons"]["total_remaining_amount"] == 18.5
        assert summary.json()["local"]["tts"]["source"] == "local_estimated"
        assert summary.json()["evidence_layers"]["official_balance"]["status"] == "available"
        assert summary.json()["evidence_layers"]["gifted_entitlements"]["status"] == "available"
        assert summary.json()["evidence_layers"]["configured_budgets"]["status"] == "configured"
        assert summary.json()["evidence_layers"]["local_metering"]["status"] == "available"
        assert summary.json()["recent_tasks"] == []


def test_cloud_usage_summary_keeps_balance_when_entitlement_permission_is_denied(tmp_path: Path):
    with make_entitlement_denied_client(tmp_path) as client:
        saved = client.put(
            "/api/cloud-usage/settings",
            json={"access_key_id": "TEST1234567890XYZ", "secret_access_key": "secret-value-never-return"},
            headers={"Origin": "http://testserver"},
        )
        summary = client.post("/api/cloud-usage/refresh")

        assert saved.status_code == 200
        assert summary.status_code == 200
        assert summary.json()["balance"]["available"] is True
        assert summary.json()["balance"]["available_balance"] == 88.5
        assert summary.json()["ark_usage"]["available"] is True
        assert summary.json()["ark_entitlements"]["available"] is False
        assert summary.json()["ark_entitlements"]["error"] == "AccessDenied"


def test_cloud_usage_settings_reject_cross_origin_write(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.put(
            "/api/cloud-usage/settings",
            json={"access_key_id": "AKLT123", "secret_access_key": "secret"},
            headers={"Origin": "https://evil.example"},
        )

        assert response.status_code == 403


def test_cloud_usage_settings_reports_safe_provider_failure_stage(tmp_path: Path):
    with make_denied_client(tmp_path) as client:
        response = client.put(
            "/api/cloud-usage/settings",
            json={"access_key_id": "AKLT123", "secret_access_key": "secret-value-never-return"},
            headers={"Origin": "http://testserver"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == {
            "code": "credential_verification_failed",
            "stage": "balance",
            "reason": "AccessDenied",
            "http_status": 403,
            "request_id": "req-safe-123",
        }
        assert "secret-value" not in response.text


def test_cloud_usage_settings_page_exists(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.get("/settings/cloud-usage")

        assert response.status_code == 200
        assert "云端余量设置" in response.text
        assert "用量与成本" in response.text
        assert 'id="usage-overview"' in response.text
        assert 'id="task-usage-ledger"' in response.text
        assert 'class="credential-settings"' in response.text
        assert "/static/cloud_usage_settings.css" in response.text
        assert "从剪贴板读取" in response.text
        assert 'aria-label="主导航"' in response.text
        assert 'class="app-sidebar"' in response.text
        assert 'class="app-main workspace settings-shell"' in response.text
        assert '/static/design_system.css' in response.text
        assert 'href="/"' in response.text
        assert 'href="/settings/cloud-usage"' in response.text
        assert "返回工作台" in response.text
        assert "video-usage-monitor" in response.text
        assert "不要创建 API Key" in response.text


def test_unconfigured_summary_marks_official_values_unknown_instead_of_zero(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "unknown-data",
        database_url=f"sqlite:///{(tmp_path / 'unknown.db').as_posix()}",
        usage_secret_master_key="test-secret-master-key-123456789",
        automation_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        summary = client.get("/api/cloud-usage/summary").json()

        assert summary["configured"] is False
        assert summary["balance"]["available"] is False
        assert "available_balance" not in summary["balance"]
        assert summary["evidence_layers"]["official_balance"] == {
            "source": "official",
            "status": "unavailable",
            "reason": "not_configured",
        }
        assert summary["evidence_layers"]["configured_budgets"]["status"] == "not_configured"
        assert summary["evidence_layers"]["local_metering"]["status"] == "available"


def test_summary_exposes_recent_per_video_usage(tmp_path: Path):
    with make_client(tmp_path) as client:
        created = client.post(
            "/api/tasks",
            data={"title": "宠物除毛梳", "content_type": "商品介绍", "rights_confirmed": "true"},
            files=[("files", ("pet.mp4", b"video", "video/mp4"))],
        ).json()
        with Session(client.app.state.database.engine) as session:
            client.app.state.cloud_usage.usage.record_event(
                session,
                task_id=created["id"],
                provider="volcengine",
                service="tts",
                metric="characters",
                quantity=96,
                unit="characters",
            )

        summary = client.get("/api/cloud-usage/summary").json()

        assert summary["recent_tasks"][0]["task_id"] == created["id"]
        assert summary["recent_tasks"][0]["title"] == "宠物除毛梳"
        assert summary["recent_tasks"][0]["totals"]["tts_characters"] == 96
