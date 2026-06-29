"""Backward-compatibility re-export.

The original service_request_graph was superseded by helper_agent_graph.
Tests that import build_service_request_graph or get_compiled_graph are
redirected to the Helper Agent graph which includes the full SR workflow.
"""
from app.agents.graph.helper_agent_graph import (  # noqa: F401
    build_helper_agent_graph as build_service_request_graph,
    get_compiled_helper_graph as get_compiled_graph,
)
