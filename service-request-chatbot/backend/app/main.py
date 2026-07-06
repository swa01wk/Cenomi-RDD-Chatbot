"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, upload
from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.chat import service_request_router
from app.api.routes.msp_chat import msp_chat_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.integrations.factory import close_integrations
from app.observability.api import feedback as obs_feedback
from app.observability.api import metrics as obs_metrics
from app.observability.api import sessions as obs_sessions
from app.observability.api import traces as obs_traces


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    # DB/redis engines are created lazily via session helpers; add migrations/startup checks here later.
    yield
    # Close any open RAG integration HTTP clients (httpx.AsyncClient in AzureSearchRepository).
    await close_integrations()


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins_list),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── v1 routes (kept for backward compatibility) ───────────────────────────

    application.include_router(health.router, prefix=settings.api_v1_prefix, tags=["health-v1"])
    application.include_router(auth_router, prefix="/api", tags=["auth"])
    # Original service-request endpoint — unversioned path kept for RDD frontend
    application.include_router(service_request_router, prefix="/api", tags=["chat"])
    # Legacy v1 chat stub
    application.include_router(chat_router, prefix=settings.api_v1_prefix, tags=["chat-v1"])
    # MSP Platform-compatible help endpoints — contractually pinned to /api/v1 by cenomi-ai-backend
    application.include_router(msp_chat_router, prefix=settings.api_v1_prefix, tags=["msp-chat"])
    application.include_router(upload.router, prefix=settings.api_v1_prefix, tags=["upload-v1"])
    # Observability (unversioned legacy paths)
    application.include_router(obs_traces.router, prefix="/api", tags=["observability"])
    application.include_router(obs_feedback.router, prefix="/api", tags=["observability"])
    application.include_router(obs_sessions.router, prefix="/api", tags=["observability"])
    application.include_router(obs_metrics.router, prefix=settings.api_v1_prefix, tags=["observability-v1"])

    # ── v2 routes (current — new callers should use these) ────────────────────

    application.include_router(health.router, prefix=settings.api_v2_prefix, tags=["health-v2"])
    application.include_router(auth_router, prefix=settings.api_v2_prefix, tags=["auth-v2"])
    application.include_router(service_request_router, prefix=settings.api_v2_prefix, tags=["chat-v2"])
    application.include_router(chat_router, prefix=settings.api_v2_prefix, tags=["chat-v2"])
    application.include_router(upload.router, prefix=settings.api_v2_prefix, tags=["upload-v2"])
    application.include_router(obs_traces.router, prefix=settings.api_v2_prefix, tags=["observability-v2"])
    application.include_router(obs_feedback.router, prefix=settings.api_v2_prefix, tags=["observability-v2"])
    application.include_router(obs_sessions.router, prefix=settings.api_v2_prefix, tags=["observability-v2"])
    application.include_router(obs_metrics.router, prefix=settings.api_v2_prefix, tags=["observability-v2"])
    # Note: msp_chat_router is intentionally NOT duplicated at v2 — MSP Platform
    # contract is fixed to /api/v1/chat and /api/v1/chat/stream.

    return application


app = create_app()
