"""Abstract embedding provider interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for all embedding backends.

    Implementations must be async and return ``None`` on failure so callers
    can treat a ``None`` result as a fallback signal without catching exceptions.
    """

    async def embed(self, text: str) -> list[float] | None:
        """Embed *text* and return the vector, or ``None`` on error."""
        ...
