"""Authentication and token utilities."""

from __future__ import annotations

import logging
from typing import Any

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from app.core.auth import decode_access_token
from app.core.config import settings
from app.types.chat import AuthContext

log = structlog.get_logger(__name__)
logger = logging.getLogger(__name__)

security_scheme = HTTPBearer(auto_error=False)


def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
) -> AuthContext:
    """Resolve caller identity from the bearer JWT.

    Shadow mode (``RBAC_ENFORCE=false``, default):
        No token → anonymous AuthContext (empty roles, no scoping).
        Invalid/expired token → warn log, anonymous AuthContext.

    Enforce mode (``RBAC_ENFORCE=true``):
        No token → HTTP 401.
        Invalid/expired token → HTTP 401.
    """
    if credentials is None or not credentials.credentials:
        if settings.rbac_enforce:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required. Please log in.",
            )
        return AuthContext(subject_id="anonymous")

    try:
        payload = decode_access_token(credentials.credentials)
    except JWTError as exc:
        if settings.rbac_enforce:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token. Please log in again.",
            ) from exc
        logger.warning("security.invalid_jwt: %s", exc)
        return AuthContext(subject_id="unauthenticated")

    return AuthContext(
        subject_id=str(payload.get("user_id", payload.get("sub", "unknown"))),
        tenant_id=payload.get("tenant_id"),
        roles=frozenset(payload.get("roles", [])),
        unique_property_ids=tuple(int(x) for x in payload.get("unique_property_ids", [])),
        mall_names=tuple(payload.get("mall_names", [])),
        is_global_admin=bool(payload.get("is_global_admin", False)),
    )


def require_bearer(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
) -> str:
    """Require a bearer token; raise HTTP 401 if absent."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    return credentials.credentials


def redact_secrets(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive fields before logging or persisting debug views."""
    blocked = {"password", "token", "authorization", "secret", "api_key", "password_hash"}
    return {k: v for k, v in payload.items() if k.lower() not in blocked}
