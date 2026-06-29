"""Authentication routes — login and current-user."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.auth import create_access_token, verify_password
from app.core.security import get_auth_context
from app.db.repositories.user_repo import UserRepository
from app.db.session import DbSession
from app.types.chat import AuthContext

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, examples=["aisha@cenomi.com"])
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str
    mall_names: list[str]
    expires_in: int = Field(description="Token lifetime in seconds.")


class MeResponse(BaseModel):
    user_id: str
    role: str
    roles: list[str]
    mall_names: list[str]
    unique_property_ids: list[int]
    is_global_admin: bool


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login and receive a JWT",
    responses={
        status.HTTP_200_OK: {"description": "Login successful."},
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid credentials."},
    },
)
async def login(body: LoginRequest, db: DbSession) -> LoginResponse:
    """Validate username + password and return a signed JWT."""
    repo = UserRepository(db)
    user = await repo.get_by_username(body.username)

    if user is None or not verify_password(body.password, user.password_hash):
        log.warning("auth.login.failed", username=body.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated. Contact your administrator.",
        )

    token = create_access_token(
        {
            "sub": str(user.id),
            "user_id": str(user.id),
            "roles": [user.role],
            "unique_property_ids": user.unique_property_ids,
            "mall_names": user.mall_names,
            "is_global_admin": user.is_global_admin,
        }
    )

    from app.core.config import settings

    log.info("auth.login.success", username=body.username, role=user.role)
    return LoginResponse(
        access_token=token,
        user_id=str(user.id),
        role=user.role,
        mall_names=list(user.mall_names),
        expires_in=settings.jwt_expire_minutes * 60,
    )


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Get current authenticated user",
)
async def me(auth: AuthContext = Depends(get_auth_context)) -> MeResponse:
    """Return the identity derived from the current JWT."""
    return MeResponse(
        user_id=auth.subject_id,
        role=next(iter(auth.roles), ""),
        roles=list(auth.roles),
        mall_names=list(auth.mall_names),
        unique_property_ids=list(auth.unique_property_ids),
        is_global_admin=auth.is_global_admin,
    )
