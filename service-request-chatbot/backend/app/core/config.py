"""Application configuration via environment variables."""

from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="service-request-chatbot-api", validation_alias="APP_NAME")
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")
    debug: bool = Field(default=False, validation_alias="DEBUG")
    api_v1_prefix: str = Field(default="/api/v1", validation_alias="API_V1_PREFIX")

    cors_origins: str = Field(
        default="http://localhost:3000",
        validation_alias="CORS_ORIGINS",
        description="Comma-separated list of allowed browser origins.",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/service_request_chatbot",
        validation_alias="DATABASE_URL",
        description="Async SQLAlchemy URL, e.g. postgresql+asyncpg://...",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", validation_alias="REDIS_URL")

    service_request_api_base_url: str | None = Field(
        default=None, validation_alias="SERVICE_REQUEST_API_BASE_URL"
    )
    lease_tenant_api_base_url: str | None = Field(
        default=None, validation_alias="LEASE_TENANT_API_BASE_URL"
    )
    file_upload_api_base_url: str | None = Field(
        default=None, validation_alias="FILE_UPLOAD_API_BASE_URL"
    )

    # ── Platform auth (service-to-service; separate from user JWT) ────────────
    platform_auth_base_url: str | None = Field(
        default=None,
        validation_alias="PLATFORM_AUTH_BASE_URL",
        description=(
            "Base URL for the Cenomi platform auth endpoint "
            "(POST /cenomi-ai/login). Defaults to SERVICE_REQUEST_API_BASE_URL when absent."
        ),
    )
    platform_internal_api_token: str | None = Field(
        default=None,
        validation_alias="PLATFORM_INTERNAL_API_TOKEN",
        description="x-internal-api-token header value for the platform login call.",
    )
    platform_login_email: str | None = Field(
        default=None,
        validation_alias="PLATFORM_LOGIN_EMAIL",
        description="Email address used for service-to-service platform login.",
    )

    # ── Platform API (service-to-service auth) ────────────────────────────────
    # ``platform_base_url`` is an alias for ``service_request_api_base_url``
    # kept for clarity in platform_api_client and related modules.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def platform_base_url(self) -> str | None:
        return self.service_request_api_base_url

    platform_auth_base_url: str | None = Field(
        default=None,
        validation_alias="PLATFORM_AUTH_BASE_URL",
        description=(
            "Base URL for the platform auth endpoint (POST /cenomi-ai/login). "
            "Defaults to platform_base_url when absent."
        ),
    )
    platform_internal_api_token: str | None = Field(
        default=None,
        validation_alias="PLATFORM_INTERNAL_API_TOKEN",
        description="Service-to-service internal API token for platform login.",
    )
    platform_login_email: str | None = Field(
        default=None,
        validation_alias="PLATFORM_LOGIN_EMAIL",
        description="Email used for service-to-service platform login.",
    )

    jwt_secret_key: str = Field(default="change-me", validation_alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")

    # ── LLM / AI ──────────────────────────────────────────────────────────────
    openai_api_key: str | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
        description="OpenAI API key used by LLMGateway (required in production).",
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        validation_alias="LLM_MODEL",
        description="Chat model passed to LLMGateway (must support json_object response_format).",
    )
    llm_base_url: str | None = Field(
        default=None,
        validation_alias="LLM_BASE_URL",
        description="Optional custom base URL for the OpenAI-compatible endpoint.",
    )
    llm_confidence_threshold: float = Field(
        default=0.6,
        validation_alias="LLM_CONFIDENCE_THRESHOLD",
        description="Minimum supervisor confidence before routing; below this asks clarification.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
