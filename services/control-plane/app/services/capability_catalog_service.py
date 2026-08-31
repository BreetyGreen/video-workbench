from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


SUPPORTED_TIERS = {"local_no_key", "optional_key", "external_authorization"}


class CapabilityCatalogService:
    """Load the public, secret-free capability contract shipped with the app."""

    def __init__(self, catalog_path: Path | None = None):
        self.catalog_path = catalog_path or Path(__file__).resolve().parents[1] / "capability_catalog.json"
        self._catalog = self._load()

    def _load(self) -> list[dict[str, Any]]:
        payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not payload:
            raise ValueError("Capability catalog must be a non-empty list")
        identifiers: set[str] = set()
        required_fields = {
            "id",
            "name",
            "tier",
            "summary",
            "features",
            "requires",
            "fallback",
            "data_boundary",
            "docs_url",
        }
        for item in payload:
            if not isinstance(item, dict) or not required_fields.issubset(item):
                raise ValueError("Capability catalog item is incomplete")
            identifier = str(item["id"])
            if identifier in identifiers:
                raise ValueError(f"Duplicate capability id: {identifier}")
            identifiers.add(identifier)
            if item["tier"] not in SUPPORTED_TIERS:
                raise ValueError(f"Unsupported capability tier: {item['tier']}")
            if not isinstance(item["features"], list) or not isinstance(item["requires"], list):
                raise ValueError(f"Capability lists are invalid: {identifier}")
        return payload

    def list(self) -> list[dict[str, Any]]:
        return deepcopy(self._catalog)
