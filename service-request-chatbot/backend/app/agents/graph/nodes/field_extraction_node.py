"""Field extraction node — calls FieldExtractionService and stores results in state.

Responsibilities
----------------
- Read ``user_message`` and ``workflow_stage`` from the graph state.
- Delegate extraction to ``FieldExtractionService`` (LLM call + retry logic).
- Emit a child LLM run span and an LLM call record via ``TraceManager`` so
  every extraction attempt is fully observable.
- Write ``extracted_fields`` to state as ``{field: {value, confidence}}``.

Non-responsibilities (enforced)
--------------------------------
- MUST NOT merge extracted fields into ``collected_data``.  That is the
  exclusive job of ``merge_state_node``.
- MUST NOT validate business rules or check required fields.
- MUST NOT perform lease / backend lookups.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from app.agents.graph.state import ServiceRequestState
from app.agents.llm.gateway import get_default_gateway
from app.agents.services.field_extraction_service import FieldExtractionService
from app.observability.decorators import trace_node

log = structlog.get_logger(__name__)


def _extract_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (ValueError, AttributeError):
        return None


@trace_node("field_extraction", "AGENT")
async def field_extraction_node(state: ServiceRequestState) -> dict[str, Any]:
    """LangGraph node: extract handover fields from the user message.

    The ``@trace_node`` decorator handles the outer node-level run span
    (BEFORE_NODE / AFTER_NODE snapshots + SUCCESS/FAILED finish).  This
    function additionally opens a child ``LLM`` run span for the LLM call
    itself so token counts, latency, and retry metadata are captured
    separately from the node span.
    """
    user_message: str = state.get("user_message") or ""
    workflow_stage: str | None = state.get("workflow_stage")
    conversation_history: list[dict] = state.get("conversation_history") or []  # type: ignore[assignment]
    missing_fields: list[str] = state.get("missing_fields") or []  # type: ignore[assignment]

    # Resolve trace plumbing injected by TraceManager / lifespan.
    tm = state.get("trace_manager")
    trace_id: UUID | None = _extract_uuid(state.get("trace_id"))

    # ── 1. Open child LLM-call run span ───────────────────────────────────
    # ``_trace_node_run_id`` is injected by the ``@trace_node`` decorator
    # so the LLM span is nested under the field_extraction node span.
    node_run_id: UUID | None = _extract_uuid(state.get("_trace_node_run_id"))
    llm_run_id: UUID | None = None
    if tm is not None and trace_id is not None:
        try:
            llm_run_id = await tm.start_run(
                trace_id=trace_id,
                run_name="field_extraction_llm_call",
                run_type="LLM",
                parent_run_id=node_run_id,
            )
        except Exception:
            log.warning("field_extraction.start_llm_run.failed", exc_info=True)

    # ── 2. Extract fields via service ──────────────────────────────────────
    gateway = get_default_gateway()
    service = FieldExtractionService(gateway=gateway)

    llm_wall_start = time.monotonic()
    result, meta = await service.extract(
        user_message,
        workflow_stage,
        recent_history=conversation_history[-4:] if conversation_history else None,
        missing_fields=missing_fields if missing_fields else None,
    )

    # ── 3. Emit LLM call metadata ──────────────────────────────────────────
    if tm is not None and trace_id is not None and llm_run_id is not None:
        effective_latency = meta.latency_ms or int((time.monotonic() - llm_wall_start) * 1000)
        structured_output: dict[str, Any] = {
            "summary": result.summary,
            "fields": result.to_state_dict(),
            "retry_count": meta.retry_count,
            "parse_success": meta.parse_success,
        }
        try:
            await tm.capture_llm_call(
                trace_id=trace_id,
                run_id=llm_run_id,
                provider="openai",
                model=gateway.model,
                temperature=Decimal("0"),
                prompt_name="handover_extraction_prompt",
                prompt_version="1.0",
                input_tokens=meta.input_tokens or None,
                output_tokens=meta.output_tokens or None,
                total_tokens=(meta.input_tokens + meta.output_tokens) or None,
                latency_ms=effective_latency,
                structured_output=structured_output,
                parse_success=meta.parse_success,
                parse_error=meta.parse_error,
            )
        except Exception:
            log.warning("field_extraction.capture_llm_call.failed", exc_info=True)

        try:
            await tm.finish_run(
                run_id=llm_run_id,
                output=structured_output,
                status="SUCCESS" if meta.parse_success else "FAILED",
                error_message=meta.parse_error,
            )
        except Exception:
            log.warning("field_extraction.finish_llm_run.failed", exc_info=True)

    # ── 4. Handle empty / failed extraction ───────────────────────────────
    if not meta.parse_success:
        log.warning(
            "field_extraction.parse_failed",
            parse_error=meta.parse_error,
            retry_count=meta.retry_count,
        )
        return {"extracted_fields": {}}

    # ── 5. Build state update ──────────────────────────────────────────────
    # Store the full {value, confidence} shape so merge_state_node can apply
    # a confidence threshold at merge time rather than discarding information.
    extracted_fields = result.to_state_dict()

    log.info(
        "field_extraction.complete",
        fields=list(extracted_fields.keys()),
        retry_count=meta.retry_count,
    )

    return {"extracted_fields": extracted_fields}
