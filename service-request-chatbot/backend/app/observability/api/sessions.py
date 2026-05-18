"""Observability session replay API.

Endpoint
--------
GET /observability/sessions/{session_id}/replay

Returns every trace recorded for the given session, ordered oldest-first,
each enriched with its full set of runs, state captures, diffs, LLM/tool
calls, and feedback.  This gives a complete, deterministic replay of how
the agent behaved across all turns of a conversation.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, status

from app.db.session import DbSession
from app.observability.api.traces import _build_run_tree
from app.observability.repositories.feedback_repo import FeedbackRepository
from app.observability.repositories.llm_call_repo import LLMCallRepository
from app.observability.repositories.run_repo import RunRepository
from app.observability.repositories.state_diff_repo import StateDiffRepository
from app.observability.repositories.state_snapshot_repo import StateSnapshotRepository
from app.observability.repositories.tool_call_repo import ToolCallRepository
from app.observability.repositories.trace_repo import TraceRepository
from app.observability.schemas.api_models import (
    FeedbackResponse,
    LLMCallResponse,
    ReplayTraceEntry,
    RunResponse,
    SessionReplayResponse,
    StateDiffResponse,
    StateSnapshotResponse,
    ToolCallResponse,
    TraceResponse,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/observability")


@router.get(
    "/sessions/{session_id}/replay",
    response_model=SessionReplayResponse,
    summary="Full session replay — all traces ordered oldest-first",
)
async def get_session_replay(
    session_id: UUID,
    db: DbSession,
) -> SessionReplayResponse:
    """Return a deterministic, ordered replay of all agent turns in a session.

    Traces are returned oldest-first.  Each entry includes the complete
    run tree, state timeline, tool calls, LLM calls, and any feedback
    submitted against that turn.

    Returns 404 if the session has no recorded traces.
    """
    trace_repo = TraceRepository(db)
    traces_orm = await trace_repo.list_by_session(session_id, limit=500)

    if not traces_orm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No traces found for session {session_id}",
        )

    # list_by_session returns most-recent first — reverse for replay order
    traces_orm = list(reversed(traces_orm))

    run_repo = RunRepository(db)
    snapshot_repo = StateSnapshotRepository(db)
    diff_repo = StateDiffRepository(db)
    llm_repo = LLMCallRepository(db)
    tool_repo = ToolCallRepository(db)
    feedback_repo = FeedbackRepository(db)

    entries: list[ReplayTraceEntry] = []
    for trace in traces_orm:
        runs_orm = await run_repo.list_for_trace(trace.id)
        snapshots_orm = await snapshot_repo.list_for_trace(trace.id)
        diffs_orm = await diff_repo.list_for_trace(trace.id)
        llm_calls_orm = await llm_repo.list_for_trace(trace.id)
        tool_calls_orm = await tool_repo.list_for_trace(trace.id)
        feedback_orm = await feedback_repo.list_for_trace(trace.id)

        runs = [RunResponse.model_validate(r) for r in runs_orm]
        run_tree = _build_run_tree(runs_orm)

        entries.append(
            ReplayTraceEntry(
                trace=TraceResponse.model_validate(trace),
                runs=runs,
                run_tree=run_tree,
                state_snapshots=[StateSnapshotResponse.model_validate(s) for s in snapshots_orm],
                state_diffs=[StateDiffResponse.model_validate(d) for d in diffs_orm],
                llm_calls=[LLMCallResponse.model_validate(c) for c in llm_calls_orm],
                tool_calls=[ToolCallResponse.model_validate(t) for t in tool_calls_orm],
                feedback=[FeedbackResponse.model_validate(f) for f in feedback_orm],
            )
        )

    log.debug(
        "observability.session_replay",
        session_id=str(session_id),
        trace_count=len(entries),
    )

    return SessionReplayResponse(
        session_id=session_id,
        trace_count=len(entries),
        traces=entries,
    )
