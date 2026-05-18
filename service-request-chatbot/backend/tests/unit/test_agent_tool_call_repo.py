"""Unit tests for ToolCallRepository."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from app.db.models import AgentToolCall
from app.observability.repositories.tool_call_repo import ToolCallRepository


# ── helpers ────────────────────────────────────────────────────────────────


def _make_tool_call(**kwargs: object) -> AgentToolCall:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "trace_id": uuid4(),
        "run_id": uuid4(),
        "tool_name": "lookup_lease",
        "tool_type": "LEASE_LOOKUP",
        "request_payload": {},
        "response_payload": {},
        "status_code": 200,
        "success": True,
        "latency_ms": 80,
        "error_message": None,
    }
    defaults.update(kwargs)
    return AgentToolCall(**defaults)  # type: ignore[arg-type]


# ── create ─────────────────────────────────────────────────────────────────


async def test_create_returns_tool_call(mock_session: AsyncMock) -> None:
    trace_id = uuid4()
    run_id = uuid4()
    repo = ToolCallRepository(mock_session)

    result = await repo.create(
        trace_id=trace_id,
        run_id=run_id,
        tool_name="lookup_lease",
        tool_type="LEASE_LOOKUP",
        request_payload={"lease_id": "L001"},
        response_payload={"status": "active"},
        status_code=200,
        success=True,
        latency_ms=80,
    )

    assert isinstance(result, AgentToolCall)
    assert result.trace_id == trace_id
    assert result.run_id == run_id
    assert result.tool_name == "lookup_lease"
    assert result.tool_type == "LEASE_LOOKUP"
    assert result.status_code == 200
    assert result.success is True
    assert result.latency_ms == 80
    mock_session.add.assert_called_once_with(result)
    mock_session.flush.assert_awaited_once()


async def test_create_all_tool_types(mock_session: AsyncMock) -> None:
    repo = ToolCallRepository(mock_session)
    for tool_type in (
        "LEASE_LOOKUP",
        "DOCUMENT_UPLOAD",
        "SERVICE_REQUEST_CREATE",
        "SERVICE_REQUEST_PATCH",
        "PERMISSION_CHECK",
    ):
        mock_session.add.reset_mock()
        mock_session.flush.reset_mock()
        result = await repo.create(
            trace_id=uuid4(),
            run_id=uuid4(),
            tool_name="test_tool",
            tool_type=tool_type,
        )
        assert result.tool_type == tool_type


async def test_create_with_failed_call(mock_session: AsyncMock) -> None:
    repo = ToolCallRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        run_id=uuid4(),
        tool_name="lookup_lease",
        tool_type="LEASE_LOOKUP",
        status_code=404,
        success=False,
        error_message="Lease not found",
    )

    assert result.success is False
    assert result.status_code == 404
    assert result.error_message == "Lease not found"


async def test_create_sanitises_request_payload(mock_session: AsyncMock) -> None:
    """Sensitive keys in request payload must be redacted before storage."""
    repo = ToolCallRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        run_id=uuid4(),
        tool_name="tool",
        tool_type="PERMISSION_CHECK",
        request_payload={"user_id": "u1", "api_token": "tok_secret"},
    )

    assert result.request_payload["api_token"] == "[REDACTED]"
    assert result.request_payload["user_id"] == "u1"


async def test_create_sanitises_response_payload(mock_session: AsyncMock) -> None:
    """Sensitive keys in response payload must be redacted before storage."""
    repo = ToolCallRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        run_id=uuid4(),
        tool_name="tool",
        tool_type="SERVICE_REQUEST_CREATE",
        response_payload={"sr_id": "SR001", "secret_key": "xyz"},
    )

    assert result.response_payload["secret_key"] == "[REDACTED]"
    assert result.response_payload["sr_id"] == "SR001"


# ── list operations ────────────────────────────────────────────────────────


async def test_list_for_trace_returns_list(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    rows = [_make_tool_call(), _make_tool_call()]
    mock_session.execute.return_value = make_execute_result(scalars=rows)  # type: ignore[operator]
    repo = ToolCallRepository(mock_session)

    result = await repo.list_for_trace(uuid4())

    assert result == rows
    mock_session.execute.assert_awaited_once()


async def test_list_for_run_returns_list(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    rows = [_make_tool_call()]
    mock_session.execute.return_value = make_execute_result(scalars=rows)  # type: ignore[operator]
    repo = ToolCallRepository(mock_session)

    result = await repo.list_for_run(uuid4())

    assert result == rows
    mock_session.execute.assert_awaited_once()
