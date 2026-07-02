# Re-export shim — canonical location is nodes/shared/merge_state_node.py
from app.agents.graph.nodes.shared.merge_state_node import *  # noqa: F401, F403
from app.agents.graph.nodes.shared.merge_state_node import (  # noqa: F401
    merge_state_node,
    BACKEND_COMPUTED_FIELDS,
    BACKEND_PROTECTED_FIELDS,
    _add_days,
)
