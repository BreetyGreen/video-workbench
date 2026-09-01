from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets

from sqlalchemy import update
from sqlmodel import Session, select

from app.models import DeliveryDevice, DevicePairingCode


@dataclass(frozen=True)
class IssuedPairingCode:
    id: str
    code: str
    expires_at: datetime


@dataclass(frozen=True)
class PairedDevice:
    device: DeliveryDevice
    token: str


class DeviceDeliveryService:
    def __init__(self, master_secret: str, *, pairing_ttl_minutes: int = 10):
        if not master_secret.strip():
            raise ValueError("device_master_secret_required")
        self.master_secret = master_secret.encode("utf-8")
        self.pairing_ttl = timedelta(minutes=pairing_ttl_minutes)

    def _digest(self, value: str) -> str:
        return hmac.new(self.master_secret, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def issue_code(self, session: Session) -> IssuedPairingCode:
        code = secrets.token_urlsafe(9)
        expires_at = datetime.now(UTC) + self.pairing_ttl
        record = DevicePairingCode(code_hash=self._digest(code), expires_at=expires_at)
        session.add(record)
        session.commit()
        session.refresh(record)
        return IssuedPairingCode(id=record.id, code=code, expires_at=expires_at)

    def pair(self, session: Session, *, code: str, name: str) -> PairedDevice:
        code_hash = self._digest(code.strip())
        now = datetime.now(UTC)
        result = session.exec(
            update(DevicePairingCode)
            .where(DevicePairingCode.code_hash == code_hash)
            .where(DevicePairingCode.used_at.is_(None))
            .where(DevicePairingCode.expires_at > now)
            .values(used_at=now)
        )
        if result.rowcount != 1:
            session.rollback()
            record = session.exec(
                select(DevicePairingCode).where(DevicePairingCode.code_hash == code_hash)
            ).first()
            if record is None:
                raise ValueError("pairing_code_invalid")
            if record.used_at is not None:
                raise ValueError("pairing_code_already_used")
            raise ValueError("pairing_code_expired")

        token = secrets.token_urlsafe(32)
        device = DeliveryDevice(name=name.strip()[:100] or "VideoWorkbench Device", token_hash=self._digest(token))
        session.add(device)
        session.commit()
        session.refresh(device)
        return PairedDevice(device=device, token=token)

    def authenticate(self, session: Session, token: str) -> DeliveryDevice:
        digest = self._digest(token.strip())
        device = session.exec(
            select(DeliveryDevice).where(DeliveryDevice.token_hash == digest)
        ).first()
        if device is None or not device.active or not hmac.compare_digest(device.token_hash, digest):
            raise ValueError("device_token_invalid")
        device.last_seen_at = datetime.now(UTC)
        session.add(device)
        session.commit()
        session.refresh(device)
        return device
