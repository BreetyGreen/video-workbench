from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Callable

from sqlmodel import Session

from app.adapters.volcengine_usage import VolcengineUsageClient
from app.models import CloudCredential, OfficialUsageSnapshot, UsageBudget
from app.services.secret_store import SecretStore, mask_access_key
from app.services.usage_service import UsageService


class CredentialVerificationError(RuntimeError):
    def __init__(self, *, stage: str, cause: Exception):
        self.stage = stage
        self.reason = str(getattr(cause, "provider_code", type(cause).__name__))
        self.http_status = int(getattr(cause, "status_code", 0) or 0)
        self.request_id = str(getattr(cause, "request_id", ""))
        super().__init__(f"Credential verification failed at {stage}: {self.reason}")


class CloudUsageService:
    CACHE_TTL = timedelta(minutes=5)

    def __init__(self, master_secret: str, client_factory: Callable[[str, str], VolcengineUsageClient] | None = None):
        self.secrets = SecretStore(master_secret)
        self.client_factory = client_factory or (lambda ak, sk: VolcengineUsageClient(ak, sk))
        self.usage = UsageService()

    @staticmethod
    def _budget(session: Session) -> UsageBudget:
        budget = session.get(UsageBudget, "default")
        if budget is None:
            budget = UsageBudget(id="default")
            session.add(budget)
            session.commit()
            session.refresh(budget)
        return budget

    def settings(self, session: Session) -> dict[str, object]:
        credential = session.get(CloudCredential, "volcengine")
        budget = self._budget(session)
        return {
            "configured": credential is not None,
            "access_key_id_masked": credential.access_key_id_masked if credential else "",
            "permission_mode": credential.permission_mode if credential else "read_only",
            "verified_at": credential.verified_at.isoformat() if credential and credential.verified_at else None,
            "asr_total_seconds": budget.asr_total_seconds,
            "tts_total_characters": budget.tts_total_characters,
            "ark_monthly_tokens": budget.ark_monthly_tokens,
            "warning_threshold_percent": budget.warning_threshold_percent,
            "critical_threshold_percent": budget.critical_threshold_percent,
        }

    def save(self, session: Session, payload) -> dict[str, object]:
        client = self.client_factory(payload.access_key_id.strip(), payload.secret_access_key.strip())
        try:
            client.query_balance()
        except Exception as error:
            raise CredentialVerificationError(stage="balance", cause=error) from error
        try:
            client.get_inference_usage((datetime.now(UTC) - timedelta(days=1)).date().isoformat(), datetime.now(UTC).date().isoformat())
        except Exception as error:
            raise CredentialVerificationError(stage="ark_usage", cause=error) from error
        now = datetime.now(UTC)
        credential = session.get(CloudCredential, "volcengine") or CloudCredential(provider="volcengine")
        credential.access_key_id_masked = mask_access_key(payload.access_key_id)
        credential.encrypted_access_key_id = self.secrets.encrypt(payload.access_key_id.strip())
        credential.encrypted_secret_access_key = self.secrets.encrypt(payload.secret_access_key.strip())
        credential.verified_at = now
        credential.updated_at = now
        budget = self._budget(session)
        for name in ("asr_total_seconds", "tts_total_characters", "ark_monthly_tokens", "warning_threshold_percent", "critical_threshold_percent"):
            setattr(budget, name, getattr(payload, name))
        budget.updated_at = now
        session.add(credential)
        session.add(budget)
        session.commit()
        return self.settings(session)

    def _client(self, session: Session):
        credential = session.get(CloudCredential, "volcengine")
        if credential is None:
            return None
        return self.client_factory(self.secrets.decrypt(credential.encrypted_access_key_id), self.secrets.decrypt(credential.encrypted_secret_access_key))

    @staticmethod
    def _store_snapshot(session: Session, kind: str, payload: dict[str, object], error: str = "") -> None:
        snapshot = session.get(OfficialUsageSnapshot, kind) or OfficialUsageSnapshot(kind=kind)
        snapshot.payload_json = json.dumps(payload, ensure_ascii=False)
        snapshot.fetched_at = datetime.now(UTC)
        snapshot.error = error
        session.add(snapshot)
        session.commit()

    @classmethod
    def _cached_snapshot(cls, session: Session, kind: str) -> dict[str, object] | None:
        snapshot = session.get(OfficialUsageSnapshot, kind)
        if snapshot is None:
            return None
        fetched_at = snapshot.fetched_at
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        if datetime.now(UTC) - fetched_at > cls.CACHE_TTL:
            return None
        return {**json.loads(snapshot.payload_json), "cached": True, "fetched_at": fetched_at.isoformat()}

    def summary(self, session: Session, *, force: bool = False) -> dict[str, object]:
        local = self.usage.local_summary(session)
        budget = self._budget(session)
        recent_tasks = self.usage.recent_task_usage(session)
        client = self._client(session)
        if client is None:
            unavailable = {"available": False, "source": "official", "error": "not_configured"}
            return {
                "configured": False,
                "balance": dict(unavailable),
                "ark_usage": dict(unavailable),
                "ark_entitlements": dict(unavailable),
                "resource_packages": dict(unavailable),
                "coupons": dict(unavailable),
                "ark": dict(unavailable),
                "local": local,
                "recent_tasks": recent_tasks,
                "evidence_layers": self._evidence_layers(
                    configured=False,
                    balance=dict(unavailable),
                    gifted_sections=[dict(unavailable)],
                    budget=budget,
                ),
            }

        today = datetime.now(UTC).date()

        def load_section(kind: str, fetch: Callable[[], object]) -> dict[str, object]:
            if not force:
                cached = self._cached_snapshot(session, kind)
                if cached is not None:
                    return cached
            try:
                snapshot = fetch()
                payload = {**asdict(snapshot), "available": True, "source": "official"}
                self._store_snapshot(session, kind, payload)
                return payload
            except Exception as error:
                error_code = str(getattr(error, "provider_code", type(error).__name__))
                previous = session.get(OfficialUsageSnapshot, kind)
                if previous is not None:
                    return {
                        **json.loads(previous.payload_json),
                        "stale": True,
                        "error": error_code,
                        "fetched_at": previous.fetched_at.isoformat(),
                    }
                return {
                    "available": False,
                    "source": "official",
                    "error": error_code,
                    "action": str(getattr(error, "action", "")),
                }

        balance = load_section("balance", client.query_balance)
        ark_usage = load_section(
            "ark_usage",
            lambda: client.get_inference_usage(
                (today - timedelta(days=30)).isoformat(),
                (today + timedelta(days=1)).isoformat(),
            ),
        )
        ark_entitlements = load_section("ark_entitlements", client.list_model_activations)
        resource_packages = load_section("resource_packages", client.list_resource_packages)
        coupons = load_section("coupons", client.list_coupons)
        return {
            "configured": True,
            "balance": balance,
            "ark_usage": ark_usage,
            "ark_entitlements": ark_entitlements,
            "resource_packages": resource_packages,
            "coupons": coupons,
            "ark": ark_usage,
            "local": local,
            "recent_tasks": recent_tasks,
            "evidence_layers": self._evidence_layers(
                configured=True,
                balance=balance,
                gifted_sections=[ark_entitlements, resource_packages, coupons],
                budget=budget,
            ),
            "updated_at": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def _evidence_layers(
        *,
        configured: bool,
        balance: dict[str, object],
        gifted_sections: list[dict[str, object]],
        budget: UsageBudget,
    ) -> dict[str, dict[str, object]]:
        balance_available = bool(balance.get("available"))
        gifts_available = any(bool(section.get("available")) for section in gifted_sections)
        budget_configured = any(
            value > 0
            for value in (budget.asr_total_seconds, budget.tts_total_characters, budget.ark_monthly_tokens)
        )
        official_reason = str(balance.get("error") or ("not_configured" if not configured else "provider_unavailable"))
        gifts_reason = next(
            (str(section.get("error")) for section in gifted_sections if section.get("error")),
            "not_configured" if not configured else "provider_unavailable",
        )
        return {
            "official_balance": {
                "source": "official",
                "status": "available" if balance_available else "unavailable",
                **({} if balance_available else {"reason": official_reason}),
            },
            "gifted_entitlements": {
                "source": "official",
                "status": "available" if gifts_available else "unavailable",
                **({} if gifts_available else {"reason": gifts_reason}),
            },
            "configured_budgets": {
                "source": "user_configured",
                "status": "configured" if budget_configured else "not_configured",
            },
            "local_metering": {
                "source": "local_measured",
                "status": "available",
            },
        }
