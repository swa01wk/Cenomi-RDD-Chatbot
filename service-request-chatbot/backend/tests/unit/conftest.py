"""Shared pytest fixtures for repository unit tests.

All tests run against a mocked AsyncSession — no database connection required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture()
def mock_session() -> AsyncMock:
    """Return a mocked AsyncSession with the most-used hooks pre-configured.

    ``session.add`` is a plain MagicMock (synchronous).
    ``session.flush`` is an AsyncMock (awaitable, no-op).
    ``session.execute`` is an AsyncMock; tests set its ``return_value`` per call.
    """
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture()
def make_execute_result():
    """Factory that builds a fake ``CursorResult`` for ``session.execute``.

    Usage::

        result = make_execute_result(scalar=my_model_instance)
        mock_session.execute.return_value = result

    For list returns::

        result = make_execute_result(scalars=[a, b, c])
        mock_session.execute.return_value = result
    """

    def _factory(
        scalar: object = None,
        scalars: list[object] | None = None,
    ) -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = scalar
        # Also wire scalar_one so aggregate (COUNT) queries work in unit tests.
        result.scalar_one.return_value = scalar

        scalars_mock = MagicMock()
        scalars_mock.__iter__ = MagicMock(return_value=iter(scalars or []))
        result.scalars.return_value = scalars_mock

        return result

    return _factory


# ---------------------------------------------------------------------------
# Observability repo fixtures — used by test_trace_manager.py
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_trace_repo() -> AsyncMock:
    """AsyncMock for TraceRepository with create and complete pre-wired."""
    from app.observability.repositories.trace_repo import TraceRepository

    repo = AsyncMock(spec=TraceRepository)
    repo.create = AsyncMock()
    repo.complete = AsyncMock()
    repo.update = AsyncMock()
    repo.get = AsyncMock(return_value=None)
    return repo


@pytest.fixture()
def mock_run_repo() -> AsyncMock:
    """AsyncMock for RunRepository with create and complete pre-wired."""
    from app.observability.repositories.run_repo import RunRepository

    repo = AsyncMock(spec=RunRepository)
    repo.create = AsyncMock()
    repo.complete = AsyncMock()
    repo.update = AsyncMock()
    repo.get = AsyncMock(return_value=None)
    return repo


@pytest.fixture()
def mock_llm_repo() -> AsyncMock:
    """AsyncMock for LLMCallRepository."""
    from app.observability.repositories.llm_call_repo import LLMCallRepository

    repo = AsyncMock(spec=LLMCallRepository)
    repo.create = AsyncMock()
    return repo


@pytest.fixture()
def mock_tool_repo() -> AsyncMock:
    """AsyncMock for ToolCallRepository."""
    from app.observability.repositories.tool_call_repo import ToolCallRepository

    repo = AsyncMock(spec=ToolCallRepository)
    repo.create = AsyncMock()
    return repo
