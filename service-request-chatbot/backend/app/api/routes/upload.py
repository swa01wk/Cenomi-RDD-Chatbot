"""Document upload route with document-type and role validation.

Guards applied (in order)
--------------------------
1. **Role check** — caller must hold ``CAN_RAISE_HANDOVER_SR``; returns 403
   on failure.  (POC: ``get_auth_context`` returns a stub; tighten when JWT
   is wired.)
2. **Content-type allowlist** — only PDF, JPEG, and PNG are accepted; returns
   415 for anything else.
3. **Document-type validation** — when the optional ``document_type`` form
   field is supplied it must be one of the values in ``ALL_DOCUMENT_TYPES``
   from ``handover_schema``; returns 422 otherwise.

The file bytes are **not** stored by this stub endpoint.  Actual virus
scanning, cloud storage upload, and metadata persistence are out of scope for
the POC.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.agents.schemas.handover_schema import ALL_DOCUMENT_TYPES
from app.agents.services.permission_service import PermissionDeniedError, PermissionService
from app.core.security import get_auth_context
from app.types.chat import AuthContext

router = APIRouter()

# ---------------------------------------------------------------------------
# Allowed MIME types for uploaded files
# ---------------------------------------------------------------------------

_ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
    }
)

_permission_service = PermissionService()


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    document_type: str | None = Form(default=None),
    auth: AuthContext = Depends(get_auth_context),
) -> dict[str, str]:
    """Accept a document file with role and document-type validation.

    Parameters
    ----------
    file:
        The uploaded file (multipart).
    document_type:
        Optional document-type identifier (e.g. ``"SR_HANDOVER_CHECKLIST"``).
        When provided it must be a member of ``ALL_DOCUMENT_TYPES``.
    auth:
        Resolved from the ``Authorization`` header by ``get_auth_context``.
    """
    # 1. Role check -----------------------------------------------------------
    try:
        _permission_service.ensure_can_create_request(auth)
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    # 2. Content-type allowlist -----------------------------------------------
    content_type = (file.content_type or "").lower()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported file type '{content_type}'. "
                f"Allowed types: {sorted(_ALLOWED_CONTENT_TYPES)}."
            ),
        )

    # 3. Document-type validation ---------------------------------------------
    if document_type is not None:
        if document_type not in ALL_DOCUMENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Unknown document_type '{document_type}'. "
                    f"Valid types: {sorted(ALL_DOCUMENT_TYPES)}."
                ),
            )

    return {
        "filename": file.filename or "unknown",
        "content_type": content_type,
        "document_type": document_type or "unspecified",
        "status": "received_stub",
    }
