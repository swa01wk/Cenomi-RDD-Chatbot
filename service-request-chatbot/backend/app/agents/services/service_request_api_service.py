"""Service Request REST client — adapter, models, mock.

Architecture
------------
- ``ServiceRequestCreationResult`` — canonical result shape for a create call.
- ``AbstractServiceRequestAPIService`` — adapter interface; swap real ↔ mock
  without touching the node.
- ``HttpServiceRequestAPIService`` — production adapter; POST /service-requests
  against ``SERVICE_REQUEST_API_BASE_URL``.
- ``MockServiceRequestAPIService`` — in-memory POC adapter; zero external
  dependencies.
- ``get_service_request_api_service()`` — factory that picks HTTP vs mock.

POC scope
---------
For this POC, only ``create_service_request`` is fully implemented.
``patch_service_request`` and ``submit_report`` are declared on the abstract base
but raise ``NotImplementedError`` in both adapters — they are reserved for the
FM_REVIEW and RDD_REVIEW workflow stages respectively.

Security contract
-----------------
- The LLM must never call this service directly.
- Only ``api_submission_node`` is permitted to invoke ``create_service_request``.
- Submission is only attempted after confirmation_status == CONFIRMED and all
  blocking validation errors have been cleared.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)

_MAX_RESPONSE_BYTES = 32_768  # cap raw body stored in trace payload

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class ServiceRequestCreationResult:
    """Output of a single ``create_service_request`` call.

    Attributes
    ----------
    sr_id:
        The service request ID assigned by the backend.  ``None`` on failure.
    endpoint:
        Full URL that was (or would have been) called.
    request_payload:
        The exact payload sent to the API (used for tracing; callers should
        redact sensitive values before persisting).
    response_payload:
        Parsed JSON response body, or ``None`` when the call failed before a
        response was received.
    latency_ms:
        Wall-clock time from request dispatch to response receipt in
        milliseconds.
    status_code:
        HTTP status code returned by the API.  ``None`` on connection error.
    correlation_id:
        Correlation / request ID extracted from response headers or body.
        ``None`` when not provided by the API.
    error:
        Human-readable error string.  ``None`` on success.
    """

    sr_id: str | None
    endpoint: str
    request_payload: dict[str, Any]
    response_payload: dict[str, Any] | None
    latency_ms: int
    status_code: int | None
    correlation_id: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Abstract adapter
# ---------------------------------------------------------------------------


class AbstractServiceRequestAPIService(ABC):
    """Interface for the Service Request API backend; swap real ↔ mock without
    changing ``api_submission_node``."""

    @abstractmethod
    async def create_service_request(
        self,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        """POST a new Service Request; always returns a ``ServiceRequestCreationResult``."""

    @abstractmethod
    async def patch_service_request(
        self,
        sr_id: str,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        """PATCH an existing SR (reserved for FM_REVIEW / RDD_REVIEW stages)."""

    @abstractmethod
    async def submit_report(
        self,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        """POST a report payload (reserved for RDD_REVIEW stage)."""


# ---------------------------------------------------------------------------
# HTTP adapter (production)
# ---------------------------------------------------------------------------


class HttpServiceRequestAPIService(AbstractServiceRequestAPIService):
    """Production adapter — issues a ``POST /service-requests`` against the SR API.

    Parameters
    ----------
    base_url:
        Base URL of the Service Request API.  Defaults to
        ``settings.service_request_api_base_url``.
    timeout:
        ``httpx`` request timeout in seconds.
    """

    _CREATE_PATH = "/service-requests"

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = (base_url or settings.service_request_api_base_url or "").rstrip("/")
        self._timeout = timeout

    async def create_service_request(
        self,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        """POST /service-requests and return a ``ServiceRequestCreationResult``."""
        endpoint = f"{self._base_url}{self._CREATE_PATH}"
        wall_start = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(endpoint, json=payload)
            latency_ms = int((time.monotonic() - wall_start) * 1000)

            # Prefer X-Correlation-ID header; fall back to X-Request-ID.
            correlation_id: str | None = (
                response.headers.get("x-correlation-id")
                or response.headers.get("x-request-id")
            ) or None

            raw_text = response.text[:_MAX_RESPONSE_BYTES]
            try:
                body: dict[str, Any] | None = response.json()
            except Exception:
                body = {"_raw": raw_text}

            # Also look for correlation_id in response body when absent from headers.
            if not correlation_id and isinstance(body, dict):
                body_cid = body.get("correlation_id") or body.get("request_id")
                correlation_id = str(body_cid) if body_cid else None

            if response.status_code not in (200, 201):
                log.warning(
                    "service_request_api.create.non_2xx",
                    status_code=response.status_code,
                    endpoint=endpoint,
                    correlation_id=correlation_id,
                )
                return ServiceRequestCreationResult(
                    sr_id=None,
                    endpoint=endpoint,
                    request_payload=payload,
                    response_payload=body,
                    latency_ms=latency_ms,
                    status_code=response.status_code,
                    correlation_id=correlation_id,
                    error=f"HTTP {response.status_code}",
                )

            sr_id = self._extract_sr_id(body)
            log.info(
                "service_request_api.create.success",
                sr_id=sr_id,
                latency_ms=latency_ms,
                correlation_id=correlation_id,
            )
            return ServiceRequestCreationResult(
                sr_id=sr_id,
                endpoint=endpoint,
                request_payload=payload,
                response_payload=body,
                latency_ms=latency_ms,
                status_code=response.status_code,
                correlation_id=correlation_id,
            )

        except httpx.RequestError as exc:
            latency_ms = int((time.monotonic() - wall_start) * 1000)
            error_msg = f"{type(exc).__name__}: {exc}"
            log.warning("service_request_api.create.connection_error", error=error_msg)
            return ServiceRequestCreationResult(
                sr_id=None,
                endpoint=endpoint,
                request_payload=payload,
                response_payload=None,
                latency_ms=latency_ms,
                status_code=None,
                error=error_msg,
            )

    async def patch_service_request(
        self,
        sr_id: str,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        """Reserved for FM_REVIEW / RDD_REVIEW — not implemented for CREATE_SR POC."""
        raise NotImplementedError(
            "patch_service_request is reserved for FM_REVIEW / RDD_REVIEW stages "
            "and is not implemented in this POC."
        )

    async def submit_report(
        self,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        """Reserved for RDD_REVIEW — not implemented for CREATE_SR POC."""
        raise NotImplementedError(
            "submit_report is reserved for RDD_REVIEW stage "
            "and is not implemented in this POC."
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_sr_id(body: dict[str, Any] | None) -> str | None:
        """Extract the service request ID from various response envelope shapes.

        Tries common keys in order: ``id``, ``sr_id``, ``service_request_id``.
        Also inspects a nested ``data`` envelope if top-level keys are absent.
        """
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
# Mock adapter (local POC / testing)
# ---------------------------------------------------------------------------


class MockServiceRequestAPIService(AbstractServiceRequestAPIService):
    """In-memory SR service mock for local POC development and unit tests.

    Parameters
    ----------
    simulated_latency_ms:
        Latency value reported in the result (no real sleep).
    force_error:
        When set, the mock returns this error string instead of a success result.
    force_status_code:
        Override the HTTP status code returned on error (default ``500``).
        On success the mock always returns ``201``.
    """

    _MOCK_ENDPOINT = "mock://service-request-api/service-requests"

    def __init__(
        self,
        simulated_latency_ms: int = 15,
        force_error: str | None = None,
        force_status_code: int | None = None,
    ) -> None:
        self._latency_ms = simulated_latency_ms
        self._force_error = force_error
        self._force_status_code = force_status_code
        self._created: list[dict[str, Any]] = []

    @property
    def created_requests(self) -> list[dict[str, Any]]:
        """All payloads submitted via ``create_service_request`` (for test assertions)."""
        return list(self._created)

    async def create_service_request(
        self,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        if self._force_error:
            status_code = self._force_status_code if self._force_status_code is not None else 500
            log.debug(
                "service_request_api.mock.create.forced_error",
                error=self._force_error,
                status_code=status_code,
            )
            return ServiceRequestCreationResult(
                sr_id=None,
                endpoint=self._MOCK_ENDPOINT,
                request_payload=payload,
                response_payload=None,
                latency_ms=self._latency_ms,
                status_code=status_code,
                error=self._force_error,
            )

        sr_id = str(uuid.uuid4())
        correlation_id = str(uuid.uuid4())
        self._created.append({"sr_id": sr_id, "payload": payload})

        response_payload: dict[str, Any] = {
            "id": sr_id,
            "status": "SUBMITTED",
            "correlation_id": correlation_id,
        }

        log.debug(
            "service_request_api.mock.create.success",
            sr_id=sr_id,
            correlation_id=correlation_id,
        )
        return ServiceRequestCreationResult(
            sr_id=sr_id,
            endpoint=self._MOCK_ENDPOINT,
            request_payload=payload,
            response_payload=response_payload,
            latency_ms=self._latency_ms,
            status_code=self._force_status_code if self._force_status_code is not None else 201,
            correlation_id=correlation_id,
        )

    async def patch_service_request(
        self,
        sr_id: str,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        raise NotImplementedError(
            "patch_service_request not implemented in MockServiceRequestAPIService."
        )

    async def submit_report(
        self,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        raise NotImplementedError(
            "submit_report not implemented in MockServiceRequestAPIService."
        )


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def get_service_request_api_service() -> AbstractServiceRequestAPIService:
    """Return the appropriate adapter based on whether a real API URL is configured."""
    if settings.service_request_api_base_url:
        return HttpServiceRequestAPIService()
    return MockServiceRequestAPIService()
