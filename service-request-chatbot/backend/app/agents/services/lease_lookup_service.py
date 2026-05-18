"""Lease / Tenant API integration — adapter, models, and mock implementation.

Architecture
------------
- ``LeaseRecord``            — canonical result shape (matches the upstream API).
- ``LeaseLookupQuery``       — search parameters accepted by both adapters.
- ``LeaseLookupResult``      — wraps matches plus tracing metadata (latency, status
                               code, raw payloads, error).
- ``AbstractLeaseLookupService`` — adapter interface; swap without touching the node.
- ``HttpLeaseLookupService`` — production adapter; hits ``LEASE_TENANT_API_BASE_URL``.
- ``MockLeaseLookupService`` — in-memory POC adapter; zero external dependencies.

Search priority (``HttpLeaseLookupService`` and ``MockLeaseLookupService``)
---------------------------------------------------------------------------
1. ``lease_code``  (exact)
2. ``brand`` + ``mall``  (both present)
3. ``brand`` only
4. ``mall`` only
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog
from pydantic import BaseModel

from app.core.config import settings

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class LeaseRecord(BaseModel):
    """Canonical lease result shape returned by the Lease/Tenant API."""

    lease_code: str
    lease_id: int
    contract_id: int
    brand: str
    brand_id: int
    mall: str
    property_id: int
    tenant_profile_id: int
    unit_codes: list[str]
    contracted_area: float
    city: str
    lease_brand_mall: str


class LeaseLookupQuery(BaseModel):
    """Search parameters for a lease lookup — at least one field must be set."""

    lease_code: str | None = None
    brand: str | None = None
    mall: str | None = None

    def has_identifiers(self) -> bool:
        """Return True when at least one search field is non-empty."""
        return bool(self.lease_code or self.brand or self.mall)


@dataclass
class LeaseLookupResult:
    """Output of a single lease lookup call — matches plus full trace metadata."""

    matches: list[LeaseRecord]
    endpoint: str
    request_payload: dict[str, Any]
    response_payload: dict[str, Any] | None
    latency_ms: int
    status_code: int | None
    error: str | None = None


# ---------------------------------------------------------------------------
# Abstract adapter
# ---------------------------------------------------------------------------


class AbstractLeaseLookupService(ABC):
    """Interface for lease lookup backends; swap real ↔ mock without node changes."""

    @abstractmethod
    async def lookup(self, query: LeaseLookupQuery) -> LeaseLookupResult:
        """Resolve leases matching *query*; always returns a ``LeaseLookupResult``."""


# ---------------------------------------------------------------------------
# HTTP adapter (production)
# ---------------------------------------------------------------------------

_MAX_RESPONSE_BYTES = 32_768  # cap raw body stored in trace payload


class HttpLeaseLookupService(AbstractLeaseLookupService):
    """Production adapter — issues a single ``GET /leases`` against the tenant API.

    Parameters
    ----------
    base_url:
        Base URL of the Lease/Tenant API.  Defaults to
        ``settings.lease_tenant_api_base_url``.
    timeout:
        ``httpx`` request timeout in seconds.
    """

    _ENDPOINT_PATH = "/leases"

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = (base_url or settings.lease_tenant_api_base_url or "").rstrip("/")
        self._timeout = timeout

    async def lookup(self, query: LeaseLookupQuery) -> LeaseLookupResult:
        params = self._build_params(query)
        endpoint = f"{self._base_url}{self._ENDPOINT_PATH}"
        request_payload: dict[str, Any] = {"endpoint": endpoint, "params": params}

        wall_start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(endpoint, params=params)
            latency_ms = int((time.monotonic() - wall_start) * 1000)

            raw_text = response.text[:_MAX_RESPONSE_BYTES]
            try:
                body: dict[str, Any] | None = response.json()
            except Exception:
                body = {"_raw": raw_text}

            if response.status_code != 200:
                log.warning(
                    "lease_lookup.http.non_200",
                    status_code=response.status_code,
                    endpoint=endpoint,
                )
                return LeaseLookupResult(
                    matches=[],
                    endpoint=endpoint,
                    request_payload=request_payload,
                    response_payload=body,
                    latency_ms=latency_ms,
                    status_code=response.status_code,
                    error=f"HTTP {response.status_code}",
                )

            matches = self._parse_matches(body)
            log.info(
                "lease_lookup.http.success",
                match_count=len(matches),
                latency_ms=latency_ms,
            )
            return LeaseLookupResult(
                matches=matches,
                endpoint=endpoint,
                request_payload=request_payload,
                response_payload=body,
                latency_ms=latency_ms,
                status_code=response.status_code,
            )

        except httpx.RequestError as exc:
            latency_ms = int((time.monotonic() - wall_start) * 1000)
            error_msg = f"{type(exc).__name__}: {exc}"
            log.warning("lease_lookup.http.connection_error", error=error_msg)
            return LeaseLookupResult(
                matches=[],
                endpoint=endpoint,
                request_payload=request_payload,
                response_payload=None,
                latency_ms=latency_ms,
                status_code=None,
                error=error_msg,
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_params(query: LeaseLookupQuery) -> dict[str, str]:
        params: dict[str, str] = {}
        if query.lease_code:
            params["lease_code"] = query.lease_code
        if query.brand:
            params["brand"] = query.brand
        if query.mall:
            params["mall"] = query.mall
        return params

    @staticmethod
    def _parse_matches(body: dict[str, Any] | None) -> list[LeaseRecord]:
        """Parse the API response body into a list of ``LeaseRecord``."""
        if not body:
            return []
        items: list[Any] = []
        if isinstance(body, list):
            items = body
        elif isinstance(body, dict):
            # Support both {"leases": [...]} and {"data": [...]} envelopes.
            items = body.get("leases") or body.get("data") or []
        records: list[LeaseRecord] = []
        for item in items:
            try:
                records.append(LeaseRecord.model_validate(item))
            except Exception as exc:
                log.warning("lease_lookup.parse_record.failed", error=str(exc), item=item)
        return records


# ---------------------------------------------------------------------------
# Mock adapter (local POC / testing)
# ---------------------------------------------------------------------------

_MOCK_LEASES: list[dict[str, Any]] = [
    {
        "lease_code": "t0105712",
        "lease_id": 95404,
        "contract_id": 95404,
        "brand": "Brand Under Armour",
        "brand_id": 267,
        "mall": "Jawharat Jeddah",
        "property_id": 3041,
        "tenant_profile_id": 116,
        "unit_codes": ["FF050"],
        "contracted_area": 420,
        "city": "Jeddah",
        "lease_brand_mall": "t0105712 - Brand Under Armour - Jawharat Jeddah",
    },
    {
        "lease_code": "t0208831",
        "lease_id": 88210,
        "contract_id": 88210,
        "brand": "Nike",
        "brand_id": 312,
        "mall": "Riyadh Park",
        "property_id": 2018,
        "tenant_profile_id": 204,
        "unit_codes": ["GF101", "GF102"],
        "contracted_area": 680,
        "city": "Riyadh",
        "lease_brand_mall": "t0208831 - Nike - Riyadh Park",
    },
    {
        "lease_code": "t0301144",
        "lease_id": 71033,
        "contract_id": 71033,
        "brand": "Nike",
        "brand_id": 312,
        "mall": "Mall of Arabia",
        "property_id": 1905,
        "tenant_profile_id": 204,
        "unit_codes": ["LG220"],
        "contracted_area": 510,
        "city": "Jeddah",
        "lease_brand_mall": "t0301144 - Nike - Mall of Arabia",
    },
    {
        "lease_code": "t0419977",
        "lease_id": 60511,
        "contract_id": 60511,
        "brand": "Zara",
        "brand_id": 88,
        "mall": "Dubai Festival City",
        "property_id": 4422,
        "tenant_profile_id": 77,
        "unit_codes": ["UF301"],
        "contracted_area": 900,
        "city": "Dubai",
        "lease_brand_mall": "t0419977 - Zara - Dubai Festival City",
    },
]

_MOCK_RECORDS: list[LeaseRecord] = [LeaseRecord.model_validate(r) for r in _MOCK_LEASES]


class MockLeaseLookupService(AbstractLeaseLookupService):
    """In-memory lease lookup for local POC development and unit tests.

    Parameters
    ----------
    records:
        Optional override for the seed data.  Defaults to ``_MOCK_RECORDS``.
    simulated_latency_ms:
        Latency value reported in ``LeaseLookupResult`` (no real sleep).
    """

    _MOCK_ENDPOINT = "mock://lease-tenant-api/leases"

    def __init__(
        self,
        records: list[LeaseRecord] | None = None,
        simulated_latency_ms: int = 12,
    ) -> None:
        self._records: list[LeaseRecord] = records if records is not None else list(_MOCK_RECORDS)
        self._latency_ms = simulated_latency_ms

    async def lookup(self, query: LeaseLookupQuery) -> LeaseLookupResult:
        request_payload: dict[str, Any] = {
            "endpoint": self._MOCK_ENDPOINT,
            **query.model_dump(exclude_none=True),
        }

        matches = self._filter(query)

        response_payload: dict[str, Any] = {
            "leases": [r.model_dump() for r in matches],
            "count": len(matches),
        }

        log.debug(
            "lease_lookup.mock",
            query=query.model_dump(exclude_none=True),
            match_count=len(matches),
        )

        return LeaseLookupResult(
            matches=matches,
            endpoint=self._MOCK_ENDPOINT,
            request_payload=request_payload,
            response_payload=response_payload,
            latency_ms=self._latency_ms,
            status_code=200,
        )

    def _filter(self, query: LeaseLookupQuery) -> list[LeaseRecord]:
        # Priority 1: case-insensitive lease_code match.
        if query.lease_code:
            code_lower = query.lease_code.strip().lower()
            return [r for r in self._records if r.lease_code.lower() == code_lower]

        # Priority 2: brand + mall (both required, bidirectional substring).
        if query.brand and query.mall:
            brand_l = query.brand.lower()
            mall_l = query.mall.lower()
            return [
                r for r in self._records
                if (brand_l in r.brand.lower() or r.brand.lower() in brand_l)
                and (mall_l in r.mall.lower() or r.mall.lower() in mall_l)
            ]

        # Priority 3: brand only (case-insensitive substring, bidirectional).
        # A real search API typically does fuzzy/partial matching in both
        # directions, so we check whether either string contains the other.
        if query.brand:
            brand_l = query.brand.lower()
            return [
                r for r in self._records
                if brand_l in r.brand.lower() or r.brand.lower() in brand_l
            ]

        # Priority 4: mall only (case-insensitive substring, bidirectional).
        # e.g. query "Jawharat Jeddah mall" must still match record "Jawharat Jeddah".
        if query.mall:
            mall_l = query.mall.lower()
            return [
                r for r in self._records
                if mall_l in r.mall.lower() or r.mall.lower() in mall_l
            ]

        return []


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def get_lease_lookup_service() -> AbstractLeaseLookupService:
    """Return the appropriate service based on whether a real API URL is configured."""
    if settings.lease_tenant_api_base_url:
        return HttpLeaseLookupService()
    return MockLeaseLookupService()
