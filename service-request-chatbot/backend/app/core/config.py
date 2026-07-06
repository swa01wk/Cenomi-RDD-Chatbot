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
    api_v2_prefix: str = Field(default="/api/v2", validation_alias="API_V2_PREFIX")

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
    # FILE_UPLOAD_API_BASE_URL is accepted in .env for forward compatibility but
    # is not currently used — file uploads route through SERVICE_REQUEST_API_BASE_URL
    # + PUT /files per the Postman collection.  Keeping the field avoids noisy
    # "extra fields not permitted" errors if operators set it.
    file_upload_api_base_url: str | None = Field(
        default=None,
        validation_alias="FILE_UPLOAD_API_BASE_URL",
        description=(
            "Reserved for future use. File uploads currently use "
            "SERVICE_REQUEST_API_BASE_URL + /files (per Postman collection)."
        ),
    )

    # ── Platform auth (service-to-service; separate from user JWT) ────────────

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

    # ── MSP Platform integration ──────────────────────────────────────────────
    msp_service_token: str | None = Field(
        default=None,
        validation_alias="MSP_SERVICE_TOKEN",
        description=(
            "Inbound x-internal-api-token value expected from the MSP Platform frontend. "
            "When set, /api/v1/chat and /api/v1/chat/stream reject requests that omit or "
            "mismatch this token.  When absent (default), validation is skipped — "
            "shadow mode, matching the RBAC_ENFORCE=false pattern."
        ),
    )

    jwt_secret_key: str = Field(default="change-me", validation_alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=60, validation_alias="JWT_EXPIRE_MINUTES")
    rbac_enforce: bool = Field(
        default=False,
        validation_alias="RBAC_ENFORCE",
        description="True = reject requests without a valid JWT. False = shadow mode (warn, pass through).",
    )

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

    # ── RAG provider selection ────────────────────────────────────────────────
    embedding_provider: str = Field(
        default="openai",
        validation_alias="EMBEDDING_PROVIDER",
        description="Embedding backend: 'openai' (default) or 'azure_openai'.",
    )
    search_provider: str = Field(
        default="azure_search",
        validation_alias="SEARCH_PROVIDER",
        description="Search backend: 'azure_search' (only current impl).",
    )

    # Embeddings — standard OpenAI (reuses existing openai_api_key)
    embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias="EMBEDDING_MODEL",
        description="Embedding model name (used by both OpenAI and Azure OpenAI providers).",
    )
    embedding_base_url: str | None = Field(
        default=None,
        validation_alias="EMBEDDING_BASE_URL",
        description="Optional custom base URL for OpenAI-compatible embedding endpoint.",
    )

    # Embeddings — Azure OpenAI (only when EMBEDDING_PROVIDER=azure_openai)
    azure_ai_endpoint: str | None = Field(
        default=None,
        validation_alias="AZURE_AI_ENDPOINT",
        description="Azure OpenAI endpoint, e.g. https://<instance>.openai.azure.com",
    )
    azure_ai_api_key: str | None = Field(
        default=None,
        validation_alias="AZURE_AI_API_KEY",
        description="Azure OpenAI API key (only when EMBEDDING_PROVIDER=azure_openai).",
    )
    azure_ai_api_version: str = Field(
        default="2024-02-15-preview",
        validation_alias="AZURE_AI_API_VERSION",
        description="Azure OpenAI API version for embedding calls.",
    )

    # Search — Azure AI Search (only when SEARCH_PROVIDER=azure_search)
    azure_search_endpoint: str | None = Field(
        default=None,
        validation_alias="AZURE_SEARCH_ENDPOINT",
        description="Azure AI Search endpoint, e.g. https://<instance>.search.windows.net",
    )
    azure_search_api_key: str | None = Field(
        default=None,
        validation_alias="AZURE_SEARCH_API_KEY",
        description="Azure AI Search admin/query key.",
    )
    azure_search_index_name: str | None = Field(
        default=None,
        validation_alias="AZURE_SEARCH_INDEX_NAME",
        description="Azure AI Search index name (e.g. cenomi-help-index).",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
