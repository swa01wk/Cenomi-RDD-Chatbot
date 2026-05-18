"""Unified Cenomi Service Request Platform HTTP client.

This module provides ``ServiceRequestPlatformClient``, the single gateway for
all outbound calls to the Cenomi platform API.  Graph nodes must **never**
issue raw ``httpx`` requests directly — they call this client instead.

Endpoint map (from Postman collection)
---------------------------------------
POST  {auth_base_url}/cenomi-ai/login            → login
GET   {base_url}/service-requests/workflows       → get_workflows
POST  {base_url}/service-requests                 → create_service_request / submit_report
GET   {base_url}/service-requests/{sr_id}         → get_service_request
PATCH {base_url}/service-requests/{sr_id}         → patch_service_request
PUT   {base_url}/files?...                        → upload_file

Auth model
----------
Service-to-service Bearer token obtained via ``login``.  The token is cached
in memory using ``_token_acquired_at`` (monotonic clock) and refreshed when
the age exceeds TOKEN_TTL_S.

Security contract
-----------------
- This client is the only place that performs raw HTTP I/O to the platform.
- All payloads must be constructed by payload-builder services, not by LLM.
- Sensitive fields (access_token, document_id, signed_url) are redacted
  before being stored in traces.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from app.agents.exceptions import PlatformAuthError
from app.core.config import settings

log = structlog.get_logger(__name__)
logger = logging.getLogger(__name__)

_MAX_RESPONSE_BYTES = 32_768  # cap raw body stored in trace payload

# Token time-to-live: refresh after this many seconds regardless of JWT exp.
# Intentionally conservative so a slow graph turn never races token expiry.
TOKEN_TTL_S: float = 3600.0  # 1 hour
TOKEN_REFRESH_BEFORE_EXPIRY_S = 120  # kept for backward-compat imports


# ---------------------------------------------------------------------------
# Typed result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PlatformCallResult:
    """Generic result returned by every platform call.

    All positional arguments have defaults so that the class can also be used
    as the ``ServiceRequestResult`` alias (where callers omit ``success``).
    """

    success: bool = True
    endpoint: str = ""
    status_code: int | None = None
    latency_ms: int = 0
    sr_id: str | None = None
    request_payload: dict[str, Any] | None = None
    response_payload: dict[str, Any] | None = None
    correlation_id: str | None = None
    error: str | None = None


# Backward-compatible alias: ServiceRequestResult maps to PlatformCallResult.
# Tests and callers that construct ServiceRequestResult without the `success`
# field use this alias; they must provide success=True/False explicitly.
ServiceRequestResult = PlatformCallResult


@dataclass
class FileUploadMetadata:
    """Query parameters required by PUT /files."""

    document_type_id: str
    sr_id: str
    lease_id: str
    brand_id: str
    property_id: str
    lease_code: str
    tenant_profile_id: str
    file_name: str = ""
    document_type_status: str = ""
    file_extension: str = "pdf"


@dataclass
class FileUploadResult:
    """Result of a PUT /files call."""

    success: bool
    document_id: str | None
    file_path: str | None
    signed_url: str | None
    document_type_id: str | None
    endpoint: str
    status_code: int | None
    latency_ms: int
    error: str | None = None


@dataclass
class ServiceRequestGetResult:
    """Result of GET /service-requests/{sr_id}."""

    success: bool
    sr_id: str | None
    status: str | None
    service_request_operations: list[dict[str, Any]] = field(default_factory=list)
    payload: dict[str, Any] | None = None
    endpoint: str = ""
    status_code: int | None = None
    latency_ms: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class ServiceRequestPlatformClient:
    """Authenticated HTTP client for all Cenomi platform API calls.

    Parameters
    ----------
    base_url:
        Base URL for service-requests and file endpoints.  Reads from
        ``settings.service_request_api_base_url`` by default.
    auth_base_url:
        Base URL for the auth (login) endpoint.  Defaults to ``base_url``
        when not provided.
    timeout:
        ``httpx`` request timeout in seconds.

    Usage
    -----
    The factory ``get_platform_client()`` returns a module-level singleton.
    Call ``await client.ensure_authenticated()`` before any platform call —
    or let each method do it automatically (preferred).
    """

    _LOGIN_PATH = "/cenomi-ai/login"
    _WORKFLOWS_PATH = "/service-requests/workflows"
    _SERVICE_REQUESTS_PATH = "/service-requests"
    _FILES_PATH = "/files"

    def __init__(
        self,
        base_url: str | None = None,
        auth_base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = (base_url or settings.service_request_api_base_url or "").rstrip("/")
        self._auth_base_url = (
            auth_base_url or settings.platform_auth_base_url or self._base_url
        ).rstrip("/")
        self._timeout = timeout

        # Token state — populated by login()
        self._access_token: str | None = None
        # Monotonic timestamp of when the token was acquired (0 = never acquired).
        self._token_acquired_at: float = 0.0

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def login(
        self,
        email: str | None = None,
        internal_api_token: str | None = None,
    ) -> None:
        """POST {auth_base_url}/cenomi-ai/login and cache the access token.

        Parameters default to ``settings.platform_login_email`` and
        ``settings.platform_internal_api_token`` when not provided.

        Raises
        ------
        PlatformAuthError
            On non-2xx response, missing token in response, or connection error.
        """
        _email = email or settings.platform_login_email or ""
        _token = internal_api_token or settings.platform_internal_api_token or ""
        endpoint = f"{self._auth_base_url}{self._LOGIN_PATH}"
        wall_start = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    endpoint,
                    json={"email": _email},
                    headers={"Content-Type": "application/json", "x-internal-api-token": _token},
                )
            latency_ms = int((time.monotonic() - wall_start) * 1000)

            if response.status_code not in (200, 201):
                log.warning(
                    "platform_client.login.non_2xx",
                    status_code=response.status_code,
                    endpoint=endpoint,
                )
                raise PlatformAuthError(
                    f"Platform login failed: HTTP {response.status_code}"
                )

            body = self._parse_body(response)
            # Try both flat and nested envelope shapes
            access_token: str | None = None
            if isinstance(body, dict):
                # Flat: {"access_token": "..."}
                access_token = body.get("access_token")
                if access_token is None:
                    # Nested: {"data": {"access_token": "..."}}
                    data = body.get("data")
                    if isinstance(data, dict):
                        access_token = data.get("access_token")

            if not access_token:
                raise PlatformAuthError(
                    "Platform login succeeded but access_token was absent in response"
                )

            self._access_token = access_token
            self._token_acquired_at = time.monotonic()
            log.info("platform_client.login.success", latency_ms=latency_ms)

        except httpx.RequestError as exc:
            err = f"connection error: {type(exc).__name__}: {exc}"
            log.warning("platform_client.login.connection_error", error=err)
            raise PlatformAuthError(f"Platform login connection error: {exc}") from exc

    async def ensure_authenticated(self) -> bool:
        """Ensure a valid token is available; attempt login if needed.

        Returns True on success, False if login raises.
        """
        now = time.monotonic()
        if self._access_token and (now - self._token_acquired_at) < TOKEN_TTL_S:
            return True  # token still within TTL
        log.info("platform_client.ensure_authenticated.refreshing_token")
        try:
            await self.login()
            return True
        except PlatformAuthError as exc:
            log.warning("platform_client.ensure_authenticated.login_failed", error=str(exc))
            return False

    # ------------------------------------------------------------------
    # Workflows
    # ------------------------------------------------------------------

    async def get_workflows(
        self, service_category: str, sub_category: str
    ) -> PlatformCallResult:
        """GET /service-requests/workflows for the form skeleton."""
        await self.ensure_authenticated()
        endpoint = f"{self._base_url}{self._WORKFLOWS_PATH}"
        params = {
            "service_category": service_category,
            "sub_category": sub_category,
            "sort_by": "updated_at",
            "order": "ASC",
        }
        return await self._get(endpoint, params=params)

    # ------------------------------------------------------------------
    # Service requests
    # ------------------------------------------------------------------

    async def create_service_request(self, payload: dict[str, Any]) -> PlatformCallResult:
        """POST /service-requests — create a new SR."""
        await self.ensure_authenticated()
        endpoint = f"{self._base_url}{self._SERVICE_REQUESTS_PATH}"
        result = await self._post(endpoint, payload)
        if result.sr_id is None:
            result.sr_id = self._extract_sr_id(result.response_payload)
        return result

    async def get_service_request(self, sr_id: str) -> ServiceRequestGetResult:
        """GET /service-requests/{sr_id} — refresh status and operations."""
        await self.ensure_authenticated()
        endpoint = f"{self._base_url}{self._SERVICE_REQUESTS_PATH}/{sr_id}"
        wall_start = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    endpoint,
                    headers=self._auth_headers(),
                )
            latency_ms = int((time.monotonic() - wall_start) * 1000)
            body = self._parse_body(response)

            if response.status_code != 200:
                return ServiceRequestGetResult(
                    success=False,
                    sr_id=None,
                    status=None,
                    endpoint=endpoint,
                    status_code=response.status_code,
                    latency_ms=latency_ms,
                    error=f"HTTP {response.status_code}",
                )

            data: dict[str, Any] = {}
            if isinstance(body, dict):
                data = body.get("data") or {}

            return ServiceRequestGetResult(
                success=True,
                sr_id=str(data.get("service_request_id") or sr_id),
                status=data.get("status") or data.get("sr_status"),
                service_request_operations=data.get("service_request_operations") or [],
                payload=data.get("payload"),
                endpoint=endpoint,
                status_code=response.status_code,
                latency_ms=latency_ms,
            )

        except httpx.RequestError as exc:
            latency_ms = int((time.monotonic() - wall_start) * 1000)
            err = f"{type(exc).__name__}: {exc}"
            log.warning("platform_client.get_sr.connection_error", sr_id=sr_id, error=err)
            return ServiceRequestGetResult(
                success=False,
                sr_id=None,
                status=None,
                endpoint=endpoint,
                status_code=None,
                latency_ms=latency_ms,
                error=err,
            )

    async def patch_service_request(
        self, sr_id: str, payload: dict[str, Any]
    ) -> PlatformCallResult:
        """PATCH /service-requests/{sr_id} — update SR (FM save/approve)."""
        await self.ensure_authenticated()
        endpoint = f"{self._base_url}{self._SERVICE_REQUESTS_PATH}/{sr_id}"
        result = await self._patch(endpoint, payload)
        if result.success and result.sr_id is None:
            result.sr_id = self._extract_sr_id(result.response_payload) or sr_id
        return result

    async def submit_report(self, payload: dict[str, Any]) -> PlatformCallResult:
        """POST /service-requests with status=REPORT_SUBMITTED (RDD stage)."""
        await self.ensure_authenticated()
        endpoint = f"{self._base_url}{self._SERVICE_REQUESTS_PATH}"
        result = await self._post(endpoint, payload)
        if result.sr_id is None:
            result.sr_id = self._extract_sr_id(result.response_payload)
        return result

    # ------------------------------------------------------------------
    # File upload
    # ------------------------------------------------------------------

    async def upload_file(
        self, file_bytes: bytes, metadata: FileUploadMetadata
    ) -> FileUploadResult:
        """PUT /files — upload a document to the platform.

        The platform expects raw binary bytes in the body with no Content-Type
        header override (the Postman collection uses 'binary' body mode).
        """
        await self.ensure_authenticated()
        endpoint = f"{self._base_url}{self._FILES_PATH}"
        params: dict[str, str] = {
            "query": "SERVICE_REQUEST",
            "file_extension": metadata.file_extension,
            "document_type_id": metadata.document_type_id,
            "lease_id": str(metadata.lease_id),
            "brand_id": str(metadata.brand_id),
            "property_id": str(metadata.property_id),
            "lease_code": metadata.lease_code,
            "sr_id": str(metadata.sr_id),
            "tenant_profile_id": str(metadata.tenant_profile_id),
            "document_type_status": metadata.document_type_status,
            "signed_url": "true",
        }
        if metadata.file_name:
            params["file_name"] = metadata.file_name

        wall_start = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.put(
                    endpoint,
                    content=file_bytes,
                    params=params,
                    headers=self._auth_headers(),
                )
            latency_ms = int((time.monotonic() - wall_start) * 1000)
            body = self._parse_body(response)

            if response.status_code not in (200, 201):
                log.warning(
                    "platform_client.upload_file.non_2xx",
                    status_code=response.status_code,
                    document_type_id=metadata.document_type_id,
                )
                return FileUploadResult(
                    success=False,
                    document_id=None,
                    file_path=None,
                    signed_url=None,
                    document_type_id=None,
                    endpoint=endpoint,
                    status_code=response.status_code,
                    latency_ms=latency_ms,
                    error=f"HTTP {response.status_code}",
                )

            data: dict[str, Any] = {}
            if isinstance(body, dict):
                data = body.get("data") or {}

            doc_id = data.get("document_id")
            log.info(
                "platform_client.upload_file.success",
                document_type_id=metadata.document_type_id,
                document_id=doc_id,
                latency_ms=latency_ms,
            )
            return FileUploadResult(
                success=True,
                document_id=doc_id,
                file_path=data.get("file_path"),
                signed_url=data.get("signed_url"),
                document_type_id=data.get("document_type_id") or metadata.document_type_id,
                endpoint=endpoint,
                status_code=response.status_code,
                latency_ms=latency_ms,
            )

        except httpx.RequestError as exc:
            latency_ms = int((time.monotonic() - wall_start) * 1000)
            err = f"{type(exc).__name__}: {exc}"
            log.warning("platform_client.upload_file.connection_error", error=err)
            return FileUploadResult(
                success=False,
                document_id=None,
                file_path=None,
                signed_url=None,
                document_type_id=None,
                endpoint=endpoint,
                status_code=None,
                latency_ms=latency_ms,
                error=err,
            )

    # ------------------------------------------------------------------
    # Private HTTP helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    async def _get(
        self, endpoint: str, params: dict[str, str] | None = None
    ) -> PlatformCallResult:
        wall_start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    endpoint, params=params, headers=self._auth_headers()
                )
            latency_ms = int((time.monotonic() - wall_start) * 1000)
            body = self._parse_body(response)
            correlation_id = self._extract_correlation(response, body)
            success = response.status_code in (200, 201)
            if not success:
                log.warning(
                    "platform_client.get.non_2xx",
                    status_code=response.status_code,
                    endpoint=endpoint,
                )
            sr_id = self._extract_sr_id(body) if success else None
            return PlatformCallResult(
                success=success,
                endpoint=endpoint,
                status_code=response.status_code,
                latency_ms=latency_ms,
                sr_id=sr_id,
                response_payload=body,
                correlation_id=correlation_id,
                error=None if success else f"HTTP {response.status_code}",
            )
        except httpx.RequestError as exc:
            latency_ms = int((time.monotonic() - wall_start) * 1000)
            err = f"{type(exc).__name__}: {exc}"
            return PlatformCallResult(
                success=False, endpoint=endpoint, status_code=None,
                latency_ms=latency_ms, error=err,
            )

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> PlatformCallResult:
        wall_start = time.monotonic()
        try:
            headers = {**self._auth_headers(), "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
            latency_ms = int((time.monotonic() - wall_start) * 1000)
            body = self._parse_body(response)
            correlation_id = self._extract_correlation(response, body)
            success = response.status_code in (200, 201)
            if not success:
                log.warning(
                    "platform_client.post.non_2xx",
                    status_code=response.status_code,
                    endpoint=endpoint,
                )
            sr_id = self._extract_sr_id(body) if success else None
            return PlatformCallResult(
                success=success,
                endpoint=endpoint,
                status_code=response.status_code,
                latency_ms=latency_ms,
                sr_id=sr_id,
                response_payload=body,
                correlation_id=correlation_id,
                error=None if success else f"HTTP {response.status_code}",
            )
        except httpx.RequestError as exc:
            latency_ms = int((time.monotonic() - wall_start) * 1000)
            err = f"{type(exc).__name__}: {exc}"
            return PlatformCallResult(
                success=False, endpoint=endpoint, status_code=None,
                latency_ms=latency_ms, error=err,
            )

    async def _patch(self, endpoint: str, payload: dict[str, Any]) -> PlatformCallResult:
        wall_start = time.monotonic()
        try:
            headers = {**self._auth_headers(), "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.patch(endpoint, json=payload, headers=headers)
            latency_ms = int((time.monotonic() - wall_start) * 1000)
            body = self._parse_body(response)
            correlation_id = self._extract_correlation(response, body)
            success = response.status_code in (200, 201)
            if not success:
                log.warning(
                    "platform_client.patch.non_2xx",
                    status_code=response.status_code,
                    endpoint=endpoint,
                )
            sr_id = self._extract_sr_id(body) if success else None
            return PlatformCallResult(
                success=success,
                endpoint=endpoint,
                status_code=response.status_code,
                latency_ms=latency_ms,
                sr_id=sr_id,
                response_payload=body,
                correlation_id=correlation_id,
                error=None if success else f"HTTP {response.status_code}",
            )
        except httpx.RequestError as exc:
            latency_ms = int((time.monotonic() - wall_start) * 1000)
            err = f"{type(exc).__name__}: {exc}"
            return PlatformCallResult(
                success=False, endpoint=endpoint, status_code=None,
                latency_ms=latency_ms, error=err,
            )

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_body(response: httpx.Response) -> dict[str, Any] | None:
        try:
            return response.json()
        except Exception:
            raw = response.text[:_MAX_RESPONSE_BYTES]
            return {"_raw": raw} if raw else None

    @staticmethod
    def _extract_correlation(
        response: httpx.Response, body: dict[str, Any] | None
    ) -> str | None:
        cid = (
            response.headers.get("x-correlation-id")
            or response.headers.get("x-request-id")
        )
        if not cid and isinstance(body, dict):
            raw = body.get("correlation_id") or body.get("request_id")
            cid = str(raw) if raw else None
        return cid

    @staticmethod
    def _extract_sr_id(body: dict[str, Any] | None) -> str | None:
        """Extract the service request ID from various response envelope shapes."""
        if not isinstance(body, dict):
            return None
        for key in ("id", "sr_id", "service_request_id"):
            val = body.get(key)
            if val is not None:
                return str(val)
        nested = body.get("data")
        if isinstance(nested, dict):
            for key in ("id", "sr_id", "service_request_id"):
                val = nested.get(key)
                if val is not None:
                    return str(val)
        return None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_platform_client: ServiceRequestPlatformClient | None = None


def get_platform_client() -> ServiceRequestPlatformClient:
    """Return the module-level singleton ``ServiceRequestPlatformClient``.

    The singleton is created lazily on first call.  Settings are read from
    the ``Settings`` object (i.e. from environment variables).
    """
    global _platform_client
    if _platform_client is None:
        _platform_client = ServiceRequestPlatformClient()
    return _platform_client
