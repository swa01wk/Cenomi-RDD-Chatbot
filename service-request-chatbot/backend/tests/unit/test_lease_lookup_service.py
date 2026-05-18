"""Unit tests — lease_lookup_service.

Test groups
-----------
TestLeaseRecord                     — Pydantic model construction and validation.
TestLeaseLookupQuery                — Query model + has_identifiers helper.
TestMockLeaseLookupServiceBasic     — Smoke-tests and result shape.
TestMockLookupByLeaseCode           — Exact lease_code match behaviour.
TestMockLookupByBrandMall           — brand + mall combined search.
TestMockLookupByBrandOnly           — brand-only substring matching.
TestMockLookupByMallOnly            — mall-only substring matching.
TestMockLookupNoMatch               — Empty result when nothing matches.
TestMockLookupMultiMatch            — Multiple records returned.
TestMockLookupCustomRecords         — Custom seed data injection.
TestHttpLeaseLookupServiceSuccess   — 200 response parsed into LeaseRecord list.
TestHttpLeaseLookupServiceErrors    — 404, 500, and connection-error handling.
TestHttpLeaseLookupParamBuilding    — Query string parameters.
TestGetLeaseLookupServiceFactory    — Factory helper selects correct backend.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.services.lease_lookup_service import (
    AbstractLeaseLookupService,
    HttpLeaseLookupService,
    LeaseRecord,
    LeaseLookupQuery,
    LeaseLookupResult,
    MockLeaseLookupService,
    _MOCK_RECORDS,
    get_lease_lookup_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UA_RECORD: dict[str, Any] = {
    "lease_code": "t0105712",
    "lease_id": 95404,
    "contract_id": 95404,
    "brand": "Brand Under Armour",
    "brand_id": 267,
    "mall": "Jawharat Jeddah",
    "property_id": 3041,
    "tenant_profile_id": 116,
    "unit_codes": ["FF050"],
    "contracted_area": 420.0,
    "city": "Jeddah",
    "lease_brand_mall": "t0105712 - Brand Under Armour - Jawharat Jeddah",
}


def _make_http_response(
    status_code: int = 200,
    body: Any = None,
    raise_exc: Exception | None = None,
) -> MagicMock:
    """Build a mock httpx Response."""
    resp = MagicMock()
    resp.status_code = status_code
    if body is not None:
        resp.json.return_value = body
        resp.text = json.dumps(body)
    else:
        resp.json.side_effect = ValueError("no body")
        resp.text = ""
    return resp


# ---------------------------------------------------------------------------
# TestLeaseRecord
# ---------------------------------------------------------------------------


class TestLeaseRecord:
    def test_constructs_from_dict(self) -> None:
        record = LeaseRecord.model_validate(_UA_RECORD)
        assert record.lease_code == "t0105712"
        assert record.brand == "Brand Under Armour"
        assert record.unit_codes == ["FF050"]
        assert record.contracted_area == 420.0

    def test_unit_codes_is_list(self) -> None:
        record = LeaseRecord.model_validate(_UA_RECORD)
        assert isinstance(record.unit_codes, list)

    def test_missing_required_field_raises(self) -> None:
        from pydantic import ValidationError

        bad = dict(_UA_RECORD)
        del bad["lease_id"]
        with pytest.raises(ValidationError):
            LeaseRecord.model_validate(bad)

    def test_model_dump_round_trip(self) -> None:
        record = LeaseRecord.model_validate(_UA_RECORD)
        dumped = record.model_dump()
        assert dumped["lease_code"] == _UA_RECORD["lease_code"]
        assert dumped["lease_id"] == _UA_RECORD["lease_id"]


# ---------------------------------------------------------------------------
# TestLeaseLookupQuery
# ---------------------------------------------------------------------------


class TestLeaseLookupQuery:
    def test_has_identifiers_true_with_lease_code(self) -> None:
        q = LeaseLookupQuery(lease_code="t0001")
        assert q.has_identifiers() is True

    def test_has_identifiers_true_with_brand(self) -> None:
        q = LeaseLookupQuery(brand="Nike")
        assert q.has_identifiers() is True

    def test_has_identifiers_true_with_mall(self) -> None:
        q = LeaseLookupQuery(mall="Riyadh Park")
        assert q.has_identifiers() is True

    def test_has_identifiers_false_when_all_none(self) -> None:
        q = LeaseLookupQuery()
        assert q.has_identifiers() is False

    def test_model_dump_excludes_none_by_default_for_tracing(self) -> None:
        q = LeaseLookupQuery(lease_code="t0001")
        dumped = q.model_dump(exclude_none=True)
        assert "brand" not in dumped
        assert "mall" not in dumped

    def test_is_abstract_service_subtype(self) -> None:
        svc = MockLeaseLookupService()
        assert isinstance(svc, AbstractLeaseLookupService)


# ---------------------------------------------------------------------------
# TestMockLeaseLookupServiceBasic
# ---------------------------------------------------------------------------


class TestMockLeaseLookupServiceBasic:
    @pytest.mark.asyncio
    async def test_returns_lookup_result_type(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert isinstance(result, LeaseLookupResult)

    @pytest.mark.asyncio
    async def test_status_code_is_200(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_error_is_none_on_success(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert result.error is None

    @pytest.mark.asyncio
    async def test_latency_ms_is_non_negative(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(brand="Nike"))
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_response_payload_contains_leases_key(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert result.response_payload is not None
        assert "leases" in result.response_payload

    @pytest.mark.asyncio
    async def test_request_payload_contains_endpoint(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert "endpoint" in result.request_payload

    @pytest.mark.asyncio
    async def test_endpoint_is_mock_scheme(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert result.endpoint.startswith("mock://")


# ---------------------------------------------------------------------------
# TestMockLookupByLeaseCode
# ---------------------------------------------------------------------------


class TestMockLookupByLeaseCode:
    @pytest.mark.asyncio
    async def test_exact_match_returns_one_record(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert len(result.matches) == 1
        assert result.matches[0].lease_code == "t0105712"

    @pytest.mark.asyncio
    async def test_wrong_code_returns_empty(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(lease_code="NONEXISTENT"))
        assert len(result.matches) == 0

    @pytest.mark.asyncio
    async def test_lease_code_takes_priority_over_brand(self) -> None:
        svc = MockLeaseLookupService()
        # brand exists for two records; lease_code should narrow to one
        result = await svc.lookup(LeaseLookupQuery(lease_code="t0208831", brand="Nike"))
        assert len(result.matches) == 1
        assert result.matches[0].lease_code == "t0208831"

    @pytest.mark.asyncio
    async def test_match_has_all_fields(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        record = result.matches[0]
        assert record.brand == "Brand Under Armour"
        assert record.mall == "Jawharat Jeddah"
        assert record.city == "Jeddah"
        assert record.tenant_profile_id == 116


# ---------------------------------------------------------------------------
# TestMockLookupByBrandMall
# ---------------------------------------------------------------------------


class TestMockLookupByBrandMall:
    @pytest.mark.asyncio
    async def test_brand_and_mall_returns_exact_match(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(brand="Nike", mall="Riyadh Park"))
        assert len(result.matches) == 1
        assert result.matches[0].lease_code == "t0208831"

    @pytest.mark.asyncio
    async def test_brand_and_mall_case_insensitive(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(brand="nike", mall="riyadh park"))
        assert len(result.matches) == 1

    @pytest.mark.asyncio
    async def test_brand_and_mall_no_match_returns_empty(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(brand="Nike", mall="Nonexistent Mall"))
        assert len(result.matches) == 0


# ---------------------------------------------------------------------------
# TestMockLookupByBrandOnly
# ---------------------------------------------------------------------------


class TestMockLookupByBrandOnly:
    @pytest.mark.asyncio
    async def test_brand_only_returns_all_matching(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(brand="Nike"))
        assert len(result.matches) == 2
        codes = {r.lease_code for r in result.matches}
        assert "t0208831" in codes
        assert "t0301144" in codes

    @pytest.mark.asyncio
    async def test_brand_only_case_insensitive(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(brand="NIKE"))
        assert len(result.matches) == 2

    @pytest.mark.asyncio
    async def test_brand_only_substring_match(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(brand="Under Armour"))
        assert len(result.matches) >= 1

    @pytest.mark.asyncio
    async def test_brand_only_no_match(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(brand="Nonexistent Brand XYZ"))
        assert len(result.matches) == 0


# ---------------------------------------------------------------------------
# TestMockLookupByMallOnly
# ---------------------------------------------------------------------------


class TestMockLookupByMallOnly:
    @pytest.mark.asyncio
    async def test_mall_only_returns_matching(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(mall="Riyadh Park"))
        assert len(result.matches) == 1
        assert result.matches[0].mall == "Riyadh Park"

    @pytest.mark.asyncio
    async def test_mall_only_case_insensitive(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(mall="riyadh park"))
        assert len(result.matches) == 1

    @pytest.mark.asyncio
    async def test_mall_only_no_match(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(mall="Nonexistent Mall"))
        assert len(result.matches) == 0

    @pytest.mark.asyncio
    async def test_jeddah_mall_returns_results(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(mall="Jawharat Jeddah"))
        assert len(result.matches) >= 1


# ---------------------------------------------------------------------------
# TestMockLookupNoMatch
# ---------------------------------------------------------------------------


class TestMockLookupNoMatch:
    @pytest.mark.asyncio
    async def test_no_match_returns_empty_list(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(lease_code="DOES_NOT_EXIST"))
        assert result.matches == []

    @pytest.mark.asyncio
    async def test_no_match_status_code_still_200(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(lease_code="DOES_NOT_EXIST"))
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_no_match_error_is_none(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(lease_code="DOES_NOT_EXIST"))
        assert result.error is None


# ---------------------------------------------------------------------------
# TestMockLookupMultiMatch
# ---------------------------------------------------------------------------


class TestMockLookupMultiMatch:
    @pytest.mark.asyncio
    async def test_brand_query_returns_multiple_for_nike(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(brand="Nike"))
        assert len(result.matches) > 1

    @pytest.mark.asyncio
    async def test_all_matches_are_lease_records(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(brand="Nike"))
        for match in result.matches:
            assert isinstance(match, LeaseRecord)

    @pytest.mark.asyncio
    async def test_response_payload_count_matches_list_length(self) -> None:
        svc = MockLeaseLookupService()
        result = await svc.lookup(LeaseLookupQuery(brand="Nike"))
        assert result.response_payload is not None
        assert result.response_payload["count"] == len(result.matches)


# ---------------------------------------------------------------------------
# TestMockLookupCustomRecords
# ---------------------------------------------------------------------------


class TestMockLookupCustomRecords:
    def _make_record(self, lease_code: str, brand: str, mall: str) -> LeaseRecord:
        return LeaseRecord(
            lease_code=lease_code,
            lease_id=1,
            contract_id=1,
            brand=brand,
            brand_id=1,
            mall=mall,
            property_id=1,
            tenant_profile_id=1,
            unit_codes=["A01"],
            contracted_area=100.0,
            city="Riyadh",
            lease_brand_mall=f"{lease_code} - {brand} - {mall}",
        )

    @pytest.mark.asyncio
    async def test_custom_records_replace_defaults(self) -> None:
        custom = [self._make_record("CUSTOM-001", "TestBrand", "TestMall")]
        svc = MockLeaseLookupService(records=custom)
        result = await svc.lookup(LeaseLookupQuery(lease_code="CUSTOM-001"))
        assert len(result.matches) == 1
        assert result.matches[0].brand == "TestBrand"

    @pytest.mark.asyncio
    async def test_default_records_not_returned_with_custom_seed(self) -> None:
        custom = [self._make_record("CUSTOM-001", "TestBrand", "TestMall")]
        svc = MockLeaseLookupService(records=custom)
        result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert len(result.matches) == 0

    @pytest.mark.asyncio
    async def test_custom_latency_reported(self) -> None:
        svc = MockLeaseLookupService(simulated_latency_ms=99)
        result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert result.latency_ms == 99


# ---------------------------------------------------------------------------
# TestHttpLeaseLookupServiceSuccess
# ---------------------------------------------------------------------------


class TestHttpLeaseLookupServiceSuccess:
    def _make_client_ctx(self, response: MagicMock) -> MagicMock:
        """Return a mock for ``httpx.AsyncClient`` context manager."""
        client = AsyncMock()
        client.get = AsyncMock(return_value=response)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=client)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    @pytest.mark.asyncio
    async def test_200_response_returns_records(self) -> None:
        body = {"leases": [_UA_RECORD]}
        resp = _make_http_response(200, body)
        svc = HttpLeaseLookupService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=self._make_client_ctx(resp)):
            result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert len(result.matches) == 1
        assert result.matches[0].lease_code == "t0105712"
        assert result.status_code == 200
        assert result.error is None

    @pytest.mark.asyncio
    async def test_200_data_envelope_parsed(self) -> None:
        body = {"data": [_UA_RECORD]}
        resp = _make_http_response(200, body)
        svc = HttpLeaseLookupService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=self._make_client_ctx(resp)):
            result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert len(result.matches) == 1

    @pytest.mark.asyncio
    async def test_200_empty_list_returns_no_matches(self) -> None:
        body: dict[str, Any] = {"leases": []}
        resp = _make_http_response(200, body)
        svc = HttpLeaseLookupService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=self._make_client_ctx(resp)):
            result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert result.matches == []
        assert result.error is None

    @pytest.mark.asyncio
    async def test_latency_ms_is_populated(self) -> None:
        body = {"leases": [_UA_RECORD]}
        resp = _make_http_response(200, body)
        svc = HttpLeaseLookupService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=self._make_client_ctx(resp)):
            result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert isinstance(result.latency_ms, int)
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_response_payload_stored(self) -> None:
        body = {"leases": [_UA_RECORD]}
        resp = _make_http_response(200, body)
        svc = HttpLeaseLookupService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=self._make_client_ctx(resp)):
            result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert result.response_payload == body

    @pytest.mark.asyncio
    async def test_request_payload_contains_endpoint_and_params(self) -> None:
        body = {"leases": [_UA_RECORD]}
        resp = _make_http_response(200, body)
        svc = HttpLeaseLookupService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=self._make_client_ctx(resp)):
            result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert "endpoint" in result.request_payload
        assert "params" in result.request_payload


# ---------------------------------------------------------------------------
# TestHttpLeaseLookupServiceErrors
# ---------------------------------------------------------------------------


class TestHttpLeaseLookupServiceErrors:
    def _make_client_ctx(self, response: MagicMock) -> MagicMock:
        client = AsyncMock()
        client.get = AsyncMock(return_value=response)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=client)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    def _make_error_client_ctx(self, exc: Exception) -> MagicMock:
        client = AsyncMock()
        client.get = AsyncMock(side_effect=exc)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=client)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    @pytest.mark.asyncio
    async def test_404_returns_error_and_empty_matches(self) -> None:
        resp = _make_http_response(404, None)
        svc = HttpLeaseLookupService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=self._make_client_ctx(resp)):
            result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert result.matches == []
        assert result.status_code == 404
        assert "404" in (result.error or "")

    @pytest.mark.asyncio
    async def test_500_returns_error(self) -> None:
        resp = _make_http_response(500, None)
        svc = HttpLeaseLookupService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=self._make_client_ctx(resp)):
            result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert result.matches == []
        assert "500" in (result.error or "")

    @pytest.mark.asyncio
    async def test_connection_error_returns_none_status_code(self) -> None:
        import httpx as _httpx

        exc = _httpx.ConnectError("connection refused")
        svc = HttpLeaseLookupService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=self._make_error_client_ctx(exc)):
            result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert result.matches == []
        assert result.status_code is None
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_connection_error_error_message_non_empty(self) -> None:
        import httpx as _httpx

        exc = _httpx.TimeoutException("timed out")
        svc = HttpLeaseLookupService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=self._make_error_client_ctx(exc)):
            result = await svc.lookup(LeaseLookupQuery(brand="Nike"))
        assert result.error
        assert len(result.error) > 0

    @pytest.mark.asyncio
    async def test_connection_error_response_payload_is_none(self) -> None:
        import httpx as _httpx

        exc = _httpx.ConnectError("connection refused")
        svc = HttpLeaseLookupService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=self._make_error_client_ctx(exc)):
            result = await svc.lookup(LeaseLookupQuery(lease_code="t0105712"))
        assert result.response_payload is None


# ---------------------------------------------------------------------------
# TestHttpLeaseLookupParamBuilding
# ---------------------------------------------------------------------------


class TestHttpLeaseLookupParamBuilding:
    def test_lease_code_param_only(self) -> None:
        svc = HttpLeaseLookupService.__new__(HttpLeaseLookupService)
        params = svc._build_params(LeaseLookupQuery(lease_code="t0105712"))
        assert params == {"lease_code": "t0105712"}

    def test_brand_mall_params(self) -> None:
        svc = HttpLeaseLookupService.__new__(HttpLeaseLookupService)
        params = svc._build_params(LeaseLookupQuery(brand="Nike", mall="Riyadh Park"))
        assert params == {"brand": "Nike", "mall": "Riyadh Park"}

    def test_all_params(self) -> None:
        svc = HttpLeaseLookupService.__new__(HttpLeaseLookupService)
        params = svc._build_params(
            LeaseLookupQuery(lease_code="t0001", brand="Nike", mall="Riyadh Park")
        )
        assert "lease_code" in params
        assert "brand" in params
        assert "mall" in params

    def test_none_fields_excluded(self) -> None:
        svc = HttpLeaseLookupService.__new__(HttpLeaseLookupService)
        params = svc._build_params(LeaseLookupQuery(mall="Riyadh Park"))
        assert "lease_code" not in params
        assert "brand" not in params


# ---------------------------------------------------------------------------
# TestGetLeaseLookupServiceFactory
# ---------------------------------------------------------------------------


class TestGetLeaseLookupServiceFactory:
    def test_returns_mock_when_no_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "app.agents.services.lease_lookup_service.settings",
            MagicMock(lease_tenant_api_base_url=None),
        )
        svc = get_lease_lookup_service()
        assert isinstance(svc, MockLeaseLookupService)

    def test_returns_http_when_base_url_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "app.agents.services.lease_lookup_service.settings",
            MagicMock(lease_tenant_api_base_url="http://api.example.com"),
        )
        svc = get_lease_lookup_service()
        assert isinstance(svc, HttpLeaseLookupService)

    def test_mock_records_are_pre_populated(self) -> None:
        assert len(_MOCK_RECORDS) >= 3
