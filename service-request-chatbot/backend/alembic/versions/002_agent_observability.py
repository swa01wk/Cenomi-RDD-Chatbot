"""Agent observability tables — custom internal tracing layer.

Creates:
  agent_traces
  agent_runs
  agent_state_snapshots
  agent_state_diffs
  agent_tool_calls
  agent_llm_calls
  agent_feedback

Revision ID: 002
Revises: 001
Create Date: 2026-05-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── agent_traces ───────────────────────────────────────────────────────
    op.create_table(
        "agent_traces",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "trace_type",
            sa.Text(),
            nullable=False,
            server_default="CHAT_TURN",
        ),
        sa.Column("active_agent", sa.Text(), nullable=True),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("service_category", sa.Text(), nullable=True),
        sa.Column("sub_category", sa.Text(), nullable=True),
        sa.Column("workflow_stage_before", sa.Text(), nullable=True),
        sa.Column("workflow_stage_after", sa.Text(), nullable=True),
        sa.Column("input_message", sa.Text(), nullable=True),
        sa.Column("output_message", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("total_latency_ms", sa.Integer(), nullable=True),
        sa.Column("total_token_count", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(12, 6), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_traces_session_id", "agent_traces", ["session_id"])
    op.create_index("ix_agent_traces_user_id", "agent_traces", ["user_id"])
    op.create_index("ix_agent_traces_created_at", "agent_traces", ["created_at"])
    op.create_index("ix_agent_traces_status", "agent_traces", ["status"])
    op.create_index("ix_agent_traces_active_agent", "agent_traces", ["active_agent"])

    # ── agent_runs ─────────────────────────────────────────────────────────
    op.create_table(
        "agent_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "trace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("run_name", sa.Text(), nullable=False),
        sa.Column("run_type", sa.Text(), nullable=False),
        sa.Column("node_name", sa.Text(), nullable=True),
        sa.Column(
            "input",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "output",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_runs_trace_id", "agent_runs", ["trace_id"])
    op.create_index("ix_agent_runs_started_at", "agent_runs", ["started_at"])

    # ── agent_state_snapshots ──────────────────────────────────────────────
    op.create_table(
        "agent_state_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "trace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_type", sa.Text(), nullable=False),
        sa.Column(
            "state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_agent_state_snapshots_trace_id", "agent_state_snapshots", ["trace_id"]
    )
    op.create_index(
        "ix_agent_state_snapshots_run_id", "agent_state_snapshots", ["run_id"]
    )

    # ── agent_state_diffs ──────────────────────────────────────────────────
    op.create_table(
        "agent_state_diffs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "trace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "diff",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_agent_state_diffs_trace_id", "agent_state_diffs", ["trace_id"]
    )
    op.create_index("ix_agent_state_diffs_run_id", "agent_state_diffs", ["run_id"])

    # ── agent_tool_calls ───────────────────────────────────────────────────
    op.create_table(
        "agent_tool_calls",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "trace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("tool_type", sa.Text(), nullable=False),
        sa.Column(
            "request_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "response_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_agent_tool_calls_trace_id", "agent_tool_calls", ["trace_id"]
    )
    op.create_index("ix_agent_tool_calls_run_id", "agent_tool_calls", ["run_id"])

    # ── agent_llm_calls ────────────────────────────────────────────────────
    op.create_table(
        "agent_llm_calls",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "trace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("temperature", sa.Numeric(3, 2), nullable=True),
        sa.Column("prompt_name", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(12, 6), nullable=True),
        sa.Column(
            "structured_output",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("parse_success", sa.Boolean(), nullable=True),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_agent_llm_calls_trace_id", "agent_llm_calls", ["trace_id"])
    op.create_index("ix_agent_llm_calls_run_id", "agent_llm_calls", ["run_id"])

    # ── agent_feedback ─────────────────────────────────────────────────────
    op.create_table(
        "agent_feedback",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "trace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("feedback_type", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_agent_feedback_trace_id", "agent_feedback", ["trace_id"])


def downgrade() -> None:
    op.drop_table("agent_feedback")
    op.drop_table("agent_llm_calls")
    op.drop_table("agent_tool_calls")
    op.drop_table("agent_state_diffs")
    op.drop_table("agent_state_snapshots")
    op.drop_table("agent_runs")
    op.drop_table("agent_traces")
