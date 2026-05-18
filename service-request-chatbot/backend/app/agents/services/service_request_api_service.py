"""Service Request REST client — adapter, models, mock.

Architecture
------------
- ``ServiceRequestCreationResult`` — canonical result shape for create/submit calls.
- ``ServiceRequestGetResult``      — result shape for GET /service-requests/{sr_id}.
- ``AbstractServiceRequestAPIService`` — adapter interface; swap real ↔ mock.
- ``HttpServiceRequestAPIService`` — production adapter; delegates to
  ``ServiceRequestPlatformClient``.
- ``MockServiceRequestAPIService`` — in-memory POC adapter; zero external deps.
- ``get_service_request_api_service()`` — factory that picks HTTP vs mock.

Security contract
-----------------
- The LLM must never call this service directly.
- Only ``api_submission_node``, ``fm_api_submission_node``, and
  ``rdd_api_submission_node`` are permitted to invoke the write methods.
- Submission is only attempted after confirmation_status == CONFIRMED and all
  blocking validation errors have been cleared.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)

_MAX_RESPONSE_BYTES = 32_768  # cap raw body stored in trace payload


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


@dataclass
class ServiceRequestCreationResult:
    """Output of a create_service_request / submit_report / patch call.

    Attributes
    ----------
    sr_id:
        The service request ID assigned/confirmed by the backend.
        ``None`` on failure.
    endpoint:
        Full URL that was (or would have been) called.
    request_payload:
        The exact payload sent to the API (redact before persisting).
    response_payload:
        Parsed JSON response body, or ``None`` when the call failed before a
        response was received.
    latency_ms:
        Wall-clock time in milliseconds.
    status_code:
        HTTP status code returned by the API.  ``None`` on connection error.
    correlation_id:
        Correlation / request ID extracted from response headers or body.
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


# Re-export ServiceRequestGetResult from the platform client for convenience.
from app.agents.services.platform_api_client import ServiceRequestGetResult  # noqa: E402


# ---------------------------------------------------------------------------
# Abstract adapter
# ---------------------------------------------------------------------------


