# Re-export shim — canonical location is nodes/shared/missing_field_node.py
from app.agents.graph.nodes.shared.missing_field_node import *  # noqa: F401, F403
from app.agents.graph.nodes.shared.missing_field_node import (  # noqa: F401
    missing_field_node,
    BACKEND_PROTECTED_FIELDS,
)
