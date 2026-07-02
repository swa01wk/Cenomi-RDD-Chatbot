"""Rename agent identifiers: handover_service_request_agent → rdd_agent.

Revision ID: 004
Revises: 003
Create Date: 2026-07-01

Context
-------
The agent taxonomy was updated so that:
  - ``helper_agent``  becomes the ``help_agent`` (supervisor + FAQ Q&A)
  - ``handover_service_request_agent`` becomes the ``rdd_agent``

The ``active_agent`` column in ``chat_sessions`` and ``agent_traces`` stores
the agent name as a plain text value.  Existing rows with the old name must
be migrated so that session continuity routing (``_AGENT_ENTRY_NODES`` lookup)
works correctly after the code rename.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE chat_sessions "
        "SET active_agent = 'rdd_agent' "
        "WHERE active_agent = 'handover_service_request_agent'"
    )
    op.execute(
        "UPDATE agent_traces "
        "SET active_agent = 'rdd_agent' "
        "WHERE active_agent = 'handover_service_request_agent'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE chat_sessions "
        "SET active_agent = 'handover_service_request_agent' "
        "WHERE active_agent = 'rdd_agent'"
    )
    op.execute(
        "UPDATE agent_traces "
        "SET active_agent = 'handover_service_request_agent' "
        "WHERE active_agent = 'rdd_agent'"
    )
