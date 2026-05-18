"""Unit tests for LLMCallRepository."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

from app.db.models import AgentLLMCall
from app.observability.repositories.llm_call_repo import LLMCallRepository


# ── helpers ────────────────────────────────────────────────────────────────


def _make_llm_call(**kwargs: object) -> AgentLLMCall:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "trace_id": uuid4(),
        "run_id": uuid4(),
        "provider": "openai",
        "model": "gpt-4o",
        "temperature": Decimal("0.00"),
        "prompt_name": "extraction_prompt",
        "prompt_version": "v1",
        "input_tokens": 200,
        "output_tokens": 150,
        "total_tokens": 350,
        "latency_ms": 900,
        "estimated_cost": Decimal("0.000350"),
        "structured_output": {},
        "parse_success": True,
        "parse_error": None,
    }
    defaults.update(kwargs)
    return AgentLLMCall(**defaults)  # type: ignore[arg-type]


# ── create ─────────────────────────────────────────────────────────────────


async def test_create_returns_llm_call(mock_session: AsyncMock) -> None:
    trace_id = uuid4()
    run_id = uuid4()
    repo = LLMCallRepository(mock_session)

    result = await repo.create(
        trace_id=trace_id,
        run_id=run_id,
        provider="openai",
        model="gpt-4o",
        temperature=Decimal("0.00"),
        prompt_name="extraction_prompt",
        prompt_version="v1",
        input_tokens=200,
        output_tokens=150,
        total_tokens=350,
        latency_ms=900,
        estimated_cost=Decimal("0.000350"),
        parse_success=True,
    )

    assert isinstance(result, AgentLLMCall)
    assert result.trace_id == trace_id
    assert result.run_id == run_id
    assert result.provider == "openai"
    assert result.model == "gpt-4o"
    assert result.total_tokens == 350
    assert result.parse_success is True
    mock_session.add.assert_called_once_with(result)
    mock_session.flush.assert_awaited_once()


async def test_create_minimal_fields(mock_session: AsyncMock) -> None:
    """All optional fields should be accepted as None."""
    repo = LLMCallRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        run_id=uuid4(),
    )

    assert isinstance(result, AgentLLMCall)
    assert result.model is None
    assert result.total_tokens is None
    assert result.estimated_cost is None


async def test_create_sanitises_structured_output(mock_session: AsyncMock) -> None:
    """Sensitive keys in structured_output must be redacted before storage."""
    repo = LLMCallRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        run_id=uuid4(),
        structured_output={"intent": "lease_query", "auth_credential": "secret"},
    )

    assert result.structured_output["auth_credential"] == "[REDACTED]"
    assert result.structured_output["intent"] == "lease_query"


async def test_create_strips_cot_from_structured_output(mock_session: AsyncMock) -> None:
    """Chain-of-thought keys must be stripped from structured_output before storage."""
    repo = LLMCallRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        run_id=uuid4(),
        structured_output={"intent": "maintenance", "chain_of_thought": "Step 1..."},
    )

    assert "chain_of_thought" not in result.structured_output
    assert result.structured_output["intent"] == "maintenance"


async def test_create_with_parse_error(mock_session: AsyncMock) -> None:
    repo = LLMCallRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        run_id=uuid4(),
        model="gpt-4o",
        parse_success=False,
        parse_error="ValidationError: missing field 'intent'",
    )

    assert result.parse_success is False
    assert result.parse_error == "ValidationError: missing field 'intent'"


# ── list operations ────────────────────────────────────────────────────────


async def test_list_for_trace_returns_list(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    rows = [_make_llm_call(), _make_llm_call()]
    mock_session.execute.return_value = make_execute_result(scalars=rows)  # type: ignore[operator]
    repo = LLMCallRepository(mock_session)

    result = await repo.list_for_trace(uuid4())

    assert result == rows
    mock_session.execute.assert_awaited_once()


async def test_list_for_run_returns_list(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    rows = [_make_llm_call()]
    mock_session.execute.return_value = make_execute_result(scalars=rows)  # type: ignore[operator]
    repo = LLMCallRepository(mock_session)

    result = await repo.list_for_run(uuid4())

    assert result == rows
    mock_session.execute.assert_awaited_once()


async def test_list_for_trace_empty(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalars=[])  # type: ignore[operator]
    repo = LLMCallRepository(mock_session)

    result = await repo.list_for_trace(uuid4())

    assert result == []
