"""Pydantic model for the Supervisor intent-classification output.

``SupervisorDecision`` is returned by the LLM and consumed exclusively by
``supervisor_node``.  Downstream agents and form-field nodes must not import
or depend on this model directly.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class SupervisorDecision(BaseModel):
    """Structured JSON output from the supervisor intent-classification LLM call.

    The model is used only for routing — it must never carry form-field data,
    API credentials, or submission payloads.
    """

    intent: Literal[
        "CREATE_HANDOVER_SERVICE_REQUEST",
        "UPDATE_HANDOVER_SERVICE_REQUEST",
        "APPROVE_HANDOVER_SERVICE_REQUEST",
        "CHECK_SERVICE_REQUEST_STATUS",
        "UNKNOWN",
    ] = Field(description="Classified user intent")

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Classification confidence in [0, 1]; below threshold triggers clarification",
    )

    service_category: Optional[str] = Field(
        default=None,
        description="Top-level service category (e.g. FIT_OUT_AND_HANDOVER)",
    )

    sub_category: Optional[str] = Field(
        default=None,
        description="Sub-category within service_category (e.g. HANDOVER)",
    )

    target_agent: Optional[str] = Field(
        default=None,
        description="Name of the downstream agent that should handle this request",
    )

    reasoning: str = Field(
        description="Brief explanation of the classification decision (logged, not shown to user)",
    )
