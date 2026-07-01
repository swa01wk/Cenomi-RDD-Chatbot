"""Azure OpenAI embedding provider.

Uses ``openai.AsyncAzureOpenAI`` with ``azure_endpoint``, ``api_key``, and
``api_version``.  Selected when ``EMBEDDING_PROVIDER=azure_openai``.
"""

from __future__ import annotations

import structlog
from openai import AsyncAzureOpenAI, APIError

log = structlog.get_logger(__name__)


class AzureOpenAIEmbeddingProvider:
    """Embed text using the Azure OpenAI embeddings endpoint."""

    def __init__(
        self,
        azure_endpoint: str,
        api_key: str,
        model: str = "text-embedding-3-small",
        api_version: str = "2024-02-15-preview",
    ) -> None:
        self._model = model
        self._client = AsyncAzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=api_key,
            api_version=api_version,
        )

    async def embed(self, text: str) -> list[float] | None:
        """Return the embedding vector for *text*, or ``None`` on error."""
        try:
            response = await self._client.embeddings.create(
                input=text,
                model=self._model,
            )
            return response.data[0].embedding
        except APIError as exc:
            log.warning(
                "azure_openai_embed.api_error",
                model=self._model,
                status_code=getattr(exc, "status_code", None),
                error=str(exc),
            )
            return None
        except Exception as exc:
            log.warning(
                "azure_openai_embed.unexpected_error",
                model=self._model,
                error=str(exc),
            )
            return None
