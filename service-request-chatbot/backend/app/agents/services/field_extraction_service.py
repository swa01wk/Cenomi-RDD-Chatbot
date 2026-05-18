"""LLM-backed field extraction service for the Handover workflow.

``FieldExtractionService`` is the single point responsible for:
- Calling the LLM via ``LLMGateway`` with the extraction prompt.
- Parsing and validating the response as ``HandoverExtractedFields``.
  The Pydantic model's validator automatically strips any backend-only or
  unknown fields before the caller ever sees the result.
- Retrying on transient parse failures (up to ``MAX_RETRIES``).
- Returning rich trace metadata so the node can emit an LLM call record
  without duplicating the retry / token-counting logic.

This service never raises — on total failure it returns an empty
``HandoverExtractedFields`` with ``parse_success=False`` in the meta.
"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog
from pydantic import ValidationError

from app.agents.llm.gateway import LLMGateway, get_default_gateway
from app.agents.prompts.handover_extraction_prompt import HANDOVER_EXTRACTION_SYSTEM_PROMPT
from app.agents.schemas.handover_schema import ExtractionTraceMeta, HandoverExtractedFields

log = structlog.get_logger(__name__)


class FieldExtractionService:
    """Extract handover fields from a user message via the LLM.

    Parameters
    ----------
    gateway:
        Optional ``LLMGateway`` override.  Defaults to the process-level
        singleton so production code requires no explicit wiring; tests inject
        a mock via this parameter.
    """

    MAX_RETRIES: int = 2

    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self._gateway = gateway

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def extract(
        self,
        user_message: str,
        workflow_stage: str | None = None,
        recent_history: list[dict[str, str]] | None = None,
        missing_fields: list[str] | None = None,
    ) -> tuple[HandoverExtractedFields, ExtractionTraceMeta]:
        """Extract candidate field values from *user_message*.

        Parameters
        ----------
        user_message:
            The raw text the user typed.
        workflow_stage:
            Optional current workflow stage (e.g. ``"CREATE_SR"``).
        recent_history:
            Optional list of the last few conversation turns in
            ``{"role": "user"|"assistant", "content": "..."}`` format, oldest
            first.  When provided, the most recent assistant message is
            prepended to the extraction context so the LLM knows what question
            the user is answering — critical for bare values like "2026-06-03"
            or "FM Manager" to be mapped to the correct field.
        missing_fields:
            Optional list of field names that are still outstanding.  When
            provided, the first entry (the field just asked about) is included
            as a strong hint so the LLM maps the user's response to the right
            field even when the message content is ambiguous.

        Returns
        -------
        tuple[HandoverExtractedFields, ExtractionTraceMeta]
            Always a 2-tuple.  On total failure the fields dict is empty and
            ``meta.parse_success`` is ``False``.
        """
        gateway = self._gateway or get_default_gateway()
        user_content = self._build_user_content(user_message, workflow_stage, recent_history, missing_fields)

        meta = ExtractionTraceMeta()
        result: HandoverExtractedFields | None = None
        wall_start = time.monotonic()

        for attempt in range(self.MAX_RETRIES + 1):
            meta.retry_count = attempt
            try:
                raw, input_tokens, output_tokens, latency_ms = await gateway.complete_json(
                    system_prompt=HANDOVER_EXTRACTION_SYSTEM_PROMPT,
                    user_message=user_content,
                )
                meta.input_tokens = input_tokens
                meta.output_tokens = output_tokens
                meta.latency_ms = latency_ms
                meta.raw_output = raw

                result = HandoverExtractedFields.model_validate(raw)
                meta.parse_success = True
                meta.parse_error = None
                log.info(
                    "field_extraction.success",
                    attempt=attempt,
                    fields_extracted=list(result.fields.keys()),
                    summary=result.summary,
                )
                break

            except json.JSONDecodeError as exc:
                meta.parse_error = f"JSONDecodeError: {exc}"
                log.warning(
                    "field_extraction.json_parse_failed",
                    attempt=attempt,
                    error=meta.parse_error,
                )
            except ValidationError as exc:
                meta.parse_error = f"ValidationError: {exc}"
                log.warning(
                    "field_extraction.validation_failed",
                    attempt=attempt,
                    error=meta.parse_error,
                )
            except Exception as exc:
                meta.parse_error = str(exc)
                log.exception(
                    "field_extraction.llm_call_failed",
                    attempt=attempt,
                    error=meta.parse_error,
                )
                # Non-parse errors (network, API quota) are not worth retrying.
                break

        if result is None:
            meta.latency_ms = meta.latency_ms or int((time.monotonic() - wall_start) * 1000)
            result = HandoverExtractedFields()

        return result, meta

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_user_content(
        user_message: str,
        workflow_stage: str | None,
        recent_history: list[dict[str, str]] | None = None,
        missing_fields: list[str] | None = None,
    ) -> str:
        """Build the user-side content string for the LLM call.

        When *recent_history* is provided its last assistant message is
        included so the extraction LLM knows which field was being asked
        about, enabling correct mapping of bare answers such as "2026-06-03"
        to ``startDate`` vs ``endDate``.

        When *missing_fields* is provided the first outstanding field is
        included as an explicit hint for the LLM.
        """
        parts: list[str] = []

        # Include the last bot question as conversation context when available.
        if recent_history:
            last_assistant = next(
                (
                    m["content"]
                    for m in reversed(recent_history)
                    if m.get("role") == "assistant"
                ),
                None,
            )
            if last_assistant:
                parts.append(f"Previous assistant question: {last_assistant}")

        # Provide an explicit hint about the field being collected.
        if missing_fields:
            parts.append(f"Field currently being collected: {missing_fields[0]}")

        if workflow_stage:
            parts.append(f"Current workflow stage: {workflow_stage}")

        parts.append(f"User message: {user_message}")
        return "\n".join(parts)
