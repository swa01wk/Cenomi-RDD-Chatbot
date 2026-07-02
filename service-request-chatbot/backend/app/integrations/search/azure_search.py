"""Azure AI Search repository.

Ported from the staging ``cenomi-ai-backend`` ``app/integrations/azure/search.py``
with the following adaptations:
- ``EmbeddingProvider`` injected at construction — no internal Azure OAI calls.
- Standard ``logging`` replaced with ``structlog.get_logger(__name__)``.
- ``close()`` coroutine added for graceful ``httpx.AsyncClient`` shutdown.
- Import paths updated to match this repo's layout.
- Semantic reranking (``queryType=semantic``) removed — ``cenomi-help-index`` does
  not define a named semantic configuration, so including it causes a 400 Bad Request.
  Queries use hybrid BM25 keyword + dense vector search instead.
- Language filter added: each sub-query scopes results to ``language eq '<lang>'``
  so Arabic queries return Arabic documents and English queries return English documents.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import structlog

from app.integrations.embeddings.base import EmbeddingProvider
from app.integrations.search.base import SearchResult

log = structlog.get_logger(__name__)

# Sub-query configuration: (source_type_filter, top_k)
_QUERY_CONFIG: list[tuple[str, int]] = [
    ("help_content", 3),
    ("mall_info", 4),
    ("key_contact", 3),  # increased from 2: contact cards score lower than narrative docs
    ("event", 2),
]


class AzureSearchRepository:
    """Hybrid vector + keyword search against the ``cenomi-help-index`` index.

    Runs 4 parallel sub-queries (one per source type) via ``asyncio.gather``,
    deduplicates by document key, and returns the merged ranked list.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        index_name: str,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._index_name = index_name
        self._embedding_provider = embedding_provider
        self._client = httpx.AsyncClient(
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        lang: str = "en",
        top_k: int = 5,
    ) -> list[SearchResult]:
        """Run parallel hybrid search and return merged, deduplicated results.

        Parameters
        ----------
        query:
            The user's natural-language question (already cleaned by the node).
        lang:
            Language hint: ``"en"`` or ``"ar"``.  Passed to the search filter
            so language-specific content is preferred when available.
        top_k:
            Maximum total results to return after deduplication.
        """
        t0 = time.monotonic()

        vector = await self._embedding_provider.embed(query)
        embed_ms = int((time.monotonic() - t0) * 1000)

        if vector is None:
            log.warning(
                "azure_search.embed_failed",
                index_name=self._index_name,
                embed_ms=embed_ms,
            )
            return []

        log.info(
            "azure_search.embed_complete",
            index_name=self._index_name,
            embed_ms=embed_ms,
            vector_dims=len(vector),
        )

        t1 = time.monotonic()
        tasks = [
            self._run_sub_query(query=query, lang=lang, source_type=src, top_n=n, vector=vector)
            for src, n in _QUERY_CONFIG
        ]
        raw_results: list[list[SearchResult]] = await asyncio.gather(*tasks)
        search_ms = int((time.monotonic() - t1) * 1000)

        merged = self._deduplicate(raw_results)
        log.info(
            "azure_search.search_complete",
            index_name=self._index_name,
            search_ms=search_ms,
            hits=len(merged),
        )

        return merged[:top_k]

    async def close(self) -> None:
        """Close the underlying ``httpx.AsyncClient``."""
        await self._client.aclose()
        log.debug("azure_search.client_closed", index_name=self._index_name)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _run_sub_query(
        self,
        *,
        query: str,
        lang: str,
        source_type: str,
        top_n: int,
        vector: list[float],
    ) -> list[SearchResult]:
        """Execute a single hybrid search query for one source type.

        The ``lang`` parameter is applied as an OData filter on the ``language``
        field so Arabic queries return Arabic-language documents and English
        queries return English-language documents.  The index stores documents
        in both ``"en"`` and ``"ar"`` variants; filtering prevents mixed-language
        results from degrading the response quality.
        """
        url = (
            f"{self._endpoint}/indexes/{self._index_name}"
            f"/docs/search?api-version=2023-11-01"
        )
        # Hybrid search: BM25 keyword + dense vector similarity.
        # Semantic reranking (queryType=semantic) is intentionally omitted — the
        # cenomi-help-index does not have a named semantic configuration, so
        # including semanticConfiguration causes a 400 Bad Request.
        body: dict[str, Any] = {
            "search": query,
            "top": top_n,
            "filter": f"source_type eq '{source_type}' and language eq '{lang}'",
            "vectorQueries": [
                {
                    "kind": "vector",
                    "vector": vector,
                    "fields": "content_vector",
                    "k": top_n,
                }
            ],
            "select": "id,source_type,title,content,url_pattern,mall_name,language",
        }

        try:
            resp = await self._client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            log.warning(
                "azure_search.sub_query_http_error",
                index_name=self._index_name,
                query_type=source_type,
                status_code=exc.response.status_code,
                error=str(exc),
            )
            return []
        except Exception as exc:
            log.warning(
                "azure_search.sub_query_error",
                index_name=self._index_name,
                query_type=source_type,
                error=str(exc),
            )
            return []

        results: list[SearchResult] = []
        for doc in data.get("value", []):
            results.append(
                SearchResult(
                    source_type=doc.get("source_type", source_type),
                    title=doc.get("title", ""),
                    content=doc.get("content", ""),
                    url_pattern=doc.get("url_pattern", ""),
                    mall_name=doc.get("mall_name", ""),
                    language=doc.get("language", ""),
                )
            )

        log.debug(
            "azure_search.sub_query_done",
            index_name=self._index_name,
            query_type=source_type,
            hits=len(results),
        )
        return results

    @staticmethod
    def _deduplicate(grouped: list[list[SearchResult]]) -> list[SearchResult]:
        """Flatten, deduplicate, and interleave by source type.

        Strategy: one round-robin pass guarantees at least one result per
        non-empty source type before filling remaining slots in flat order.
        This prevents high-volume source types (mall_info, help_content) from
        crowding out low-volume types (key_contact, event) when the global
        ``top_k`` cap is applied by the caller.
        """
        seen: set[tuple[str, str]] = set()
        merged: list[SearchResult] = []

        # Round 1: take the best result from each non-empty group in order.
        for group in grouped:
            for result in group:
                key = (result.source_type, result.title)
                if key not in seen:
                    seen.add(key)
                    merged.append(result)
                    break  # one per group in round 1

        # Round 2: fill in remaining results from all groups in flat order.
        for group in grouped:
            for result in group:
                key = (result.source_type, result.title)
                if key not in seen:
                    seen.add(key)
                    merged.append(result)

        return merged
