from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from app.db import Database
from app.models import DevicePairingCode
from app.services.device_delivery_service import DeviceDeliveryService


def test_pairing_code_is_single_use_and_token_is_stored_as_hash(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    database.create_all()
    service = DeviceDeliveryService("test-master-secret")
    with Session(database.engine) as session:
        issued = service.issue_code(session)
        paired = service.pair(session, code=issued.code, name="MacBook")

        assert paired.token
        assert paired.device.token_hash != paired.token
        assert service.authenticate(session, paired.token).id == paired.device.id
        with pytest.raises(ValueError, match="pairing_code_already_used"):
            service.pair(session, code=issued.code, name="second")


def test_expired_pairing_code_is_rejected(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    database.create_all()
    service = DeviceDeliveryService("test-master-secret")
    with Session(database.engine) as session:
        issued = service.issue_code(session)
        record = session.get(DevicePairingCode, issued.id)
        assert record is not None
        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.add(record)
        session.commit()

        with pytest.raises(ValueError, match="pairing_code_expired"):
            service.pair(session, code=issued.code, name="MacBook")
