"""Unit tests for TraceRepository."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.db.exceptions import RecordNotFoundError
from app.db.models import AgentTrace
from app.observability.repositories.trace_repo import TraceRepository


# ── helpers ────────────────────────────────────────────────────────────────


def _make_trace(**kwargs: object) -> AgentTrace:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "session_id": uuid4(),
        "user_id": uuid4(),
        "trace_type": "CHAT_TURN",
        "status": "IN_PROGRESS",
        "active_agent": None,
        "intent": None,
        "service_category": None,
        "sub_category": None,
        "workflow_stage_before": None,
        "workflow_stage_after": None,
        "input_message": None,
        "output_message": None,
        "error_message": None,
        "total_latency_ms": None,
        "total_token_count": None,
        "estimated_cost": None,
        "metadata_": {},
        "completed_at": None,
    }
    defaults.update(kwargs)
    return AgentTrace(**defaults)  # type: ignore[arg-type]


# ── create ─────────────────────────────────────────────────────────────────


async def test_create_returns_agent_trace(mock_session: AsyncMock) -> None:
    session_id = uuid4()
    user_id = uuid4()
    repo = TraceRepository(mock_session)

    result = await repo.create(
        session_id=session_id,
        user_id=user_id,
        status="IN_PROGRESS",
    )

    assert isinstance(result, AgentTrace)
    assert result.session_id == session_id
    assert result.user_id == user_id
    assert result.trace_type == "CHAT_TURN"
    assert result.status == "IN_PROGRESS"
    mock_session.add.assert_called_once_with(result)
    mock_session.flush.assert_awaited_once()


async def test_create_with_all_fields(mock_session: AsyncMock) -> None:
    repo = TraceRepository(mock_session)

    result = await repo.create(
        session_id=uuid4(),
        user_id=uuid4(),
        trace_type="CHAT_TURN",
        status="IN_PROGRESS",
        active_agent="supervisor",
        intent="lease_issue",
        service_category="Lease",
        sub_category="Payment",
        workflow_stage_before="collect_fields",
        input_message="Hello",
        metadata={"source": "web"},
    )

    assert result.active_agent == "supervisor"
    assert result.intent == "lease_issue"
    assert result.service_category == "Lease"
    assert result.sub_category == "Payment"
    assert result.workflow_stage_before == "collect_fields"
    assert result.input_message == "Hello"
    assert result.metadata_ == {"source": "web"}


async def test_create_id_is_assigned(mock_session: AsyncMock) -> None:
    repo = TraceRepository(mock_session)
    result = await repo.create(session_id=uuid4(), user_id=uuid4(), status="IN_PROGRESS")
    assert result.id is not None


# ── get ────────────────────────────────────────────────────────────────────


async def test_get_returns_trace(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    row = _make_trace()
    mock_session.execute.return_value = make_execute_result(scalar=row)  # type: ignore[operator]
    repo = TraceRepository(mock_session)

    result = await repo.get(row.id)  # type: ignore[arg-type]

    assert result is row
    mock_session.execute.assert_awaited_once()


async def test_get_returns_none_when_missing(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = TraceRepository(mock_session)

    result = await repo.get(uuid4())

    assert result is None


# ── update ─────────────────────────────────────────────────────────────────


async def test_update_applies_changes(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    row = _make_trace(status="IN_PROGRESS", active_agent=None)
    mock_session.execute.return_value = make_execute_result(scalar=row)  # type: ignore[operator]
    repo = TraceRepository(mock_session)

    updated = await repo.update(
        row.id,  # type: ignore[arg-type]
        {"status": "COMPLETED", "active_agent": "extraction_agent"},
    )

    assert updated.status == "COMPLETED"
    assert updated.active_agent == "extraction_agent"
    mock_session.flush.assert_awaited_once()


async def test_update_raises_not_found(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = TraceRepository(mock_session)

    with pytest.raises(RecordNotFoundError) as exc_info:
        await repo.update(uuid4(), {"status": "COMPLETED"})

    assert "AgentTrace" in str(exc_info.value)


async def test_update_does_not_flush_on_not_found(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = TraceRepository(mock_session)

    with pytest.raises(RecordNotFoundError):
        await repo.update(uuid4(), {"status": "COMPLETED"})

    mock_session.flush.assert_not_awaited()


# ── complete ───────────────────────────────────────────────────────────────


async def test_complete_sets_status_and_completed_at(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    row = _make_trace(status="IN_PROGRESS")
    mock_session.execute.return_value = make_execute_result(scalar=row)  # type: ignore[operator]
    repo = TraceRepository(mock_session)

    updated = await repo.complete(
        row.id,  # type: ignore[arg-type]
        status="COMPLETED",
        output_message="Done",
        total_latency_ms=1200,
        total_token_count=500,
        estimated_cost=Decimal("0.001234"),
    )

    assert updated.status == "COMPLETED"
    assert updated.output_message == "Done"
    assert updated.total_latency_ms == 1200
    assert updated.total_token_count == 500
    assert updated.estimated_cost == Decimal("0.001234")
    assert isinstance(updated.completed_at, datetime)
    mock_session.flush.assert_awaited_once()


async def test_complete_raises_not_found(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = TraceRepository(mock_session)

    with pytest.raises(RecordNotFoundError):
        await repo.complete(uuid4(), status="COMPLETED")


async def test_complete_sets_workflow_stage_after(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    row = _make_trace()
    mock_session.execute.return_value = make_execute_result(scalar=row)  # type: ignore[operator]
    repo = TraceRepository(mock_session)

    updated = await repo.complete(
        row.id,  # type: ignore[arg-type]
        status="COMPLETED",
        workflow_stage_after="submit",
    )

    assert updated.workflow_stage_after == "submit"


# ── list operations ────────────────────────────────────────────────────────


async def test_list_by_session_returns_list(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    rows = [_make_trace(), _make_trace()]
    mock_session.execute.return_value = make_execute_result(scalars=rows)  # type: ignore[operator]
    repo = TraceRepository(mock_session)

    result = await repo.list_by_session(uuid4())

    assert result == rows
    mock_session.execute.assert_awaited_once()


async def test_list_by_user_returns_list(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    rows = [_make_trace(), _make_trace(), _make_trace()]
    mock_session.execute.return_value = make_execute_result(scalars=rows)  # type: ignore[operator]
    repo = TraceRepository(mock_session)

    result = await repo.list_by_user(uuid4())

    assert len(result) == 3
    mock_session.execute.assert_awaited_once()
