"""Reorganised — kept for backward compatibility. Real module: nodes/handover/merge_state_node.py"""
from app.agents.graph.nodes.handover.merge_state_node import *  # noqa: F401, F403
from app.agents.graph.nodes.handover.merge_state_node import (  # noqa: F401
    BACKEND_PROTECTED_FIELDS,
    BACKEND_COMPUTED_FIELDS,
    _LEASE_CONFIRMED_FIELDS,
    _CONFIDENCE_THRESHOLD,
    _generate_title,
    _add_days,
)
