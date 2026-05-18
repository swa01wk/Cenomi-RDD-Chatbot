"""Unit tests for RunRepository."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.db.exceptions import RecordNotFoundError
from app.db.models import AgentRun
from app.observability.repositories.run_repo import RunRepository


# ── helpers ────────────────────────────────────────────────────────────────


def _make_run(**kwargs: object) -> AgentRun:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "trace_id": uuid4(),
        "parent_run_id": None,
        "run_name": "supervisor_run",
        "run_type": "SUPERVISOR",
        "node_name": None,
        "input": {},
        "output": {},
        "status": "IN_PROGRESS",
        "error_message": None,
        "latency_ms": None,
        "completed_at": None,
    }
    defaults.update(kwargs)
    return AgentRun(**defaults)  # type: ignore[arg-type]


# ── create ─────────────────────────────────────────────────────────────────


async def test_create_returns_agent_run(mock_session: AsyncMock) -> None:
    trace_id = uuid4()
    repo = RunRepository(mock_session)

    result = await repo.create(
        trace_id=trace_id,
        run_name="supervisor_run",
        run_type="SUPERVISOR",
        status="IN_PROGRESS",
    )

    assert isinstance(result, AgentRun)
    assert result.trace_id == trace_id
    assert result.run_name == "supervisor_run"
    assert result.run_type == "SUPERVISOR"
    assert result.status == "IN_PROGRESS"
    assert result.parent_run_id is None
    mock_session.add.assert_called_once_with(result)
    mock_session.flush.assert_awaited_once()


async def test_create_with_parent_run_id(mock_session: AsyncMock) -> None:
    parent_id = uuid4()
    repo = RunRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        run_name="child_run",
        run_type="LANGGRAPH_NODE",
        status="IN_PROGRESS",
        parent_run_id=parent_id,
        node_name="extract_node",
    )

    assert result.parent_run_id == parent_id
    assert result.node_name == "extract_node"


async def test_create_sanitises_input(mock_session: AsyncMock) -> None:
    """Sensitive keys in input must be redacted before storage."""
    repo = RunRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        run_name="run",
        run_type="AGENT",
        status="IN_PROGRESS",
        input={"user_query": "hello", "api_key": "sk-secret123"},
    )

    assert result.input["api_key"] == "[REDACTED]"
    assert result.input["user_query"] == "hello"


async def test_create_strips_cot_from_input(mock_session: AsyncMock) -> None:
    """Chain-of-thought keys must be stripped from input before storage."""
    repo = RunRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        run_name="run",
        run_type="AGENT",
        status="IN_PROGRESS",
        input={"user_query": "hello", "reasoning": "step 1, step 2"},
    )

    assert "reasoning" not in result.input
    assert result.input["user_query"] == "hello"


# ── get ────────────────────────────────────────────────────────────────────


async def test_get_returns_run(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    row = _make_run()
    mock_session.execute.return_value = make_execute_result(scalar=row)  # type: ignore[operator]
    repo = RunRepository(mock_session)

    result = await repo.get(row.id)  # type: ignore[arg-type]

    assert result is row


async def test_get_returns_none_when_missing(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = RunRepository(mock_session)

    result = await repo.get(uuid4())

    assert result is None


# ── update ─────────────────────────────────────────────────────────────────


async def test_update_applies_changes(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    row = _make_run(status="IN_PROGRESS")
    mock_session.execute.return_value = make_execute_result(scalar=row)  # type: ignore[operator]
    repo = RunRepository(mock_session)

    updated = await repo.update(row.id, {"status": "FAILED", "error_message": "oops"})  # type: ignore[arg-type]

    assert updated.status == "FAILED"
    assert updated.error_message == "oops"
    mock_session.flush.assert_awaited_once()


async def test_update_raises_not_found(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = RunRepository(mock_session)

    with pytest.raises(RecordNotFoundError) as exc_info:
        await repo.update(uuid4(), {"status": "FAILED"})

    assert "AgentRun" in str(exc_info.value)


# ── complete ───────────────────────────────────────────────────────────────


async def test_complete_sets_fields(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    row = _make_run(status="IN_PROGRESS")
    mock_session.execute.return_value = make_execute_result(scalar=row)  # type: ignore[operator]
    repo = RunRepository(mock_session)

    updated = await repo.complete(
        row.id,  # type: ignore[arg-type]
        status="COMPLETED",
        output={"result": "ok"},
        latency_ms=350,
    )

    assert updated.status == "COMPLETED"
    assert updated.latency_ms == 350
    assert isinstance(updated.completed_at, datetime)
    mock_session.flush.assert_awaited_once()


async def test_complete_sanitises_output(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    """Sensitive keys in output must be redacted before storage."""
    row = _make_run()
    mock_session.execute.return_value = make_execute_result(scalar=row)  # type: ignore[operator]
    repo = RunRepository(mock_session)

    await repo.complete(
        row.id,  # type: ignore[arg-type]
        status="COMPLETED",
        output={"result": "ok", "auth_token": "bearer xyz"},
    )

    assert row.output["auth_token"] == "[REDACTED]"
    assert row.output["result"] == "ok"


async def test_complete_strips_cot_from_output(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    """Chain-of-thought keys must be stripped from output before storage."""
    row = _make_run()
    mock_session.execute.return_value = make_execute_result(scalar=row)  # type: ignore[operator]
    repo = RunRepository(mock_session)

    await repo.complete(
        row.id,  # type: ignore[arg-type]
        status="COMPLETED",
        output={"decision": "approve", "chain_of_thought": "I thought..."},
    )

    assert "chain_of_thought" not in row.output
    assert row.output["decision"] == "approve"


async def test_complete_raises_not_found(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = RunRepository(mock_session)

    with pytest.raises(RecordNotFoundError):
        await repo.complete(uuid4(), status="COMPLETED")


# ── list ───────────────────────────────────────────────────────────────────


async def test_list_for_trace_returns_list(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    rows = [_make_run(), _make_run()]
    mock_session.execute.return_value = make_execute_result(scalars=rows)  # type: ignore[operator]
    repo = RunRepository(mock_session)

    result = await repo.list_for_trace(uuid4())

    assert result == rows
    mock_session.execute.assert_awaited_once()
