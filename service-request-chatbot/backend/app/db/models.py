"""SQLAlchemy ORM models — async SQLAlchemy 2.x declarative style.

Domain models
─────────────
  ChatSession                  — one per user conversation
  ChatMessage                  — individual turn within a session
  ServiceRequestDraft          — SR data accumulated during the workflow
  ServiceRequestChatAuditLog   — immutable audit trail for SR actions

Observability models (legacy stubs — do not extend)
─────────────────────────────────────────────────────
  ObservabilityTrace / Run / LLMCall / ToolCall / StateSnapshot / Feedback

Agent observability models (custom internal tracing layer)
───────────────────────────────────────────────────────────
  AgentTrace            — top-level trace for one chat turn / interaction
  AgentRun              — individual run / span within a trace
  AgentStateSnapshot    — full state capture before/after a node
  AgentStateDiff        — delta between successive states
  AgentToolCall         — external tool invocation record
  AgentLLMCall          — LLM API call with token/cost accounting
  AgentFeedback         — explicit user or automated feedback signal
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ─── Domain models ────────────────────────────────────────────────────────────


class ChatSession(Base):
    """Represents one user conversation session."""

    __tablename__ = "chat_sessions"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    active_agent: Mapped[str | None] = mapped_column(Text(), nullable=True)
    intent: Mapped[str | None] = mapped_column(Text(), nullable=True)
    workflow_stage: Mapped[str | None] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(
        Text(), default="IN_PROGRESS", server_default="IN_PROGRESS"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="raise",
        order_by="ChatMessage.created_at",
    )
    drafts: Mapped[list[ServiceRequestDraft]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    audit_logs: Mapped[list[ServiceRequestChatAuditLog]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="raise",
        order_by="ServiceRequestChatAuditLog.created_at",
    )


class ChatMessage(Base):
    """A single turn (user or assistant) within a ChatSession."""

    __tablename__ = "chat_messages"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(Text(), nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    # "metadata" is a reserved attribute on DeclarativeBase; use metadata_ with an
    # explicit column name so the DB column is still called "metadata".
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped[ChatSession] = relationship(back_populates="messages", lazy="raise")


class ServiceRequestDraft(Base):
    """Accumulates service-request data throughout the collection workflow.

    Multiple drafts per session are allowed (one per workflow run), but the
    repository exposes a ``get_by_session`` helper that returns the most recent
    one for the common single-draft case.
    """

    __tablename__ = "service_request_drafts"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    service_category: Mapped[str] = mapped_column(Text(), nullable=False)
    sub_category: Mapped[str] = mapped_column(Text(), nullable=False)
    workflow_stage: Mapped[str] = mapped_column(Text(), nullable=False)
    collected_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    missing_fields: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    documents: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    sr_id: Mapped[str | None] = mapped_column(Text(), nullable=True)
    service_request_status: Mapped[str | None] = mapped_column(Text(), nullable=True)
    ready_to_submit: Mapped[bool] = mapped_column(
        Boolean(), default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session: Mapped[ChatSession] = relationship(back_populates="drafts", lazy="raise")


class ServiceRequestChatAuditLog(Base):
    """Immutable audit trail for service-request actions within a session.

    ``before_state`` / ``after_state`` capture the full JSONB snapshot before
    and after the action for point-in-time reconstruction.
    """

    __tablename__ = "service_request_chat_audit_logs"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(Text(), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped[ChatSession] = relationship(
        back_populates="audit_logs", lazy="raise"
    )


# ─── Observability models (unchanged) ─────────────────────────────────────────


class ObservabilityTrace(Base):
    __tablename__ = "observability_traces"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ObservabilityRun(Base):
    __tablename__ = "observability_runs"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    trace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("observability_traces.id", ondelete="CASCADE"),
        index=True,
    )
    parent_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("observability_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    node_name: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ObservabilityLLMCall(Base):
    __tablename__ = "observability_llm_calls"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("observability_runs.id", ondelete="CASCADE"),
        index=True,
    )
    model: Mapped[str] = mapped_column(String(128))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_request: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    raw_response: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ObservabilityToolCall(Base):
    __tablename__ = "observability_tool_calls"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("observability_runs.id", ondelete="CASCADE"),
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(256))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ObservabilityStateSnapshot(Base):
    __tablename__ = "observability_state_snapshots"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("observability_runs.id", ondelete="CASCADE"),
        index=True,
    )
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    diff_from_previous: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ObservabilityFeedback(Base):
    __tablename__ = "observability_feedback"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    trace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("observability_traces.id", ondelete="CASCADE"),
        index=True,
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text(), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ─── Agent observability models ───────────────────────────────────────────────


class AgentTrace(Base):
    """Top-level trace record for one user interaction / chat turn.

    Stores only auditable decision metadata — no hidden chain-of-thought.
    Payloads are redacted by the repository before persistence.
    """

    __tablename__ = "agent_traces"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    trace_type: Mapped[str] = mapped_column(
        Text(), default="CHAT_TURN", server_default="CHAT_TURN", nullable=False
    )
    active_agent: Mapped[str | None] = mapped_column(Text(), nullable=True, index=True)
    intent: Mapped[str | None] = mapped_column(Text(), nullable=True)
    service_category: Mapped[str | None] = mapped_column(Text(), nullable=True)
    sub_category: Mapped[str | None] = mapped_column(Text(), nullable=True)
    workflow_stage_before: Mapped[str | None] = mapped_column(Text(), nullable=True)
    workflow_stage_after: Mapped[str | None] = mapped_column(Text(), nullable=True)
    input_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    output_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(Text(), nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    total_latency_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    total_token_count: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="trace",
        cascade="all, delete-orphan",
        lazy="raise",
        order_by="AgentRun.started_at",
    )
    state_snapshots: Mapped[list["AgentStateSnapshot"]] = relationship(
        back_populates="trace",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    state_diffs: Mapped[list["AgentStateDiff"]] = relationship(
        back_populates="trace",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    tool_calls: Mapped[list["AgentToolCall"]] = relationship(
        back_populates="trace",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    llm_calls: Mapped[list["AgentLLMCall"]] = relationship(
        back_populates="trace",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    feedback: Mapped[list["AgentFeedback"]] = relationship(
        back_populates="trace",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class AgentRun(Base):
    """A single named span / run within an AgentTrace.

    Supports hierarchical nesting via ``parent_run_id``.  ``run_type`` must be
    one of: SUPERVISOR, AGENT, LANGGRAPH_NODE, LLM_CALL, TOOL_CALL,
    VALIDATION, API_CALL, STATE_UPDATE, RESPONSE_GENERATION.
    """

    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    trace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_traces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    run_name: Mapped[str] = mapped_column(Text(), nullable=False)
    run_type: Mapped[str] = mapped_column(Text(), nullable=False)
    node_name: Mapped[str | None] = mapped_column(Text(), nullable=True)
    input: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    output: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    status: Mapped[str] = mapped_column(Text(), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    trace: Mapped["AgentTrace"] = relationship(back_populates="runs", lazy="raise")
    children: Mapped[list["AgentRun"]] = relationship(
        "AgentRun",
        back_populates="parent",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    parent: Mapped["AgentRun | None"] = relationship(
        "AgentRun",
        back_populates="children",
        remote_side="AgentRun.id",
        lazy="raise",
    )
    state_snapshots: Mapped[list["AgentStateSnapshot"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    state_diffs: Mapped[list["AgentStateDiff"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    tool_calls: Mapped[list["AgentToolCall"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    llm_calls: Mapped[list["AgentLLMCall"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    feedback: Mapped[list["AgentFeedback"]] = relationship(
        back_populates="run",
        lazy="raise",
    )


class AgentStateSnapshot(Base):
    """Full state capture at a specific point in a LangGraph node execution.

    ``snapshot_type`` must be one of: BEFORE_NODE, AFTER_NODE,
    BEFORE_TRACE, AFTER_TRACE.
    """

    __tablename__ = "agent_state_snapshots"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    trace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_traces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    snapshot_type: Mapped[str] = mapped_column(Text(), nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    trace: Mapped["AgentTrace"] = relationship(
        back_populates="state_snapshots", lazy="raise"
    )
    run: Mapped["AgentRun"] = relationship(
        back_populates="state_snapshots", lazy="raise"
    )


class AgentStateDiff(Base):
    """Delta between two successive agent states within a trace."""

    __tablename__ = "agent_state_diffs"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    trace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_traces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    diff: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    trace: Mapped["AgentTrace"] = relationship(
        back_populates="state_diffs", lazy="raise"
    )
    run: Mapped["AgentRun"] = relationship(
        back_populates="state_diffs", lazy="raise"
    )


class AgentToolCall(Base):
    """Record of a single external tool invocation.

    ``tool_type`` must be one of: LEASE_LOOKUP, DOCUMENT_UPLOAD,
    SERVICE_REQUEST_CREATE, SERVICE_REQUEST_PATCH, PERMISSION_CHECK.
    Payloads are redacted by the repository before persistence.
    """

    __tablename__ = "agent_tool_calls"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    trace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_traces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(Text(), nullable=False)
    tool_type: Mapped[str] = mapped_column(Text(), nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    response_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    status_code: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    success: Mapped[bool | None] = mapped_column(Boolean(), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    trace: Mapped["AgentTrace"] = relationship(
        back_populates="tool_calls", lazy="raise"
    )
    run: Mapped["AgentRun"] = relationship(
        back_populates="tool_calls", lazy="raise"
    )


class AgentLLMCall(Base):
    """Record of a single LLM API call with token and cost accounting.

    Chain-of-thought / reasoning fields are stripped by the repository
    before persistence.  Payloads are also redacted.
    """

    __tablename__ = "agent_llm_calls"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    trace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_traces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str | None] = mapped_column(Text(), nullable=True)
    model: Mapped[str | None] = mapped_column(Text(), nullable=True)
    temperature: Mapped[Decimal | None] = mapped_column(
        Numeric(3, 2), nullable=True
    )
    prompt_name: Mapped[str | None] = mapped_column(Text(), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(Text(), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    structured_output: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    parse_success: Mapped[bool | None] = mapped_column(Boolean(), nullable=True)
    parse_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    trace: Mapped["AgentTrace"] = relationship(
        back_populates="llm_calls", lazy="raise"
    )
    run: Mapped["AgentRun"] = relationship(
        back_populates="llm_calls", lazy="raise"
    )


class AgentFeedback(Base):
    """Explicit user or automated feedback signal attached to a trace.

    ``feedback_type`` distinguishes thumbs-up/down, scores, labels, etc.
    ``run_id`` is nullable — feedback may refer to the whole trace.
    """

    __tablename__ = "agent_feedback"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    trace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_traces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    feedback_type: Mapped[str] = mapped_column(Text(), nullable=False)
    score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    label: Mapped[str | None] = mapped_column(Text(), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    trace: Mapped["AgentTrace"] = relationship(
        back_populates="feedback", lazy="raise"
    )
    run: Mapped["AgentRun | None"] = relationship(
        back_populates="feedback", lazy="raise"
    )
