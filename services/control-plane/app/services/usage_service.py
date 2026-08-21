from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, select

from app.models import UsageBudget, UsageEvent, VideoTask


class UsageService:
    @staticmethod
    def record_event(
        session: Session,
        *,
        task_id: str | None,
        provider: str,
        service: str,
        metric: str,
        quantity: float,
        unit: str,
        status: str = "succeeded",
        request_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> UsageEvent:
        event = UsageEvent(
            task_id=task_id,
            provider=provider,
            service=service,
            metric=metric,
            quantity=max(0, float(quantity)),
            unit=unit,
            status=status,
            request_id=request_id,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":")),
        )
        session.add(event)
        session.commit()
        session.refresh(event)
        return event

    @staticmethod
    def _events(session: Session, task_id: str | None = None) -> list[UsageEvent]:
        statement = select(UsageEvent).order_by(UsageEvent.created_at, UsageEvent.id)
        if task_id is not None:
            statement = statement.where(UsageEvent.task_id == task_id)
        return list(session.exec(statement).all())

    @staticmethod
    def _totals(events: list[UsageEvent]) -> dict[str, float]:
        totals = {"asr_audio_seconds": 0.0, "tts_characters": 0.0, "voiceover_seconds": 0.0, "input_tokens": 0.0, "output_tokens": 0.0, "total_tokens": 0.0}
        mapping = {
            ("asr", "audio_seconds"): "asr_audio_seconds",
            ("tts", "characters"): "tts_characters",
            ("tts", "audio_seconds"): "voiceover_seconds",
        }
        for event in events:
            key = mapping.get((event.service, event.metric), event.metric if event.metric in totals else None)
            if key:
                totals[key] += event.quantity
        return {key: round(value, 3) for key, value in totals.items()}

    def task_usage(self, session: Session, task_id: str) -> dict[str, Any]:
        events = self._events(session, task_id)
        return {
            "task_id": task_id,
            "source": "local_measured",
            "totals": self._totals(events),
            "unapplied_calls": sum(item.status == "succeeded_not_applied" for item in events),
            "events": [
                {
                    "id": item.id,
                    "task_id": item.task_id,
                    "provider": item.provider,
                    "service": item.service,
                    "metric": item.metric,
                    "quantity": item.quantity,
                    "unit": item.unit,
                    "status": item.status,
                    "request_id": item.request_id,
                    "created_at": item.created_at.isoformat(),
                }
                for item in events
            ],
        }

    def recent_task_usage(self, session: Session, limit: int = 20) -> list[dict[str, Any]]:
        tasks = list(session.exec(select(VideoTask).order_by(VideoTask.updated_at.desc()).limit(max(1, limit * 4))).all())
        events = self._events(session)
        by_task: dict[str, list[UsageEvent]] = {}
        for event in events:
            if event.task_id:
                by_task.setdefault(event.task_id, []).append(event)
        rows = []
        for task in tasks:
            task_events = by_task.get(task.id, [])
            last_event = task_events[-1].created_at if task_events else None
            rows.append(
                {
                    "task_id": task.id,
                    "title": task.title,
                    "content_type": task.content_type,
                    "status": task.status.value,
                    "source": "local_measured",
                    "event_count": len(task_events),
                    "totals": self._totals(task_events),
                    "unapplied_calls": sum(item.status == "succeeded_not_applied" for item in task_events),
                    "last_event_at": last_event.isoformat() if last_event else None,
                    "created_at": task.created_at.isoformat(),
                    "_sort_at": last_event or task.updated_at,
                }
            )
        rows.sort(key=lambda row: row["_sort_at"], reverse=True)
        for row in rows:
            row.pop("_sort_at", None)
        return rows[: max(1, limit)]

    @staticmethod
    def _budget_metric(*, used: float, total: float, warning: float, critical: float) -> dict[str, Any]:
        remaining = max(0.0, total - used) if total > 0 else None
        percent = (remaining / total * 100) if remaining is not None and total else None
        level = "unknown"
        if percent is not None:
            level = "critical" if percent <= critical else "warning" if percent <= warning else "ok"
        return {
            "used": round(used, 3),
            "total": round(total, 3),
            "remaining": round(remaining, 3) if remaining is not None else None,
            "remaining_percent": round(percent, 2) if percent is not None else None,
            "level": level,
            "source": "local_estimated",
        }

    def local_summary(self, session: Session) -> dict[str, Any]:
        events = self._events(session)
        totals = self._totals(events)
        budget = session.get(UsageBudget, "default") or UsageBudget(id="default")
        return {
            "source": "local_measured",
            "tts": self._budget_metric(used=totals["tts_characters"], total=budget.tts_total_characters, warning=budget.warning_threshold_percent, critical=budget.critical_threshold_percent),
            "asr": self._budget_metric(used=totals["asr_audio_seconds"], total=budget.asr_total_seconds, warning=budget.warning_threshold_percent, critical=budget.critical_threshold_percent),
            "tokens": totals["total_tokens"],
            "unapplied_calls": sum(item.status == "succeeded_not_applied" for item in events),
        }
