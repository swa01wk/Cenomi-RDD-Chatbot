"""Observability feedback API.

Endpoint
--------
POST /observability/traces/{trace_id}/feedback

Allows admin reviewers or automated systems to attach a scored, labelled
feedback signal to any trace.  The ``feedback_type`` field distinguishes
admin reviews, automated evaluations, thumb ratings, etc.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.db.session import DbSession
from app.observability.repositories.feedback_repo import FeedbackRepository
from app.observability.repositories.trace_repo import TraceRepository
from app.observability.schemas.api_models import FeedbackResponse

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/observability")


class FeedbackBody(BaseModel):
    """Request body for submitting feedback on a trace."""

    feedback_type: str = Field(
        description="Feedback category, e.g. ADMIN_REVIEW, THUMB_UP, THUMB_DOWN, AUTOMATED_EVAL"
    )
    score: int | None = Field(
        default=None,
        ge=0,
        le=5,
        description="Optional integer score (0–5)",
    )
    label: str | None = Field(
        default=None,
        description="Optional categorical label, e.g. GOOD_EXTRACTION, WRONG_INTENT",
    )
    comment: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional free-text reviewer comment",
    )


@router.post(
    "/traces/{trace_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit feedback for a trace",
)
async def submit_feedback(
    trace_id: UUID,
    body: FeedbackBody,
    db: DbSession,
) -> FeedbackResponse:
    """Attach a feedback signal to a trace.

    The trace must exist.  ``run_id`` and ``user_id`` are not accepted here
    (admin-level endpoint; the user identity comes from the auth layer, not
    the request body).
    """
    trace_repo = TraceRepository(db)
    trace = await trace_repo.get(trace_id)
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace {trace_id} not found",
        )

    feedback_repo = FeedbackRepository(db)
    row = await feedback_repo.create(
        trace_id=trace_id,
        feedback_type=body.feedback_type,
        score=body.score,
        label=body.label,
        comment=body.comment,
    )

    log.info(
        "observability.feedback_submitted",
        trace_id=str(trace_id),
        feedback_type=body.feedback_type,
        score=body.score,
        label=body.label,
    )

    return FeedbackResponse.model_validate(row)
