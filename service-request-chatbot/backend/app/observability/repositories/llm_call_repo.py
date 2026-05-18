"""AgentLLMCall repository.

Records individual LLM API calls with full token and cost accounting.
Hidden chain-of-thought and sensitive fields are stripped before storage.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentLLMCall
from app.observability.redaction import sanitise

log = structlog.get_logger(__name__)


class LLMCallRepository:
    """Async repository for :class:`~app.db.models.AgentLLMCall`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
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
    ) -> AgentLLMCall:
        """Insert a new LLM call record.

        ``structured_output`` is sanitised (redacted + CoT stripped) before
        storage.  Hidden chain-of-thought fields must never be persisted.
        """
        row = AgentLLMCall(
            id=uuid4(),
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
            structured_output=sanitise(structured_output or {}),
            parse_success=parse_success,
            parse_error=parse_error,
        )
        self._session.add(row)
        await self._session.flush()
        log.debug(
            "agent_llm_call.created",
            llm_call_id=str(row.id),
            trace_id=str(trace_id),
            run_id=str(run_id),
            model=model,
            total_tokens=total_tokens,
            estimated_cost=str(estimated_cost) if estimated_cost is not None else None,
        )
        return row

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def list_for_trace(
        self, trace_id: UUID, *, limit: int = 200
    ) -> list[AgentLLMCall]:
        """Return all LLM calls for *trace_id*, oldest first."""
        result = await self._session.execute(
            select(AgentLLMCall)
            .where(AgentLLMCall.trace_id == trace_id)
            .order_by(AgentLLMCall.created_at)
            .limit(limit)
        )
        return list(result.scalars())

    async def list_for_run(
        self, run_id: UUID, *, limit: int = 50
    ) -> list[AgentLLMCall]:
        """Return all LLM calls for *run_id*, oldest first."""
        result = await self._session.execute(
            select(AgentLLMCall)
            .where(AgentLLMCall.run_id == run_id)
            .order_by(AgentLLMCall.created_at)
            .limit(limit)
        )
        return list(result.scalars())
