"""Unit tests for ChatSessionRepository."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.db.exceptions import InvalidUpdateFieldError, RecordNotFoundError
from app.db.models import ChatSession
from app.db.repositories.chat_session_repo import ChatSessionRepository


# ── helpers ────────────────────────────────────────────────────────────────


def _make_session_row(**kwargs: object) -> ChatSession:
    """Build a detached ChatSession without a DB connection."""
    defaults: dict[str, object] = {
        "id": uuid4(),
        "user_id": uuid4(),
        "status": "IN_PROGRESS",
        "active_agent": None,
        "intent": None,
        "workflow_stage": None,
    }
    defaults.update(kwargs)
    return ChatSession(**defaults)  # type: ignore[arg-type]


# ── create ─────────────────────────────────────────────────────────────────


async def test_create_returns_chat_session(mock_session: AsyncMock) -> None:
    user_id = uuid4()
    repo = ChatSessionRepository(mock_session)

    result = await repo.create(user_id=user_id)

    assert isinstance(result, ChatSession)
    assert result.user_id == user_id
    assert result.status == "IN_PROGRESS"
    mock_session.add.assert_called_once_with(result)
    mock_session.flush.assert_awaited_once()


async def test_create_with_explicit_fields(mock_session: AsyncMock) -> None:
    user_id = uuid4()
    repo = ChatSessionRepository(mock_session)

    result = await repo.create(
        user_id=user_id,
        active_agent="extraction_agent",
        intent="lease_issue",
        workflow_stage="collect_fields",
        status="IN_PROGRESS",
    )

    assert result.active_agent == "extraction_agent"
    assert result.intent == "lease_issue"
    assert result.workflow_stage == "collect_fields"


async def test_create_defaults_active_agent_to_none(mock_session: AsyncMock) -> None:
    repo = ChatSessionRepository(mock_session)
    result = await repo.create(user_id=uuid4())
    assert result.active_agent is None
    assert result.intent is None
    assert result.workflow_stage is None


# ── get_by_id ──────────────────────────────────────────────────────────────


async def test_get_by_id_returns_row(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    row = _make_session_row()
    mock_session.execute.return_value = make_execute_result(scalar=row)  # type: ignore[operator]
    repo = ChatSessionRepository(mock_session)

    result = await repo.get_by_id(row.id)  # type: ignore[arg-type]

    assert result is row
    mock_session.execute.assert_awaited_once()


async def test_get_by_id_returns_none_when_missing(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = ChatSessionRepository(mock_session)

    result = await repo.get_by_id(uuid4())

    assert result is None


# ── update ─────────────────────────────────────────────────────────────────


async def test_update_applies_changes(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    row = _make_session_row(status="IN_PROGRESS", active_agent=None)
    mock_session.execute.return_value = make_execute_result(scalar=row)  # type: ignore[operator]
    repo = ChatSessionRepository(mock_session)

    updated = await repo.update(
        row.id,  # type: ignore[arg-type]
        {"status": "COMPLETED", "active_agent": "supervisor"},
    )

    assert updated.status == "COMPLETED"
    assert updated.active_agent == "supervisor"
    mock_session.flush.assert_awaited_once()


async def test_update_raises_not_found(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = ChatSessionRepository(mock_session)

    with pytest.raises(RecordNotFoundError) as exc_info:
        await repo.update(uuid4(), {"status": "COMPLETED"})

    assert "ChatSession" in str(exc_info.value)


async def test_update_raises_for_non_updatable_field(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    row = _make_session_row()
    mock_session.execute.return_value = make_execute_result(scalar=row)  # type: ignore[operator]
    repo = ChatSessionRepository(mock_session)

    with pytest.raises(InvalidUpdateFieldError) as exc_info:
        await repo.update(row.id, {"user_id": uuid4()})  # type: ignore[arg-type]

    assert "user_id" in str(exc_info.value)


async def test_update_does_not_flush_on_not_found(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = ChatSessionRepository(mock_session)

    with pytest.raises(RecordNotFoundError):
        await repo.update(uuid4(), {"status": "COMPLETED"})

    mock_session.flush.assert_not_awaited()


async def test_update_all_allowed_fields(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    row = _make_session_row()
    mock_session.execute.return_value = make_execute_result(scalar=row)  # type: ignore[operator]
    repo = ChatSessionRepository(mock_session)

    updated = await repo.update(
        row.id,  # type: ignore[arg-type]
        {
            "active_agent": "validation_agent",
            "intent": "maintenance",
            "workflow_stage": "validate",
            "status": "IN_PROGRESS",
        },
    )

    assert updated.active_agent == "validation_agent"
    assert updated.intent == "maintenance"
    assert updated.workflow_stage == "validate"
    mock_session.flush.assert_awaited_once()
