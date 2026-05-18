"""LangSmith-inspired trace/run lifecycle management.

``TraceManager`` is the single facade that the chatbot graph and decorators
use to record auditable decision traces.  It delegates all persistence to the
existing repository layer and is designed so that **tracing failures never
crash the main chatbot flow** — every public method swallows exceptions and
logs them via structlog.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.repositories.llm_call_repo import LLMCallRepository
from app.observability.repositories.run_repo import RunRepository
from app.observability.repositories.state_diff_repo import StateDiffRepository
from app.observability.repositories.state_snapshot_repo import StateSnapshotRepository
from app.observability.repositories.tool_call_repo import ToolCallRepository
from app.observability.repositories.trace_repo import TraceRepository
from app.observability.serializers import sanitize_state_for_trace
from app.observability.state_diff import build_json_diff

log = structlog.get_logger(__name__)


class TraceManager:
    """Coordinates trace/run lifecycle and delegates persistence to repositories.

    All public methods are async and silently absorb any exception from the
    persistence layer so that tracing failures never propagate to the calling
    node or service.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._trace_repo = TraceRepository(session)
        self._run_repo = RunRepository(session)
        self._snapshot_repo = StateSnapshotRepository(session)
        self._diff_repo = StateDiffRepository(session)
        self._tool_repo = ToolCallRepository(session)
        self._llm_repo = LLMCallRepository(session)

        self._active_trace_id: UUID | None = None
        # Maps run_id → monotonic start time (seconds) for latency computation.
        self._run_start_times: dict[UUID, float] = {}
        # Maps trace_id → monotonic start time for end-to-end trace latency.
        self._trace_start_times: dict[UUID, float] = {}

    # ------------------------------------------------------------------
    # Trace lifecycle
    # ------------------------------------------------------------------

    async def start_trace(
        self,
        session_id: str | UUID,
        user_id: str | UUID,
        input_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> UUID | None:
        """Create a new AgentTrace and return its UUID.

        Returns ``None`` if persistence fails; the caller should treat a
        ``None`` trace_id as a signal that tracing is unavailable for this
        turn.
        """
        try:
            row = await self._trace_repo.create(
                session_id=_to_uuid(session_id),
                user_id=_to_uuid(user_id),
                status="IN_PROGRESS",
                input_message=input_message,
                metadata=metadata or {},
            )
            self._active_trace_id = row.id
            self._trace_start_times[row.id] = time.monotonic()
            log.info("trace.started", trace_id=str(row.id))
            return row.id
        except Exception:
            log.exception("trace_manager.start_trace.failed")
            return None

    async def finish_trace(
        self,
        trace_id: UUID,
        output_message: str,
        final_state: dict[str, Any] | None = None,
        status: str = "SUCCESS",
        active_agent: str | None = None,
        intent: str | None = None,
        service_category: str | None = None,
        sub_category: str | None = None,
        workflow_stage_before: str | None = None,
        workflow_stage_after: str | None = None,
        total_token_count: int | None = None,
        estimated_cost: Decimal | None = None,
    ) -> None:
        """Mark a trace as successfully completed."""
        try:
            start = self._trace_start_times.pop(trace_id, None)
            latency_ms = int((time.monotonic() - start) * 1000) if start is not None else None
            await self._trace_repo.complete(
                trace_id,
                status=status,
                output_message=output_message,
                active_agent=active_agent,
                intent=intent,
                service_category=service_category,
                sub_category=sub_category,
                workflow_stage_before=workflow_stage_before,
                workflow_stage_after=workflow_stage_after,
                total_latency_ms=latency_ms,
                total_token_count=total_token_count,
                estimated_cost=estimated_cost,
            )
            if final_state:
                await self.capture_state_snapshot(
                    trace_id=trace_id,
                    run_id=None,  # type: ignore[arg-type]
                    snapshot_type="AFTER_TRACE",
                    state=final_state,
                )
            log.info(
                "trace.finished",
                trace_id=str(trace_id),
                status=status,
                latency_ms=latency_ms,
            )
        except Exception:
            log.exception("trace_manager.finish_trace.failed", trace_id=str(trace_id))

    async def fail_trace(
        self,
        trace_id: UUID,
        error_message: str,
        final_state: dict[str, Any] | None = None,
        active_agent: str | None = None,
        intent: str | None = None,
        workflow_stage_before: str | None = None,
    ) -> None:
        """Mark a trace as failed with an error message."""
        try:
            start = self._trace_start_times.pop(trace_id, None)
            latency_ms = int((time.monotonic() - start) * 1000) if start is not None else None
            await self._trace_repo.complete(
                trace_id,
                status="FAILED",
                error_message=error_message,
                active_agent=active_agent,
                intent=intent,
                workflow_stage_before=workflow_stage_before,
                total_latency_ms=latency_ms,
            )
            if final_state:
                await self.capture_state_snapshot(
                    trace_id=trace_id,
                    run_id=None,  # type: ignore[arg-type]
                    snapshot_type="AFTER_TRACE",
                    state=final_state,
                )
            log.warning(
                "trace.failed",
                trace_id=str(trace_id),
                error_message=error_message,
                latency_ms=latency_ms,
            )
        except Exception:
            log.exception("trace_manager.fail_trace.failed", trace_id=str(trace_id))

    # ------------------------------------------------------------------
    # Run (span) lifecycle
    # ------------------------------------------------------------------

    async def start_run(
        self,
        trace_id: UUID,
        run_name: str,
        run_type: str,
        parent_run_id: UUID | None = None,
        input: dict[str, Any] | None = None,
    ) -> UUID | None:
        """Create a new AgentRun (span) under *trace_id* and return its UUID."""
        try:
            row = await self._run_repo.create(
                trace_id=trace_id,
                run_name=run_name,
                run_type=run_type,
                status="IN_PROGRESS",
                parent_run_id=parent_run_id,
                node_name=run_name,
                input=input or {},
            )
            self._run_start_times[row.id] = time.monotonic()
            log.debug(
                "run.started",
                run_id=str(row.id),
                trace_id=str(trace_id),
                run_name=run_name,
            )
            return row.id
        except Exception:
            log.exception(
                "trace_manager.start_run.failed",
                trace_id=str(trace_id),
                run_name=run_name,
            )
            return None

    async def finish_run(
        self,
        run_id: UUID,
        output: dict[str, Any] | None = None,
        status: str = "SUCCESS",
        error_message: str | None = None,
    ) -> None:
        """Mark a run as completed."""
        try:
            start = self._run_start_times.pop(run_id, None)
            latency_ms = int((time.monotonic() - start) * 1000) if start is not None else None
            await self._run_repo.complete(
                run_id,
                status=status,
                output=output or {},
                latency_ms=latency_ms,
                error_message=error_message,
            )
            log.debug(
                "run.finished",
                run_id=str(run_id),
                status=status,
                latency_ms=latency_ms,
            )
        except Exception:
            log.exception("trace_manager.finish_run.failed", run_id=str(run_id))

    # ------------------------------------------------------------------
    # State snapshots and diffs
    # ------------------------------------------------------------------

    async def capture_state_snapshot(
        self,
        trace_id: UUID,
        run_id: UUID | None,
        snapshot_type: str,
        state: dict[str, Any],
    ) -> None:
        """Persist a sanitised state snapshot."""
        try:
            sanitized = sanitize_state_for_trace(state)
            if run_id is None:
                log.debug(
                    "state_snapshot.skipped_no_run_id",
                    trace_id=str(trace_id),
                    snapshot_type=snapshot_type,
                )
                return
            await self._snapshot_repo.create(
                trace_id=trace_id,
                run_id=run_id,
                snapshot_type=snapshot_type,
                state=sanitized,
            )
        except Exception:
            log.exception(
                "trace_manager.capture_state_snapshot.failed",
                trace_id=str(trace_id),
                snapshot_type=snapshot_type,
            )

    async def capture_state_diff(
        self,
        trace_id: UUID,
        run_id: UUID,
        before_state: dict[str, Any],
        after_state: dict[str, Any],
    ) -> None:
        """Compute and persist the diff between *before_state* and *after_state*."""
        try:
            diff = build_json_diff(
                sanitize_state_for_trace(before_state),
                sanitize_state_for_trace(after_state),
            )
            await self._diff_repo.create(
                trace_id=trace_id,
                run_id=run_id,
                diff=diff,
            )
        except Exception:
            log.exception(
                "trace_manager.capture_state_diff.failed",
                trace_id=str(trace_id),
                run_id=str(run_id),
            )

    # ------------------------------------------------------------------
    # Tool and LLM call capture
    # ------------------------------------------------------------------

    async def capture_tool_call(
        self,
        trace_id: UUID,
        run_id: UUID,
        tool_name: str,
        tool_type: str,
        request_payload: dict[str, Any] | None = None,
        response_payload: dict[str, Any] | None = None,
        status_code: int | None = None,
        success: bool | None = None,
        latency_ms: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Record a single external tool invocation."""
        try:
            await self._tool_repo.create(
                trace_id=trace_id,
                run_id=run_id,
                tool_name=tool_name,
                tool_type=tool_type,
                request_payload=request_payload,
                response_payload=response_payload,
                status_code=status_code,
                success=success,
                latency_ms=latency_ms,
                error_message=error_message,
            )
        except Exception:
            log.exception(
                "trace_manager.capture_tool_call.failed",
                trace_id=str(trace_id),
                run_id=str(run_id),
                tool_name=tool_name,
            )

    async def capture_llm_call(
        self,
        trace_id: UUID,
        run_id: UUID,
        provider: str | None = None,
        model: str | None = None,
        temperature: Decimal | None = None,
        prompt_name: str | None = None,
        prompt_version: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        latency_ms: int | None = None,
        estimated_cost: Decimal | None = None,
        structured_output: dict[str, Any] | None = None,
        parse_success: bool | None = None,
        parse_error: str | None = None,
    ) -> None:
        """Record a single LLM API call with token and cost accounting."""
        try:
            await self._llm_repo.create(
                trace_id=trace_id,
                run_id=run_id,
                provider=provider,
                model=model,
                temperature=temperature,
                prompt_name=prompt_name,
                prompt_version=prompt_version,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                estimated_cost=estimated_cost,
                structured_output=structured_output,
                parse_success=parse_success,
                parse_error=parse_error,
            )
        except Exception:
            log.exception(
                "trace_manager.capture_llm_call.failed",
                trace_id=str(trace_id),
                run_id=str(run_id),
                model=model,
            )

    # ------------------------------------------------------------------
    # Compatibility helpers
    # ------------------------------------------------------------------

    def current_trace_id(self) -> UUID | None:
        """Return the most recently started trace_id, or ``None``."""
        return self._active_trace_id


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_uuid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))
