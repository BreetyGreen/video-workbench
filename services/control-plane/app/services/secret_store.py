from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class SecretStore:
    def __init__(self, master_secret: str):
        normalized = master_secret.strip()
        if len(normalized) < 16:
            raise ValueError("usage secret master key must contain at least 16 characters")
        key = base64.urlsafe_b64encode(hashlib.sha256(normalized.encode("utf-8")).digest())
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken as error:
            raise ValueError("stored cloud credential cannot be decrypted") from error


def mask_access_key(value: str) -> str:
    normalized = value.strip()
    if len(normalized) <= 8:
        return "****"
    return f"{normalized[:4]}****{normalized[-4:]}"
