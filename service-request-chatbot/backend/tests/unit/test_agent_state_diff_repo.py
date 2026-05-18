"""Unit tests for StateDiffRepository."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from app.db.models import AgentStateDiff
from app.observability.repositories.state_diff_repo import StateDiffRepository


# ── helpers ────────────────────────────────────────────────────────────────


def _make_diff(**kwargs: object) -> AgentStateDiff:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "trace_id": uuid4(),
        "run_id": uuid4(),
        "diff": {"workflow_stage": {"before": "collect_fields", "after": "validate"}},
    }
    defaults.update(kwargs)
    return AgentStateDiff(**defaults)  # type: ignore[arg-type]


# ── create ─────────────────────────────────────────────────────────────────


async def test_create_returns_state_diff(mock_session: AsyncMock) -> None:
    trace_id = uuid4()
    run_id = uuid4()
    diff_payload = {"field": {"before": "a", "after": "b"}}
    repo = StateDiffRepository(mock_session)

    result = await repo.create(
        trace_id=trace_id,
        run_id=run_id,
        diff=diff_payload,
    )

    assert isinstance(result, AgentStateDiff)
    assert result.trace_id == trace_id
    assert result.run_id == run_id
    mock_session.add.assert_called_once_with(result)
    mock_session.flush.assert_awaited_once()


async def test_create_id_is_assigned(mock_session: AsyncMock) -> None:
    repo = StateDiffRepository(mock_session)
    result = await repo.create(trace_id=uuid4(), run_id=uuid4(), diff={})
    assert result.id is not None


async def test_create_sanitises_diff(mock_session: AsyncMock) -> None:
    """Sensitive keys in diff must be redacted before storage."""
    repo = StateDiffRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        run_id=uuid4(),
        diff={"service_category": "Lease", "password": "hunter2"},
    )

    assert result.diff["password"] == "[REDACTED]"
    assert result.diff["service_category"] == "Lease"


async def test_create_strips_cot_from_diff(mock_session: AsyncMock) -> None:
    repo = StateDiffRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        run_id=uuid4(),
        diff={"field": "value", "chain_of_thought": "private"},
    )

    assert "chain_of_thought" not in result.diff


# ── list operations ────────────────────────────────────────────────────────


async def test_list_for_trace_returns_list(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    rows = [_make_diff(), _make_diff()]
    mock_session.execute.return_value = make_execute_result(scalars=rows)  # type: ignore[operator]
    repo = StateDiffRepository(mock_session)

    result = await repo.list_for_trace(uuid4())

    assert result == rows
    mock_session.execute.assert_awaited_once()


async def test_list_for_run_returns_list(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    rows = [_make_diff()]
    mock_session.execute.return_value = make_execute_result(scalars=rows)  # type: ignore[operator]
    repo = StateDiffRepository(mock_session)

    result = await repo.list_for_run(uuid4())

    assert result == rows
    mock_session.execute.assert_awaited_once()


async def test_list_for_trace_empty(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalars=[])  # type: ignore[operator]
    repo = StateDiffRepository(mock_session)

    result = await repo.list_for_trace(uuid4())

    assert result == []