class AbstractServiceRequestAPIService(ABC):
    """Interface for the Service Request API backend; swap real ↔ mock without
    changing the submission nodes."""

    @abstractmethod
    async def create_service_request(
        self,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        """POST a new Service Request."""

    @abstractmethod
    async def get_service_request(self, sr_id: str) -> ServiceRequestGetResult:
        """GET an existing SR by ID (status sync)."""

    @abstractmethod
    async def patch_service_request(
        self,
        sr_id: str,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        """PATCH an existing SR (FM save progress / approve)."""

    @abstractmethod
    async def submit_report(
        self,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        """POST a report payload (RDD REPORT_SUBMITTED stage).

        Uses the same POST /service-requests endpoint as create but includes
        an existing ``service_request_id`` in the payload and sets
        ``status=REPORT_SUBMITTED``.
        """


# ---------------------------------------------------------------------------
# HTTP adapter (production)
# ---------------------------------------------------------------------------


class HttpServiceRequestAPIService(AbstractServiceRequestAPIService):
    """Production adapter — delegates all platform calls to
    ``ServiceRequestPlatformClient``.
    """

    def __init__(self) -> None:
        from app.agents.services.platform_api_client import get_platform_client
        self._client = get_platform_client()

    async def create_service_request(
        self,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        """POST /service-requests and return a ``ServiceRequestCreationResult``."""
        wall_start = time.monotonic()
        result = await self._client.create_service_request(payload)
        latency_ms = result.latency_ms or int((time.monotonic() - wall_start) * 1000)

        if not result.success or result.error:
            log.warning(
                "sr_api.create.failed",
                status_code=result.status_code,
                error=result.error,
            )
            return ServiceRequestCreationResult(
                sr_id=None,
                endpoint=result.endpoint,
                request_payload=payload,
                response_payload=result.response_payload,
                latency_ms=latency_ms,
                status_code=result.status_code,
                correlation_id=result.correlation_id,
                error=result.error or f"HTTP {result.status_code}",
            )

        sr_id = result.sr_id or self._extract_sr_id(result.response_payload)
        log.info(
            "sr_api.create.success",
            sr_id=sr_id,
            latency_ms=latency_ms,
        )
        return ServiceRequestCreationResult(
            sr_id=sr_id,
            endpoint=result.endpoint,
            request_payload=payload,
            response_payload=result.response_payload,
            latency_ms=latency_ms,
            status_code=result.status_code,
            correlation_id=result.correlation_id,
        )

    async def get_service_request(self, sr_id: str) -> ServiceRequestGetResult:
        """GET /service-requests/{sr_id}."""
        return await self._client.get_service_request(sr_id)

    async def patch_service_request(
        self,
        sr_id: str,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        """PATCH /service-requests/{sr_id}."""
        wall_start = time.monotonic()
        result = await self._client.patch_service_request(sr_id, payload)
        latency_ms = result.latency_ms or int((time.monotonic() - wall_start) * 1000)

        if not result.success:
            log.warning(
                "sr_api.patch.failed",
                sr_id=sr_id,
                status_code=result.status_code,
                error=result.error,
            )
            return ServiceRequestCreationResult(
                sr_id=sr_id,
                endpoint=result.endpoint,
                request_payload=payload,
                response_payload=result.response_payload,
                latency_ms=latency_ms,
                status_code=result.status_code,
                correlation_id=result.correlation_id,
                error=result.error,
            )

        # Use sr_id from result (already extracted by client) or fall back to the
        # known sr_id that was passed in.
        confirmed_sr_id = result.sr_id or sr_id
        log.info("sr_api.patch.success", sr_id=confirmed_sr_id, latency_ms=latency_ms)
        return ServiceRequestCreationResult(
            sr_id=confirmed_sr_id,
            endpoint=result.endpoint,
            request_payload=payload,
            response_payload=result.response_payload,
            latency_ms=latency_ms,
            status_code=result.status_code,
            correlation_id=result.correlation_id,
        )

    async def submit_report(
        self,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        """POST /service-requests with status=REPORT_SUBMITTED."""
        wall_start = time.monotonic()
        result = await self._client.submit_report(payload)
        latency_ms = result.latency_ms or int((time.monotonic() - wall_start) * 1000)

        sr_id = payload.get("service_request_id") or self._extract_sr_id(result.response_payload)

        if not result.success:
            log.warning(
                "sr_api.submit_report.failed",
                sr_id=sr_id,
                status_code=result.status_code,
                error=result.error,
            )
            return ServiceRequestCreationResult(
                sr_id=sr_id,
                endpoint=result.endpoint,
                request_payload=payload,
                response_payload=result.response_payload,
                latency_ms=latency_ms,
                status_code=result.status_code,
                correlation_id=result.correlation_id,
                error=result.error,
            )

        confirmed_sr_id = self._extract_sr_id(result.response_payload) or sr_id
        log.info(
            "sr_api.submit_report.success",
            sr_id=confirmed_sr_id,
            latency_ms=latency_ms,
        )
        return ServiceRequestCreationResult(
            sr_id=confirmed_sr_id,
            endpoint=result.endpoint,
            request_payload=payload,
            response_payload=result.response_payload,
            latency_ms=latency_ms,
            status_code=result.status_code,
            correlation_id=result.correlation_id,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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
# Mock adapter (local POC / testing)
# ---------------------------------------------------------------------------


class MockServiceRequestAPIService(AbstractServiceRequestAPIService):
    """In-memory SR service mock for local POC development and unit tests."""

    _MOCK_ENDPOINT_BASE = "mock://service-request-api/service-requests"

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
        self._patched: list[dict[str, Any]] = []
        self._submitted: list[dict[str, Any]] = []
        # Simulate platform SR state for status sync
        self._sr_states: dict[str, dict[str, Any]] = {}

    @property
    def created_requests(self) -> list[dict[str, Any]]:
        return list(self._created)

    @property
    def patched_requests(self) -> list[dict[str, Any]]:
        return list(self._patched)

    @property
    def submitted_reports(self) -> list[dict[str, Any]]:
        return list(self._submitted)

    async def create_service_request(
        self,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        endpoint = self._MOCK_ENDPOINT_BASE
        if self._force_error:
            sc = self._force_status_code or 500
            return ServiceRequestCreationResult(
                sr_id=None,
                endpoint=endpoint,
                request_payload=payload,
                response_payload=None,
                latency_ms=self._latency_ms,
                status_code=sc,
                error=self._force_error,
            )

        sr_id = str(uuid.uuid4())
        correlation_id = str(uuid.uuid4())
        self._created.append({"sr_id": sr_id, "payload": payload})
        # seed GET state
        self._sr_states[sr_id] = {
            "service_request_id": sr_id,
            "status": "SUBMITTED",
            "service_request_operations": [
                {"assigned_role": "MALL_MANAGER", "workflow_level": 1, "status": "FINISHED"},
                {"assigned_role": "FM_MANAGER", "workflow_level": 2, "status": "IN_PROGRESS"},
                {"assigned_role": "OPERATIONS", "workflow_level": 2, "status": "IN_PROGRESS"},
                {"assigned_role": "DD_ENGINEER", "workflow_level": 3, "status": "YET_TO_START"},
            ],
        }
        return ServiceRequestCreationResult(
            sr_id=sr_id,
            endpoint=endpoint,
            request_payload=payload,
            response_payload={"success": True, "data": {"service_request_id": sr_id}},
            latency_ms=self._latency_ms,
            status_code=self._force_status_code or 201,
            correlation_id=correlation_id,
        )

    async def get_service_request(self, sr_id: str) -> ServiceRequestGetResult:
        from app.agents.services.platform_api_client import ServiceRequestGetResult as _GR
        state = self._sr_states.get(sr_id)
        if not state:
            return _GR(
                success=False,
                sr_id=sr_id,
                status=None,
                service_request_operations=[],
                endpoint=f"{self._MOCK_ENDPOINT_BASE}/{sr_id}",
                status_code=404,
                latency_ms=self._latency_ms,
                error="SR not found in mock",
            )
        return _GR(
            success=True,
            sr_id=sr_id,
            status=state.get("status"),
            service_request_operations=state.get("service_request_operations", []),
            payload=state.get("payload"),
            endpoint=f"{self._MOCK_ENDPOINT_BASE}/{sr_id}",
            status_code=200,
            latency_ms=self._latency_ms,
        )

    async def patch_service_request(
        self,
        sr_id: str,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        endpoint = f"{self._MOCK_ENDPOINT_BASE}/{sr_id}"
        if self._force_error:
            sc = self._force_status_code or 500
            return ServiceRequestCreationResult(
                sr_id=sr_id,
                endpoint=endpoint,
                request_payload=payload,
                response_payload=None,
                latency_ms=self._latency_ms,
                status_code=sc,
                error=self._force_error,
            )
        self._patched.append({"sr_id": sr_id, "payload": payload})
        status = payload.get("status", "IN_PROCESS")
        # Advance mock state
        if sr_id in self._sr_states:
            self._sr_states[sr_id]["status"] = status
            if status == "APPROVED":
                ops = self._sr_states[sr_id].get("service_request_operations", [])
                for op in ops:
                    if op["assigned_role"] in ("FM_MANAGER", "OPERATIONS"):
                        op["status"] = "FINISHED"
                    if op["assigned_role"] == "DD_ENGINEER":
                        op["status"] = "IN_PROGRESS"
        return ServiceRequestCreationResult(
            sr_id=sr_id,
            endpoint=endpoint,
            request_payload=payload,
            response_payload={"success": True, "data": "Successfully processed"},
            latency_ms=self._latency_ms,
            status_code=200,
        )

    async def submit_report(
        self,
        payload: dict[str, Any],
    ) -> ServiceRequestCreationResult:
        endpoint = self._MOCK_ENDPOINT_BASE
        sr_id = payload.get("service_request_id") or str(uuid.uuid4())
        if self._force_error:
            sc = self._force_status_code or 500
            return ServiceRequestCreationResult(
                sr_id=sr_id,
                endpoint=endpoint,
                request_payload=payload,
                response_payload=None,
                latency_ms=self._latency_ms,
                status_code=sc,
                error=self._force_error,
            )
        self._submitted.append({"sr_id": sr_id, "payload": payload})
        if sr_id in self._sr_states:
            self._sr_states[sr_id]["status"] = "REPORT_SUBMITTED"
        return ServiceRequestCreationResult(
            sr_id=sr_id,
            endpoint=endpoint,
            request_payload=payload,
            response_payload={"success": True, "data": {"service_request_id": sr_id}},
            latency_ms=self._latency_ms,
            status_code=self._force_status_code or 201,
        )


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def get_service_request_api_service() -> AbstractServiceRequestAPIService:
    """Return the appropriate adapter based on whether a real API URL is configured."""
    if settings.service_request_api_base_url:
        return HttpServiceRequestAPIService()
    return MockServiceRequestAPIService()
