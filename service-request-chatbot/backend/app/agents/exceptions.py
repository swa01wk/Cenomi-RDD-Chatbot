"""Platform-layer typed exceptions for the agent services.

These are raised by ``ServiceRequestPlatformClient`` and caught in the
entry / submission nodes to produce user-friendly messages while preserving
technical detail in the trace.
"""

from __future__ import annotations


class PlatformError(Exception):
    """Base class for all platform-layer errors."""


class PlatformAuthError(PlatformError):
    """Token/login failure — service-to-service auth rejected by the platform."""


class PlatformUploadError(PlatformError):
    """File upload failure on PUT /files."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PlatformValidationError(PlatformError):
    """4xx response from PATCH /service-requests or POST /service-requests."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class StaleSRStatusError(PlatformError):
    """Status sync detected an unexpected or stale SR status."""

    def __init__(self, sr_id: str, expected: str, actual: str | None) -> None:
        super().__init__(
            f"SR {sr_id}: expected status compatible with {expected!r}, got {actual!r}"
        )
        self.sr_id = sr_id
        self.expected = expected
        self.actual = actual


class UnsupportedDocumentTypeError(PlatformError):
    """Document type is not allowed at the current workflow stage."""

    def __init__(self, document_type: str, stage: str) -> None:
        super().__init__(
            f"Document type {document_type!r} is not allowed at stage {stage!r}"
        )
        self.document_type = document_type
        self.stage = stage
