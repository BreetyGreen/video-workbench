from datetime import UTC, datetime
import json

import httpx
import pytest

from app.adapters import volcengine_usage
from app.adapters.volcengine_usage import VolcengineUsageClient


def test_query_balance_signs_request_and_parses_amounts():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, json={"Result": {"AvailableBalance": "77.01", "CashBalance": "83.01", "CreditLimit": "120.00", "FreezeAmount": "5.00", "ArrearsBalance": "0"}})

    client = VolcengineUsageClient(
        "AKLTEXAMPLE",
        "secret-value-never-output",
        transport=httpx.MockTransport(handler),
        now=lambda: datetime(2026, 8, 19, 6, 0, tzinfo=UTC),
    )

    result = client.query_balance()
    request = seen["request"]

    assert result.available_balance == 77.01
    assert result.credit_limit == 120.0
    assert request.url.params["Action"] == "QueryBalanceAcct"
    assert request.headers["Authorization"].startswith("HMAC-SHA256 Credential=AKLTEXAMPLE/20260819/")
    assert "secret-value" not in str(request.headers)


def test_get_inference_usage_parses_token_windows():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["Action"] == "GetInferenceUsage"
        return httpx.Response(
            200,
            json={"Result": {"TotalTokens": 1441, "InputTokens": 1000, "OutputTokens": 441, "DataCount": 2}},
        )

    client = VolcengineUsageClient(
        "AKLTEXAMPLE",
        "secret",
        transport=httpx.MockTransport(handler),
        now=lambda: datetime(2026, 8, 19, 6, 0, tzinfo=UTC),
    )

    result = client.get_inference_usage("2026-08-01", "2026-08-20")

    assert result.total_tokens == 1441
    assert result.input_tokens == 1000
    assert result.output_tokens == 441
    assert result.data_count == 2


def test_get_inference_usage_does_not_invent_zero_tokens_when_provider_only_returns_count():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Result": {"DataCount": 1}})

    client = VolcengineUsageClient("AKLTEXAMPLE", "secret", transport=httpx.MockTransport(handler))

    result = client.get_inference_usage("2026-08-01", "2026-08-20")

    assert result.data_count == 1
    assert result.total_tokens is None
    assert result.input_tokens is None
    assert result.output_tokens is None


def test_list_model_activations_requests_and_sums_initial_free_usage():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.read().decode("utf-8")
        assert request.url.params["Action"] == "ListModelActivations"
        assert "/cn-beijing/ark/request" in request.headers["Authorization"]
        return httpx.Response(
            200,
            json={
                "Result": {
                    "TotalCount": 2,
                    "PageNumber": 1,
                    "PageSize": 100,
                    "Items": [
                        {
                            "FoundationModelName": "doubao-seed-1.6",
                            "DisplayName": "Doubao Seed 1.6",
                            "InitialInferenceFreeUsage": {"Total": 1_000_000, "Consumed": 250_000},
                            "FreeResourcePackItems": [],
                        },
                        {
                            "FoundationModelName": "doubao-vision",
                            "DisplayName": "Doubao Vision",
                            "FreeResourcePackItems": [{"Total": 500, "Consumed": 100}],
                        },
                    ],
                }
            },
        )

    client = VolcengineUsageClient("AKLTEXAMPLE", "secret", transport=httpx.MockTransport(handler))

    result = client.list_model_activations()

    assert '"WithFreeUsage":true' in seen["body"]
    assert result.total_count == 2
    assert result.models_with_initial_free_usage == 1
    assert result.initial_total_tokens == 1_000_000
    assert result.initial_consumed_tokens == 250_000
    assert result.initial_remaining_tokens == 750_000
    assert result.resource_pack_count == 1
    assert result.resource_pack_total_tokens == 500
    assert result.resource_pack_consumed_tokens == 100
    assert result.resource_pack_remaining_tokens == 400
    assert result.total_remaining_tokens == 750_400
    assert result.items[0].display_name == "Doubao Seed 1.6"


