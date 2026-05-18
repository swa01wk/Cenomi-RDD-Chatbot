"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, upload
from app.api.routes.chat import router as chat_router
from app.api.routes.chat import service_request_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.observability.api import feedback as obs_feedback
from app.observability.api import metrics as obs_metrics
from app.observability.api import sessions as obs_sessions
from app.observability.api import traces as obs_traces


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    # DB/redis engines are created lazily via session helpers; add migrations/startup checks here later.
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
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

    application.include_router(health.router, prefix=settings.api_v1_prefix, tags=["health"])
    # Primary service-request chat endpoint — mounted at /api (no version prefix per spec)
    application.include_router(service_request_router, prefix="/api", tags=["chat"])
    # Legacy v1 chat stub — kept for backward compatibility
    application.include_router(chat_router, prefix=settings.api_v1_prefix, tags=["chat"])
    application.include_router(upload.router, prefix=settings.api_v1_prefix, tags=["upload"])
    # Observability routes mounted at /api (no version prefix) per spec
    application.include_router(obs_traces.router, prefix="/api", tags=["observability"])
    application.include_router(obs_feedback.router, prefix="/api", tags=["observability"])
    application.include_router(obs_sessions.router, prefix="/api", tags=["observability"])
    application.include_router(obs_metrics.router, prefix=settings.api_v1_prefix, tags=["observability"])

    return application


app = create_app()
