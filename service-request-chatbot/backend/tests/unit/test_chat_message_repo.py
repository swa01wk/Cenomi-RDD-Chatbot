"""Unit tests for ChatMessageRepository."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.db.exceptions import InvalidUpdateFieldError, RecordNotFoundError
from app.db.models import ChatMessage
from app.db.repositories.chat_message_repo import ChatMessageRepository


# ── helpers ────────────────────────────────────────────────────────────────


def _make_message(**kwargs: object) -> ChatMessage:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "session_id": uuid4(),
        "role": "user",
        "content": "Hello",
        "metadata_": {},
    }
    defaults.update(kwargs)
    return ChatMessage(**defaults)  # type: ignore[arg-type]


# ── create ─────────────────────────────────────────────────────────────────


async def test_create_returns_chat_message(mock_session: AsyncMock) -> None:
    session_id = uuid4()
    repo = ChatMessageRepository(mock_session)

    result = await repo.create(session_id=session_id, role="user", content="Hi there")

    assert isinstance(result, ChatMessage)
    assert result.session_id == session_id
    assert result.role == "user"
    assert result.content == "Hi there"
    assert result.metadata_ == {}
    mock_session.add.assert_called_once_with(result)
    mock_session.flush.assert_awaited_once()


async def test_create_with_metadata(mock_session: AsyncMock) -> None:
    repo = ChatMessageRepository(mock_session)
    meta = {"tokens": 42, "model": "gpt-4"}

    result = await repo.create(
        session_id=uuid4(),
        role="assistant",
        content="Sure!",
        metadata=meta,
    )

    assert result.metadata_ == meta


async def test_create_none_metadata_defaults_to_empty_dict(mock_session: AsyncMock) -> None:
    repo = ChatMessageRepository(mock_session)
    result = await repo.create(
        session_id=uuid4(),
        role="assistant",
        content="OK",
        metadata=None,
    )
    assert result.metadata_ == {}


async def test_create_assistant_role(mock_session: AsyncMock) -> None:
    repo = ChatMessageRepository(mock_session)
    result = await repo.create(session_id=uuid4(), role="assistant", content="Response")
    assert result.role == "assistant"


# ── get_by_id ──────────────────────────────────────────────────────────────


async def test_get_by_id_returns_message(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    row = _make_message()
    mock_session.execute.return_value = make_execute_result(scalar=row)  # type: ignore[operator]
    repo = ChatMessageRepository(mock_session)

    result = await repo.get_by_id(row.id)  # type: ignore[arg-type]

    assert result is row


async def test_get_by_id_returns_none_when_missing(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = ChatMessageRepository(mock_session)

    assert await repo.get_by_id(uuid4()) is None


# ── update ─────────────────────────────────────────────────────────────────


async def test_update_metadata(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    row = _make_message(metadata_={})
    mock_session.execute.return_value = make_execute_result(scalar=row)  # type: ignore[operator]
    repo = ChatMessageRepository(mock_session)

    new_meta = {"tokens": 100}
    updated = await repo.update(row.id, {"metadata_": new_meta})  # type: ignore[arg-type]

    assert updated.metadata_ == new_meta
    mock_session.flush.assert_awaited_once()


async def test_update_raises_not_found(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = ChatMessageRepository(mock_session)

    with pytest.raises(RecordNotFoundError) as exc_info:
        await repo.update(uuid4(), {"metadata_": {}})

    assert "ChatMessage" in str(exc_info.value)


async def test_update_raises_for_immutable_field(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    row = _make_message()
    mock_session.execute.return_value = make_execute_result(scalar=row)  # type: ignore[operator]
    repo = ChatMessageRepository(mock_session)

    with pytest.raises(InvalidUpdateFieldError) as exc_info:
        await repo.update(row.id, {"content": "tampered"})  # type: ignore[arg-type]

    assert "content" in str(exc_info.value)


async def test_update_does_not_flush_on_not_found(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = ChatMessageRepository(mock_session)

    with pytest.raises(RecordNotFoundError):
        await repo.update(uuid4(), {"metadata_": {}})

    mock_session.flush.assert_not_awaited()


# ── list_by_session ────────────────────────────────────────────────────────


async def test_list_by_session_returns_ordered_messages(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    session_id = uuid4()
    msgs = [_make_message(session_id=session_id) for _ in range(3)]
    mock_session.execute.return_value = make_execute_result(scalars=msgs)  # type: ignore[operator]
    repo = ChatMessageRepository(mock_session)

    result = await repo.list_by_session(session_id)

    assert result == msgs
    mock_session.execute.assert_awaited_once()


async def test_list_by_session_returns_empty_list_when_none(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalars=[])  # type: ignore[operator]
    repo = ChatMessageRepository(mock_session)

    result = await repo.list_by_session(uuid4())

    assert result == []
