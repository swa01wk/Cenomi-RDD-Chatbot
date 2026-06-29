"""supervisor_node lives at nodes/supervisor_node.py for test-patching compatibility.
This stub re-exports for any code importing from nodes.shared.supervisor_node."""
from app.agents.graph.nodes.supervisor_node import *  # noqa: F401, F403
from app.agents.graph.nodes.supervisor_node import (  # noqa: F401
    _CANCEL_PHRASES,
    _PREVIEW_PHRASES,
    _user_wants_to_switch,
    _user_wants_preview,
    _build_user_content,
    _call_supervisor_llm,
    _extract_uuid,
)
