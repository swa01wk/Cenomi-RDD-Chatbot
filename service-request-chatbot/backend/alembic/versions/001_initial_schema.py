"""Initial schema — all tables managed by this application.

Creates:
  Domain tables
  ─────────────
  chat_sessions
  chat_messages
  service_request_drafts
  service_request_chat_audit_logs

  Observability tables
  ─────────────────────
  observability_traces
  observability_runs
  observability_llm_calls
  observability_tool_calls
  observability_state_snapshots
  observability_feedback

Revision ID: 001
Revises:
Create Date: 2026-05-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── chat_sessions ──────────────────────────────────────────────────────
    op.create_table(
        "chat_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("active_agent", sa.Text(), nullable=True),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("workflow_stage", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="IN_PROGRESS",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])

    # ── chat_messages ──────────────────────────────────────────────────────
    op.create_table(
        "chat_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
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
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])

    # ── service_request_drafts ─────────────────────────────────────────────
    op.create_table(
        "service_request_drafts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("service_category", sa.Text(), nullable=False),
        sa.Column("sub_category", sa.Text(), nullable=False),
        sa.Column("workflow_stage", sa.Text(), nullable=False),
        sa.Column(
            "collected_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "missing_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "documents",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("sr_id", sa.Text(), nullable=True),
        sa.Column("service_request_status", sa.Text(), nullable=True),
        sa.Column(
            "ready_to_submit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_service_request_drafts_session_id",
        "service_request_drafts",
        ["session_id"],
    )

    # ── service_request_chat_audit_logs ────────────────────────────────────
    op.create_table(
        "service_request_chat_audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "before_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "after_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
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
    )
    op.create_index(
        "ix_service_request_chat_audit_logs_session_id",
        "service_request_chat_audit_logs",
        ["session_id"],
    )

    # ── observability_traces ───────────────────────────────────────────────
    op.create_table(
        "observability_traces",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="running",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── observability_runs ─────────────────────────────────────────────────
    op.create_table(
        "observability_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "trace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observability_traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observability_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("node_name", sa.String(256), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_observability_runs_trace_id", "observability_runs", ["trace_id"])

    # ── observability_llm_calls ────────────────────────────────────────────
    op.create_table(
        "observability_llm_calls",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observability_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "raw_request",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "raw_response",
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
    )
    op.create_index(
        "ix_observability_llm_calls_run_id",
        "observability_llm_calls",
        ["run_id"],
    )

    # ── observability_tool_calls ───────────────────────────────────────────
    op.create_table(
        "observability_tool_calls",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observability_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(256), nullable=False),
        sa.Column(
            "arguments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "result",
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
    )
    op.create_index(
        "ix_observability_tool_calls_run_id",
        "observability_tool_calls",
        ["run_id"],
    )

    # ── observability_state_snapshots ──────────────────────────────────────
    op.create_table(
        "observability_state_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observability_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "diff_from_previous",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_observability_state_snapshots_run_id",
        "observability_state_snapshots",
        ["run_id"],
    )

    # ── observability_feedback ─────────────────────────────────────────────
    op.create_table(
        "observability_feedback",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "trace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observability_traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
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
    )
    op.create_index(
        "ix_observability_feedback_trace_id",
        "observability_feedback",
        ["trace_id"],
    )


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("observability_feedback")
    op.drop_table("observability_state_snapshots")
    op.drop_table("observability_tool_calls")
    op.drop_table("observability_llm_calls")
    op.drop_table("observability_runs")
    op.drop_table("observability_traces")
    op.drop_table("service_request_chat_audit_logs")
    op.drop_table("service_request_drafts")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
