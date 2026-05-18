"""Authentication and token utilities (scaffolding only)."""

from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.types.chat import AuthContext

security_scheme = HTTPBearer(auto_error=False)


def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
) -> AuthContext:
    """
    Resolve the caller identity from the request.

    Production: validate JWT / session, map to tenant and roles.
    """
    if credentials is None or not credentials.credentials:
        # POC-friendly default; tighten when auth is wired.
        return AuthContext(subject_id="anonymous", tenant_id=None, roles=frozenset())
    # Placeholder: propagate opaque token; real validation lives here later.
    return AuthContext(subject_id="authenticated-user", tenant_id=None, roles=frozenset())


def require_bearer(credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme)) -> str:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    return credentials.credentials


def redact_secrets(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive fields before logging or persisting debug views."""
    blocked = {"password", "token", "authorization", "secret", "api_key"}
    return {k: v for k, v in payload.items() if k.lower() not in blocked}
