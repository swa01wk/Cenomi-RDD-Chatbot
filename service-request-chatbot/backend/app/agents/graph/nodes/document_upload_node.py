"""Coordinate file upload integration."""

from typing import Any

from app.agents.graph.state import ServiceRequestState


async def document_upload_node(state: ServiceRequestState) -> dict[str, Any]:
    return {}
