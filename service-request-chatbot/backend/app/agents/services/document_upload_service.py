"""File upload integration — delegates to ServiceRequestPlatformClient.

``DocumentUploadService`` is the single service-layer entry-point for all
document uploads.  It translates domain-level arguments into the
``FileUploadMetadata`` shape expected by the platform client and maps the
platform result to a domain ``DocumentUploadResult``.

The platform client (``ServiceRequestPlatformClient``) handles the actual
HTTP PUT /files call, token management, and retry-safe error mapping.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from typing import Any

import structlog

from app.agents.exceptions import PlatformUploadError
from app.agents.services.platform_api_client import FileUploadMetadata, get_platform_client

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class DocumentUploadResult:
    """Canonical result of a successful document upload.

    Attributes
    ----------
    document_id:     UUID assigned by the platform for this document.
    file_path:       Cloud storage path returned by the platform.
    signed_url:      Pre-signed download URL (may be ``None`` when not requested).
    document_type_id: The document type passed on upload.
    error:           Human-readable error string; ``None`` on success.
    """

    document_id: str | None
    file_path: str | None
    signed_url: str | None
    document_type_id: str
    error: str | None = None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class DocumentUploadService:
    """Upload documents to the Cenomi platform via PUT /files.

    This replaces the previous stub that only returned
    ``"placeholder-document-id"``.
    """

    def __init__(self) -> None:
        self._client = get_platform_client()

    async def upload_document(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        document_type_id: str,
        sr_id: str,
        lease_id: str,
        brand_id: str,
        property_id: str,
        lease_code: str,
        tenant_profile_id: str,
        document_type_status: str = "",
    ) -> DocumentUploadResult:
        """Upload *file_bytes* to the platform and return the assigned document ID.

        Parameters
        ----------
        file_bytes:             Raw file content.
        filename:               Original filename (used to derive extension).
        content_type:           MIME type of the file.
        document_type_id:       Platform document-type identifier
                                (e.g. ``"SR_HANDOVER_CHECKLIST"``).
        sr_id:                  The service request this document belongs to.
        lease_id, brand_id, ...: Backend refs required by the platform.
        document_type_status:   Set to ``"APPROVED"`` for RDD report;
                                leave empty (``""``) for FM documents.

        Returns
        -------
        DocumentUploadResult
            On success ``document_id`` is populated.
            On failure ``error`` is populated and ``document_id`` is ``None``.
        """
        file_extension = _derive_extension(filename, content_type)

        metadata = FileUploadMetadata(
            document_type_id=document_type_id,
            sr_id=sr_id,
            lease_id=str(lease_id),
            brand_id=str(brand_id),
            property_id=str(property_id),
            lease_code=lease_code,
            tenant_profile_id=str(tenant_profile_id),
            document_type_status=document_type_status,
            file_extension=file_extension,
        )

        log.info(
            "document_upload_service.upload.start",
            document_type_id=document_type_id,
            sr_id=sr_id,
            filename=filename,
            content_type=content_type,
        )

        result = await self._client.upload_file(file_bytes, metadata)

        if result.error or result.document_id is None:
            log.warning(
                "document_upload_service.upload.failed",
                document_type_id=document_type_id,
                sr_id=sr_id,
                error=result.error,
                status_code=result.status_code,
            )
            return DocumentUploadResult(
                document_id=None,
                file_path=None,
                signed_url=None,
                document_type_id=document_type_id,
                error=result.error or "Upload failed: no document_id returned",
            )

        log.info(
            "document_upload_service.upload.success",
            document_id=result.document_id,
            document_type_id=document_type_id,
            sr_id=sr_id,
        )
        return DocumentUploadResult(
            document_id=result.document_id,
            file_path=result.file_path,
            signed_url=result.signed_url,
            document_type_id=document_type_id,
        )

    # ------------------------------------------------------------------
    # Backward-compatible stub method (kept for any legacy callers)
    # ------------------------------------------------------------------

    async def register_upload(self, filename: str, content_type: str) -> str:
        """Backward-compatible stub — always returns a placeholder.

        New code should call ``upload_document`` directly.
        """
        return "placeholder-document-id"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _derive_extension(filename: str, content_type: str) -> str:
    """Return a file extension string (without dot) from *filename* or *content_type*."""
    if filename and "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    ext = mimetypes.guess_extension(content_type)
    if ext:
        return ext.lstrip(".").lower()
    return "bin"
