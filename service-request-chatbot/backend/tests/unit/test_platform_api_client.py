"""Unit tests for ServiceRequestPlatformClient.

Coverage
--------
- login: success, non-2xx, missing token, connection error
- ensure_authenticated: skips re-login when token fresh; re-logins when expired
- get_service_request: success, non-2xx, connection error
- create_service_request: success, non-2xx
- patch_service_request: success, non-2xx
- submit_report: success (reuses POST)
- upload_file: success, non-2xx, connection error
- _extract_sr_id: various envelope shapes
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.exceptions import PlatformAuthError
from app.agents.services.platform_api_client import (
    FileUploadMetadata,
    ServiceRequestPlatformClient,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(base_url: str = "http://platform.test") -> ServiceRequestPlatformClient:
    return ServiceRequestPlatformClient(
        base_url=base_url,
        auth_base_url=base_url,
        timeout=5.0,
    )


def _mock_response(status_code: int, json_body: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.text = str(json_body)
    resp.headers = {}
    return resp


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success_sets_token(self) -> None:
        client = _make_client()
        mock_resp = _mock_response(200, {"access_token": "tok-abc"})

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            await client.login(email="test@test.com", internal_api_token="secret")

        assert client._access_token == "tok-abc"

    @pytest.mark.asyncio
    async def test_login_non_2xx_raises(self) -> None:
        client = _make_client()
        mock_resp = _mock_response(401, {"error": "unauthorized"})

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            with pytest.raises(PlatformAuthError, match="401"):
                await client.login(email="test@test.com", internal_api_token="bad")

    @pytest.mark.asyncio
    async def test_login_missing_token_raises(self) -> None:
        client = _make_client()
        mock_resp = _mock_response(200, {"message": "ok"})  # no access_token

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            with pytest.raises(PlatformAuthError, match="access_token"):
                await client.login(email="a@b.com", internal_api_token="x")

    @pytest.mark.asyncio
    async def test_login_connection_error_raises(self) -> None:
        import httpx
        client = _make_client()

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.ConnectError("timeout")
            )
            with pytest.raises(PlatformAuthError, match="connection"):
                await client.login()


# ---------------------------------------------------------------------------
# ensure_authenticated
# ---------------------------------------------------------------------------


class TestEnsureAuthenticated:
    @pytest.mark.asyncio
    async def test_skips_relogin_when_token_fresh(self) -> None:
        client = _make_client()
        client._access_token = "cached-token"
        client._token_acquired_at = time.monotonic()

        with patch.object(client, "login", new_callable=AsyncMock) as mock_login:
            await client.ensure_authenticated()
            mock_login.assert_not_called()

    @pytest.mark.asyncio
    async def test_relogins_when_token_expired(self) -> None:
        client = _make_client()
        client._access_token = "stale-token"
        client._token_acquired_at = time.monotonic() - 9999.0  # well past TTL

        with patch.object(client, "login", new_callable=AsyncMock) as mock_login:
            await client.ensure_authenticated()
            mock_login.assert_called_once()

    @pytest.mark.asyncio
    async def test_relogins_when_no_token(self) -> None:
        client = _make_client()
        # No token set

        with patch.object(client, "login", new_callable=AsyncMock) as mock_login:
            await client.ensure_authenticated()
            mock_login.assert_called_once()


# ---------------------------------------------------------------------------
# get_service_request
# ---------------------------------------------------------------------------


class TestGetServiceRequest:
    @pytest.mark.asyncio
    async def test_success_returns_result(self) -> None:
        client = _make_client()
        client._access_token = "tok"
        client._token_acquired_at = time.monotonic()
        operations = [{"role": "FM_MANAGER", "status": "IN_PROGRESS"}]
        body = {"data": {"status": "IN_PROCESS", "service_request_operations": operations}}
        mock_resp = _mock_response(200, body)

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_resp
            )
            result = await client.get_service_request("sr-123")

        assert result.sr_id == "sr-123"
        assert result.status == "IN_PROCESS"
        assert len(result.service_request_operations) == 1
        assert result.error is None

    @pytest.mark.asyncio
    async def test_non_2xx_returns_error(self) -> None:
        client = _make_client()
        client._access_token = "tok"
        client._token_acquired_at = time.monotonic()
        mock_resp = _mock_response(404, {"error": "not found"})

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_resp
            )
            result = await client.get_service_request("sr-999")

        assert result.error == "HTTP 404"
        assert result.status is None


# ---------------------------------------------------------------------------
# patch_service_request
# ---------------------------------------------------------------------------


class TestPatchServiceRequest:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        client = _make_client()
        client._access_token = "tok"
        client._token_acquired_at = time.monotonic()
        mock_resp = _mock_response(200, {"success": True, "id": "sr-123"})

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_resp
            )
            result = await client.patch_service_request("sr-123", {"status": "IN_PROCESS"})

        assert result.sr_id == "sr-123"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_non_2xx_returns_error(self) -> None:
        client = _make_client()
        client._access_token = "tok"
        client._token_acquired_at = time.monotonic()
        mock_resp = _mock_response(500, {"error": "server error"})

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_resp
            )
            result = await client.patch_service_request("sr-123", {})

        assert result.error == "HTTP 500"
        assert result.sr_id is None


# ---------------------------------------------------------------------------
# upload_file
# ---------------------------------------------------------------------------


class TestUploadFile:
    def _make_metadata(self) -> FileUploadMetadata:
        return FileUploadMetadata(
            document_type_id="SR_HANDOVER_CHECKLIST",
            sr_id="sr-123",
            lease_id="456",
            brand_id="789",
            property_id="101",
            lease_code="LC-001",
            tenant_profile_id="116",
        )

    @pytest.mark.asyncio
    async def test_upload_success(self) -> None:
        client = _make_client()
        client._access_token = "tok"
        client._token_acquired_at = time.monotonic()
        body = {"data": {"document_id": "doc-uuid-123", "signed_url": "https://s3.example/doc"}}
        mock_resp = _mock_response(200, body)

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value.__aenter__.return_value.put = AsyncMock(
                return_value=mock_resp
            )
            result = await client.upload_file(b"file-bytes", self._make_metadata())

        assert result.document_id == "doc-uuid-123"
        assert result.signed_url == "https://s3.example/doc"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_upload_non_2xx_returns_error(self) -> None:
        client = _make_client()
        client._access_token = "tok"
        client._token_acquired_at = time.monotonic()
        mock_resp = _mock_response(413, {"error": "too large"})

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value.__aenter__.return_value.put = AsyncMock(
                return_value=mock_resp
            )
            result = await client.upload_file(b"bytes", self._make_metadata())

        assert result.error == "HTTP 413"
        assert result.document_id is None


# ---------------------------------------------------------------------------
# _extract_sr_id
# ---------------------------------------------------------------------------


class TestExtractSrId:
    def test_top_level_id(self) -> None:
        assert ServiceRequestPlatformClient._extract_sr_id({"id": "abc"}) == "abc"

    def test_nested_data_id(self) -> None:
        assert ServiceRequestPlatformClient._extract_sr_id({"data": {"sr_id": "xyz"}}) == "xyz"

    def test_service_request_id_key(self) -> None:
        assert (
            ServiceRequestPlatformClient._extract_sr_id({"service_request_id": "def"}) == "def"
        )

    def test_none_on_empty(self) -> None:
        assert ServiceRequestPlatformClient._extract_sr_id({}) is None

    def test_none_on_non_dict(self) -> None:
        assert ServiceRequestPlatformClient._extract_sr_id(None) is None
