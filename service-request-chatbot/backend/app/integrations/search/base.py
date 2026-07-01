"""Abstract search repository interface and shared data types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SearchResult:
    """A single chunk returned from the knowledge base."""

    source_type: str    # e.g. "help_content", "mall_info", "key_contact", "event"
    title: str
    content: str
    url_pattern: str = ""
    mall_name: str = ""
    language: str = ""


class SearchRepository(Protocol):
    """Protocol for all search backends.

    Implementations receive an ``EmbeddingProvider`` at construction time so
    embedding and search backends are independently swappable.
    """

    async def search(
        self,
        query: str,
        lang: str,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """Run hybrid search and return ranked results."""
        ...

    async def close(self) -> None:
        """Release any held HTTP clients or connections."""
        ...
