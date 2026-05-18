"""Observability trace API — list, detail, and run-tree endpoints.

Endpoints
---------
GET  /observability/traces                     — paginated + filtered trace list
GET  /observability/traces/{trace_id}          — full trace detail with run tree

Security rules enforced at this layer:
- All JSONB payloads (input/output/state/diffs/structured_output) are
  re-sanitised by the Pydantic response models on the way out.
- Hidden system prompts and chain-of-thought are never stored and therefore
  never returned (stripped at write time by repositories).
- Only auditable metadata is exposed; raw ``metadata_`` columns are excluded.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from app.db.models import AgentRun
from app.db.session import DbSession
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
    PaginatedTraceListResponse,
    RunResponse,
    RunTreeNodeResponse,
    StateDiffResponse,
    StateSnapshotResponse,
    ToolCallResponse,
    TraceDetailResponse,
    TraceResponse,
    TraceSummaryResponse,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/observability")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_run_tree(runs: list[AgentRun]) -> list[RunTreeNodeResponse]:
    """Convert a flat, time-ordered list of AgentRun rows into a nested tree.

    Runs without a parent (or whose parent is not in the list) become roots.
    Self-referencing entries are treated as roots to avoid infinite cycles.
    """
    node_map: dict[UUID, RunTreeNodeResponse] = {}
    for run in runs:
        node_map[run.id] = RunTreeNodeResponse(
            id=run.id,
            parent_run_id=run.parent_run_id,
            run_name=run.run_name,
            run_type=run.run_type,
            node_name=run.node_name,
            status=run.status,
            error_message=run.error_message,
            latency_ms=run.latency_ms,
            started_at=run.started_at,
            completed_at=run.completed_at,
        )

    roots: list[RunTreeNodeResponse] = []
    for run in runs:
        node = node_map[run.id]
        parent_id = run.parent_run_id
        if parent_id and parent_id != run.id and parent_id in node_map:
            node_map[parent_id].children.append(node)
        else:
            roots.append(node)
    return roots


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/traces",
    response_model=PaginatedTraceListResponse,
    summary="List traces with optional filters and pagination",
)
async def list_traces(
    db: DbSession,
    status: str | None = Query(default=None, description="Filter by trace status (e.g. SUCCESS, FAILED)"),
    agent: str | None = Query(default=None, description="Filter by active_agent name"),
    intent: str | None = Query(default=None, description="Filter by detected intent"),
    session_id: UUID | None = Query(default=None, description="Filter by chat session UUID"),
    user_id: UUID | None = Query(default=None, description="Filter by user UUID"),
    from_date: datetime | None = Query(default=None, description="Include traces created at or after this ISO-8601 datetime"),
    to_date: datetime | None = Query(default=None, description="Include traces created at or before this ISO-8601 datetime"),
    has_error: bool | None = Query(default=None, description="True → only traces with errors; False → only clean traces"),
    min_latency_ms: int | None = Query(default=None, ge=0, description="Minimum total_latency_ms threshold"),
    page: int = Query(default=1, ge=1, description="1-based page number"),
    page_size: int = Query(default=20, ge=1, le=200, description="Items per page (max 200)"),
) -> PaginatedTraceListResponse:
    repo = TraceRepository(db)
    rows, total = await repo.list_filtered(
        status=status,
        agent=agent,
        intent=intent,
        session_id=session_id,
        user_id=user_id,
        from_date=from_date,
        to_date=to_date,
        has_error=has_error,
        min_latency_ms=min_latency_ms,
        page=page,
        page_size=page_size,
    )
    items = [TraceSummaryResponse.model_validate(row) for row in rows]
    return PaginatedTraceListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_next=(page * page_size) < total,
    )


@router.get(
    "/traces/{trace_id}",
    response_model=TraceDetailResponse,
    summary="Full trace detail: trace + runs + state + LLM/tool calls + feedback",
)
async def get_trace(
    trace_id: UUID,
    db: DbSession,
) -> TraceDetailResponse:
    trace_repo = TraceRepository(db)
    trace = await trace_repo.get(trace_id)
    if trace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Trace {trace_id} not found")

    run_repo = RunRepository(db)
    snapshot_repo = StateSnapshotRepository(db)
    diff_repo = StateDiffRepository(db)
    llm_repo = LLMCallRepository(db)
    tool_repo = ToolCallRepository(db)
    feedback_repo = FeedbackRepository(db)

    runs_orm = await run_repo.list_for_trace(trace_id)
    snapshots_orm = await snapshot_repo.list_for_trace(trace_id)
    diffs_orm = await diff_repo.list_for_trace(trace_id)
    llm_calls_orm = await llm_repo.list_for_trace(trace_id)
    tool_calls_orm = await tool_repo.list_for_trace(trace_id)
    feedback_orm = await feedback_repo.list_for_trace(trace_id)

    runs = [RunResponse.model_validate(r) for r in runs_orm]
    run_tree = _build_run_tree(runs_orm)

    log.debug(
        "observability.get_trace",
        trace_id=str(trace_id),
        runs=len(runs),
        snapshots=len(snapshots_orm),
        diffs=len(diffs_orm),
        llm_calls=len(llm_calls_orm),
        tool_calls=len(tool_calls_orm),
        feedback=len(feedback_orm),
    )

    return TraceDetailResponse(
        trace=TraceResponse.model_validate(trace),
        runs=runs,
        run_tree=run_tree,
        state_snapshots=[StateSnapshotResponse.model_validate(s) for s in snapshots_orm],
        state_diffs=[StateDiffResponse.model_validate(d) for d in diffs_orm],
        llm_calls=[LLMCallResponse.model_validate(c) for c in llm_calls_orm],
        tool_calls=[ToolCallResponse.model_validate(t) for t in tool_calls_orm],
        feedback=[FeedbackResponse.model_validate(f) for f in feedback_orm],
    )
