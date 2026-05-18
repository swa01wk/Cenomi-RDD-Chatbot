"""Unit tests for StateSnapshotRepository."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from app.db.models import AgentStateSnapshot
from app.observability.repositories.state_snapshot_repo import StateSnapshotRepository


# ── helpers ────────────────────────────────────────────────────────────────


def _make_snapshot(**kwargs: object) -> AgentStateSnapshot:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "trace_id": uuid4(),
        "run_id": uuid4(),
        "snapshot_type": "BEFORE_NODE",
        "state": {"workflow_stage": "collect_fields"},
    }
    defaults.update(kwargs)
    return AgentStateSnapshot(**defaults)  # type: ignore[arg-type]


# ── create ─────────────────────────────────────────────────────────────────


async def test_create_returns_snapshot(mock_session: AsyncMock) -> None:
    trace_id = uuid4()
    run_id = uuid4()
    repo = StateSnapshotRepository(mock_session)

    result = await repo.create(
        trace_id=trace_id,
        run_id=run_id,
        snapshot_type="BEFORE_NODE",
        state={"workflow_stage": "collect_fields"},
    )

    assert isinstance(result, AgentStateSnapshot)
    assert result.trace_id == trace_id
    assert result.run_id == run_id
    assert result.snapshot_type == "BEFORE_NODE"
    mock_session.add.assert_called_once_with(result)
    mock_session.flush.assert_awaited_once()


async def test_create_all_snapshot_types(mock_session: AsyncMock) -> None:
    repo = StateSnapshotRepository(mock_session)
    for snap_type in ("BEFORE_NODE", "AFTER_NODE", "BEFORE_TRACE", "AFTER_TRACE"):
        mock_session.add.reset_mock()
        mock_session.flush.reset_mock()
        result = await repo.create(
            trace_id=uuid4(),
            run_id=uuid4(),
            snapshot_type=snap_type,
            state={"stage": "test"},
        )
        assert result.snapshot_type == snap_type


async def test_create_sanitises_state(mock_session: AsyncMock) -> None:
    """Sensitive keys in state must be redacted before storage."""
    repo = StateSnapshotRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        run_id=uuid4(),
        snapshot_type="AFTER_NODE",
        state={"lease_id": "L123", "api_secret": "abc"},
    )

    assert result.state["api_secret"] == "[REDACTED]"
    assert result.state["lease_id"] == "L123"


async def test_create_strips_cot_from_state(mock_session: AsyncMock) -> None:
    """Chain-of-thought keys must be stripped from state before storage."""
    repo = StateSnapshotRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        run_id=uuid4(),
        snapshot_type="AFTER_NODE",
        state={"stage": "done", "thinking": "I figured out..."},
    )

    assert "thinking" not in result.state
    assert result.state["stage"] == "done"


# ── list operations ────────────────────────────────────────────────────────


async def test_list_for_trace_returns_list(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    rows = [_make_snapshot(), _make_snapshot()]
    mock_session.execute.return_value = make_execute_result(scalars=rows)  # type: ignore[operator]
    repo = StateSnapshotRepository(mock_session)

    result = await repo.list_for_trace(uuid4())

    assert result == rows
    mock_session.execute.assert_awaited_once()


async def test_list_for_run_returns_list(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    rows = [_make_snapshot()]
    mock_session.execute.return_value = make_execute_result(scalars=rows)  # type: ignore[operator]
    repo = StateSnapshotRepository(mock_session)

    result = await repo.list_for_run(uuid4())

    assert result == rows
    mock_session.execute.assert_awaited_once()
