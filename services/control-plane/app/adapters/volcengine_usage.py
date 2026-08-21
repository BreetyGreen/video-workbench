from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable
from urllib.parse import quote

import httpx


@dataclass(frozen=True)
class BalanceSnapshot:
    available_balance: float
    cash_balance: float
    freeze_amount: float
    arrears_balance: float
    credit_limit: float | None = None


@dataclass(frozen=True)
class ArkUsageSnapshot:
    total_tokens: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    data_count: int = 0


@dataclass(frozen=True)
class ModelFreeEntitlement:
    foundation_model_name: str
    display_name: str
    initial_total_tokens: int | None
    initial_consumed_tokens: int | None
    initial_remaining_tokens: int | None
    resource_pack_count: int
    resource_pack_total_tokens: int = 0
    resource_pack_consumed_tokens: int = 0
    resource_pack_remaining_tokens: int = 0


@dataclass(frozen=True)
class ModelEntitlementSnapshot:
    total_count: int
    models_with_initial_free_usage: int
    initial_total_tokens: int
    initial_consumed_tokens: int
    initial_remaining_tokens: int
    resource_pack_count: int
    items: tuple[ModelFreeEntitlement, ...]
    resource_pack_total_tokens: int = 0
    resource_pack_consumed_tokens: int = 0
    resource_pack_remaining_tokens: int = 0
    total_remaining_tokens: int = 0


@dataclass(frozen=True)
class ResourcePackageItem:
    product_name: str
    instance_name: str
    available_amount: float | None
    total_amount: float | None
    unit: str
    expiry_time: str
    status: str


@dataclass(frozen=True)
class ResourcePackageSnapshot:
    count: int
    items: tuple[ResourcePackageItem, ...]


@dataclass(frozen=True)
class CouponItem:
    coupon_name: str
    remaining_amount: float | None
    total_amount: float | None
    expired_time: str
    status: int | None


@dataclass(frozen=True)
class CouponSnapshot:
    count: int
    total_remaining_amount: float
    items: tuple[CouponItem, ...]


class VolcengineAPIError(RuntimeError):
    def __init__(self, *, action: str, status_code: int, provider_code: str, request_id: str = ""):
        self.action = action
        self.status_code = status_code
        self.provider_code = provider_code
        self.request_id = request_id
        super().__init__(f"Volcengine {action} failed: {provider_code}")


