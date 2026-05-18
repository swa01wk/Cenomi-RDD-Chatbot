"""Unit tests for FeedbackRepository."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from app.db.models import AgentFeedback
from app.observability.repositories.feedback_repo import FeedbackRepository


# ── helpers ────────────────────────────────────────────────────────────────


def _make_feedback(**kwargs: object) -> AgentFeedback:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "trace_id": uuid4(),
        "run_id": None,
        "user_id": uuid4(),
        "feedback_type": "THUMBS_UP",
        "score": None,
        "label": None,
        "comment": None,
    }
    defaults.update(kwargs)
    return AgentFeedback(**defaults)  # type: ignore[arg-type]


# ── create ─────────────────────────────────────────────────────────────────


async def test_create_returns_feedback(mock_session: AsyncMock) -> None:
    trace_id = uuid4()
    user_id = uuid4()
    repo = FeedbackRepository(mock_session)

    result = await repo.create(
        trace_id=trace_id,
        feedback_type="THUMBS_UP",
        user_id=user_id,
    )

    assert isinstance(result, AgentFeedback)
    assert result.trace_id == trace_id
    assert result.user_id == user_id
    assert result.feedback_type == "THUMBS_UP"
    assert result.run_id is None
    mock_session.add.assert_called_once_with(result)
    mock_session.flush.assert_awaited_once()


async def test_create_with_score_and_comment(mock_session: AsyncMock) -> None:
    repo = FeedbackRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        feedback_type="SCORE",
        score=5,
        label="excellent",
        comment="Very helpful response",
    )

    assert result.score == 5
    assert result.label == "excellent"
    assert result.comment == "Very helpful response"


async def test_create_with_run_id(mock_session: AsyncMock) -> None:
    """Feedback can optionally reference a specific run."""
    run_id = uuid4()
    repo = FeedbackRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        feedback_type="THUMBS_DOWN",
        run_id=run_id,
    )

    assert result.run_id == run_id


async def test_create_without_user_id(mock_session: AsyncMock) -> None:
    """Automated feedback may not have a user_id."""
    repo = FeedbackRepository(mock_session)

    result = await repo.create(
        trace_id=uuid4(),
        feedback_type="AUTOMATED_EVAL",
        score=1,
    )

    assert result.user_id is None
    assert result.score == 1


async def test_create_id_is_assigned(mock_session: AsyncMock) -> None:
    repo = FeedbackRepository(mock_session)
    result = await repo.create(trace_id=uuid4(), feedback_type="THUMBS_UP")
    assert result.id is not None


# ── list operations ────────────────────────────────────────────────────────


async def test_list_for_trace_returns_list(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    rows = [_make_feedback(), _make_feedback()]
    mock_session.execute.return_value = make_execute_result(scalars=rows)  # type: ignore[operator]
    repo = FeedbackRepository(mock_session)

    result = await repo.list_for_trace(uuid4())

    assert result == rows
    mock_session.execute.assert_awaited_once()


async def test_list_for_trace_empty(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalars=[])  # type: ignore[operator]
    repo = FeedbackRepository(mock_session)

    result = await repo.list_for_trace(uuid4())

    assert result == []


async def test_list_for_trace_single(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    rows = [_make_feedback(feedback_type="THUMBS_DOWN", score=-1)]
    mock_session.execute.return_value = make_execute_result(scalars=rows)  # type: ignore[operator]
    repo = FeedbackRepository(mock_session)

    result = await repo.list_for_trace(uuid4())

    assert len(result) == 1
    assert result[0].feedback_type == "THUMBS_DOWN"