def test_list_billing_entitlements_parses_resource_packages_and_coupons():
    actions = []

    def handler(request: httpx.Request) -> httpx.Response:
        action = request.url.params["Action"]
        actions.append(action)
        body = request.read().decode("utf-8")
        if action == "ListResourcePackages":
            assert '"ResourceType":"Package"' in body
            assert '"MaxResults":"20"' in body
            return httpx.Response(
                200,
                json={
                    "Result": {
                        "List": [
                            {
                                "ProductName": "豆包语音",
                                "InstanceName": "赠送资源包",
                                "AvailableAmount": "14018",
                                "TotalAmount": "20000",
                                "Unit": "字符",
                                "ExpiryTime": "2026-11-19T00:00:00Z",
                                "Status": "Effective",
                            }
                        ]
                    }
                },
            )
        assert action == "ListCoupons"
        return httpx.Response(
            200,
            json={
                "Result": {
                    "Total": 1,
                    "List": [
                        {
                            "CouponName": "新用户代金券",
                            "RemainingAmount": 18.5,
                            "TotalAmount": 20,
                            "ExpiredTime": "2026-09-01T00:00:00Z",
                            "Status": 1,
                        }
                    ],
                }
            },
        )

    client = VolcengineUsageClient("AKLTEXAMPLE", "secret", transport=httpx.MockTransport(handler))

    packages = client.list_resource_packages()
    coupons = client.list_coupons()

    assert actions == ["ListResourcePackages", "ListCoupons"]
    assert packages.count == 1
    assert packages.items[0].available_amount == 14018
    assert packages.items[0].unit == "字符"
    assert coupons.count == 1
    assert coupons.total_remaining_amount == 18.5
    assert coupons.items[0].coupon_name == "新用户代金券"


def test_list_resource_packages_follows_next_token_until_complete():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        bodies.append(body)
        suffix = "二" if body.get("NextToken") else "一"
        result = {
            "List": [{"ProductName": f"资源包{suffix}", "AvailableAmount": "1", "Unit": "次"}],
        }
        if "NextToken" not in body:
            result["NextToken"] = "next-page"
        return httpx.Response(200, json={"Result": result})

    client = VolcengineUsageClient("AKLTEXAMPLE", "secret", transport=httpx.MockTransport(handler))

    result = client.list_resource_packages()

    assert result.count == 2
    assert [item.product_name for item in result.items] == ["资源包一", "资源包二"]
    assert bodies[1]["NextToken"] == "next-page"


def test_get_inference_usage_sums_documented_field_records_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/cn-beijing/ark_stg/request" in request.headers["Authorization"]
        return httpx.Response(
            200,
            json={
                "Result": {
                    "DataCount": 2,
                    "Fields": [
                        {"Name": "Day", "Type": "DATE"},
                        {"Name": "InputTokens", "Type": "BIGINT"},
                        {"Name": "OutputTokens", "Type": "BIGINT"},
                        {"Name": "TotalTokens", "Type": "BIGINT"},
                    ],
                    "Records": [
                        ["2026-08-18", "10", "20", "30"],
                        ["2026-08-19", "40", "50", "90"],
                    ],
                }
            },
        )

    client = VolcengineUsageClient("AKLTEXAMPLE", "secret", transport=httpx.MockTransport(handler))

    result = client.get_inference_usage("2026-08-18", "2026-08-20")

    assert result.input_tokens == 50
    assert result.output_tokens == 70
    assert result.total_tokens == 120


def test_get_inference_usage_retries_current_ark_signing_scope_after_legacy_route_is_removed():
    signed_scopes = []

    def handler(request: httpx.Request) -> httpx.Response:
        signed_scopes.append(request.headers["Authorization"])
        if "/ark_stg/request" in request.headers["Authorization"]:
            return httpx.Response(
                404,
                json={
                    "ResponseMetadata": {
                        "RequestId": "legacy-route-request",
                        "Error": {"Code": "InvalidActionOrVersion"},
                    }
                },
            )
        return httpx.Response(
            200,
            json={"Result": {"TotalTokens": 42, "InputTokens": 30, "OutputTokens": 12, "DataCount": 1}},
        )

    client = VolcengineUsageClient(
        "AKLTEXAMPLE",
        "secret",
        transport=httpx.MockTransport(handler),
        now=lambda: datetime(2026, 8, 19, 6, 0, tzinfo=UTC),
    )

    result = client.get_inference_usage("2026-08-01", "2026-08-20")

    assert len(signed_scopes) == 2
    assert "/ark_stg/request" in signed_scopes[0]
    assert "/ark/request" in signed_scopes[1]
    assert result.total_tokens == 42


def test_provider_error_preserves_safe_code_stage_and_request_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "ResponseMetadata": {
                    "RequestId": "req-safe-123",
                    "Error": {"Code": "AccessDenied", "Message": "permission denied"},
                }
            },
        )

    client = VolcengineUsageClient(
        "AKLTEXAMPLE",
        "secret-value-never-output",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(volcengine_usage.VolcengineAPIError) as caught:
        client.query_balance()

    assert caught.value.action == "QueryBalanceAcct"
    assert caught.value.status_code == 403
    assert caught.value.provider_code == "AccessDenied"
    assert caught.value.request_id == "req-safe-123"
    assert "secret-value" not in str(caught.value)