class VolcengineUsageClient:
    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        now: Callable[[], datetime] | None = None,
        endpoint: str = "https://open.volcengineapi.com",
    ):
        self.access_key_id = access_key_id.strip()
        self._secret = secret_access_key.strip()
        self.transport = transport
        self.now = now or (lambda: datetime.now(UTC))
        self.endpoint = endpoint.rstrip("/")

    @staticmethod
    def _hash(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    @staticmethod
    def _hmac(key: bytes, value: str) -> bytes:
        return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()

    def _headers(self, *, method: str, query: dict[str, str], payload: bytes, service: str, region: str) -> dict[str, str]:
        moment = self.now().astimezone(UTC)
        x_date = moment.strftime("%Y%m%dT%H%M%SZ")
        short_date = moment.strftime("%Y%m%d")
        host = "open.volcengineapi.com"
        payload_hash = self._hash(payload)
        canonical_query = "&".join(
            f"{quote(str(key), safe='-_.~')}={quote(str(value), safe='-_.~')}"
            for key, value in sorted(query.items())
        )
        content_type = "application/json; charset=utf-8"
        canonical_headers = f"content-type:{content_type}\nhost:{host}\nx-content-sha256:{payload_hash}\nx-date:{x_date}\n"
        signed_headers = "content-type;host;x-content-sha256;x-date"
        canonical_request = f"{method}\n/\n{canonical_query}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
        scope = f"{short_date}/{region}/{service}/request"
        string_to_sign = f"HMAC-SHA256\n{x_date}\n{scope}\n{self._hash(canonical_request.encode('utf-8'))}"
        date_key = self._hmac(self._secret.encode("utf-8"), short_date)
        region_key = self._hmac(date_key, region)
        service_key = self._hmac(region_key, service)
        signing_key = self._hmac(service_key, "request")
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        return {
            "Content-Type": content_type,
            "Host": host,
            "X-Date": x_date,
            "X-Content-Sha256": payload_hash,
            "Authorization": f"HMAC-SHA256 Credential={self.access_key_id}/{scope}, SignedHeaders={signed_headers}, Signature={signature}",
        }

    def _request(self, *, action: str, version: str, service: str, region: str, body: dict[str, object] | None = None) -> dict[str, object]:
        query = {"Action": action, "Version": version}
        payload = json.dumps(body or {}, ensure_ascii=False, separators=(",", ":")).encode("utf-8") if body is not None else b""
        method = "POST" if body is not None else "GET"
        headers = self._headers(method=method, query=query, payload=payload, service=service, region=region)
        with httpx.Client(transport=self.transport, timeout=20) as client:
            response = client.request(method, self.endpoint, params=query, headers=headers, content=payload or None)
        try:
            data = response.json()
        except ValueError:
            data = {}
        metadata = data.get("ResponseMetadata", {}) if isinstance(data, dict) else {}
        error = metadata.get("Error", {}) if isinstance(metadata, dict) else {}
        if error or response.is_error:
            provider_code = str(error.get("Code") or f"HTTP_{response.status_code}")
            raise VolcengineAPIError(
                action=action,
                status_code=response.status_code,
                provider_code=provider_code,
                request_id=str(metadata.get("RequestId", "")),
            )
        return data.get("Result", {})

    def query_balance(self) -> BalanceSnapshot:
        result = self._request(action="QueryBalanceAcct", version="2022-01-01", service="billing", region="cn-beijing")
        return BalanceSnapshot(
            available_balance=float(result.get("AvailableBalance", 0) or 0),
            cash_balance=float(result.get("CashBalance", 0) or 0),
            freeze_amount=float(result.get("FreezeAmount", 0) or 0),
            arrears_balance=float(result.get("ArrearsBalance", 0) or 0),
            credit_limit=float(result["CreditLimit"]) if result.get("CreditLimit") not in (None, "") else None,
        )

    def get_inference_usage(self, start_time: str, end_time: str, interval: str = "Day") -> ArkUsageSnapshot:
        body = {"QueryInterval": interval, "StartTime": start_time, "EndTime": end_time, "ShowWindowDetail": False}
        try:
            result = self._request(
                action="GetInferenceUsage",
                version="2024-01-01",
                service="ark_stg",
                region="cn-beijing",
                body=body,
            )
        except VolcengineAPIError as error:
            if error.provider_code != "InvalidActionOrVersion":
                raise
            result = self._request(
                action="GetInferenceUsage",
                version="2024-01-01",
                service="ark",
                region="cn-beijing",
                body=body,
            )
        totals: dict[str, int | None] = {
            name: int(float(result[name])) if result.get(name) not in (None, "") else None
            for name in ("InputTokens", "OutputTokens", "TotalTokens")
        }
        fields = result.get("Fields", result.get("fields", []))
        records = result.get("Records", result.get("records", []))
        field_names = [str(item.get("Name", item.get("name", ""))) for item in fields if isinstance(item, dict)]
        for record in records if isinstance(records, list) else []:
            if isinstance(record, dict):
                values = record
            elif isinstance(record, list) and field_names:
                values = dict(zip(field_names, record, strict=False))
            else:
                continue
            for name in totals:
                try:
                    if values.get(name) in (None, ""):
                        continue
                    totals[name] = (totals[name] or 0) + int(float(values[name]))
                except (TypeError, ValueError):
                    continue
        return ArkUsageSnapshot(
            total_tokens=totals["TotalTokens"],
            input_tokens=totals["InputTokens"],
            output_tokens=totals["OutputTokens"],
            data_count=int(result.get("DataCount", 0) or 0),
        )

    def list_model_activations(self) -> ModelEntitlementSnapshot:
        result = self._request(
            action="ListModelActivations",
            version="2024-01-01",
            service="ark",
            region="cn-beijing",
            body={"PageNumber": 1, "PageSize": 100, "WithPrice": False, "WithFreeUsage": True},
        )
        raw_items = result.get("Items", [])
        items: list[ModelFreeEntitlement] = []
        for raw in raw_items if isinstance(raw_items, list) else []:
            if not isinstance(raw, dict):
                continue
            initial = raw.get("InitialInferenceFreeUsage")
            initial = initial if isinstance(initial, dict) else {}
            total = int(float(initial["Total"])) if initial.get("Total") not in (None, "") else None
            consumed = int(float(initial["Consumed"])) if initial.get("Consumed") not in (None, "") else None
            remaining = max(total - (consumed or 0), 0) if total is not None else None
            packs = raw.get("FreeResourcePackItems")
            packs = packs if isinstance(packs, list) else []
            pack_count = len(packs)
            pack_total = sum(int(float(pack.get("Total", 0) or 0)) for pack in packs if isinstance(pack, dict))
            pack_consumed = sum(int(float(pack.get("Consumed", 0) or 0)) for pack in packs if isinstance(pack, dict))
            pack_reclaimed = sum(int(float(pack.get("Reclaimed", 0) or 0)) for pack in packs if isinstance(pack, dict))
            pack_remaining = max(pack_total - pack_consumed - pack_reclaimed, 0)
            items.append(
                ModelFreeEntitlement(
                    foundation_model_name=str(raw.get("FoundationModelName", "")),
                    display_name=str(raw.get("DisplayName") or raw.get("FoundationModelName") or "未命名模型"),
                    initial_total_tokens=total,
                    initial_consumed_tokens=consumed,
                    initial_remaining_tokens=remaining,
                    resource_pack_count=pack_count,
                    resource_pack_total_tokens=pack_total,
                    resource_pack_consumed_tokens=pack_consumed,
                    resource_pack_remaining_tokens=pack_remaining,
                )
            )
        with_initial = [item for item in items if item.initial_total_tokens is not None]
        initial_remaining = sum(item.initial_remaining_tokens or 0 for item in with_initial)
        resource_pack_remaining = sum(item.resource_pack_remaining_tokens for item in items)
        return ModelEntitlementSnapshot(
            total_count=int(result.get("TotalCount", len(items)) or len(items)),
            models_with_initial_free_usage=len(with_initial),
            initial_total_tokens=sum(item.initial_total_tokens or 0 for item in with_initial),
            initial_consumed_tokens=sum(item.initial_consumed_tokens or 0 for item in with_initial),
            initial_remaining_tokens=initial_remaining,
            resource_pack_count=sum(item.resource_pack_count for item in items),
            items=tuple(items),
            resource_pack_total_tokens=sum(item.resource_pack_total_tokens for item in items),
            resource_pack_consumed_tokens=sum(item.resource_pack_consumed_tokens for item in items),
            resource_pack_remaining_tokens=resource_pack_remaining,
            total_remaining_tokens=initial_remaining + resource_pack_remaining,
        )

    @staticmethod
    def _optional_float(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def list_resource_packages(self) -> ResourcePackageSnapshot:
        raw_items: list[object] = []
        next_token = ""
        seen_tokens: set[str] = set()
        for _ in range(100):
            body = {"MaxResults": "20", "ResourceType": "Package", "Status": "Effective"}
            if next_token:
                body["NextToken"] = next_token
            result = self._request(
                action="ListResourcePackages",
                version="2022-01-01",
                service="billing",
                region="cn-beijing",
                body=body,
            )
            page_items = result.get("List", [])
            if isinstance(page_items, list):
                raw_items.extend(page_items)
            next_token = str(result.get("NextToken", "") or "")
            if not next_token or next_token in seen_tokens:
                break
            seen_tokens.add(next_token)
        items = tuple(
            ResourcePackageItem(
                product_name=str(raw.get("ProductName", "")),
                instance_name=str(raw.get("InstanceName", "")),
                available_amount=self._optional_float(raw.get("AvailableAmount")),
                total_amount=self._optional_float(raw.get("TotalAmount")),
                unit=str(raw.get("Unit") or raw.get("SpecificationUnit") or ""),
                expiry_time=str(raw.get("ExpiryTime", "")),
                status=str(raw.get("Status", "")),
            )
            for raw in raw_items if isinstance(raw, dict)
        )
        return ResourcePackageSnapshot(count=len(items), items=items)

    def list_coupons(self) -> CouponSnapshot:
        result = self._request(
            action="ListCoupons",
            version="2022-01-01",
            service="billing",
            region="cn-beijing",
            body={"Limit": 100, "Offset": 0},
        )
        raw_items = result.get("List", [])
        items = tuple(
            CouponItem(
                coupon_name=str(raw.get("CouponName", "")),
                remaining_amount=self._optional_float(raw.get("RemainingAmount")),
                total_amount=self._optional_float(raw.get("TotalAmount")),
                expired_time=str(raw.get("ExpiredTime", "")),
                status=int(raw["Status"]) if raw.get("Status") not in (None, "") else None,
            )
            for raw in raw_items if isinstance(raw, dict)
        )
        return CouponSnapshot(
            count=int(result.get("Total", len(items)) or len(items)),
            total_remaining_amount=sum(item.remaining_amount or 0 for item in items),
            items=items,
        )
