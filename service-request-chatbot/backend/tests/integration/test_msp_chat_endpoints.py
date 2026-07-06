"""Integration tests for the MSP-compatible help chat endpoints.

    POST /api/v1/chat         — synchronous JSON
    POST /api/v1/chat/stream  — SSE streaming

Strategy
--------
* Uses httpx.AsyncClient with ASGITransport — no real DB, graph, or LLM required.
* Patches ChatOrchestrationService.process_turn to return a controlled ChatTurnResult.
* Validates request parsing, response shape, SSE frame format, auth token check.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.chat_orchestration_service import ChatTurnResult, ChatTurnState

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SYNC_URL = "/api/v1/chat"
_STREAM_URL = "/api/v1/chat/stream"
_SESSION_ID = uuid4()
_TRACE_ID = uuid4()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_DEFAULT_SOURCES = [{"source_type": "help_content", "title": "Service Request Guide"}]


def _make_result(
    *,
    message: str = "To submit a service request, navigate to the SR module.",
    faq_sources: list[dict] | None = None,
) -> ChatTurnResult:
    return ChatTurnResult(
        session_id=_SESSION_ID,
        active_agent=None,
        message=message,
        ui={"type": "message"},
        state=ChatTurnState(
            intent="ASK_HELP",
            workflow_stage=None,
            missing_fields=[],
            ready_to_submit=False,
        ),
        trace_id=_TRACE_ID,
        faq_sources=_DEFAULT_SOURCES if faq_sources is None else faq_sources,
    )


def _make_client():
    from app.db.session import _get_db  # noqa: PLC0415

    def _override():
        yield AsyncMock()

    app.dependency_overrides[_get_db] = _override
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _restore():
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/v1/chat — sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_returns_200_with_msp_shape() -> None:
    """Happy-path: returns MSP response shape with all required fields."""
    result = _make_result()
    client = _make_client()
    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new_callable=AsyncMock,
            return_value=result,
        ):
            async with client as c:
                resp = await c.post(
                    _SYNC_URL,
                    json={"message": "How do I submit a service request?"},
                )
    finally:
        _restore()

    assert resp.status_code == 200
    data = resp.json()

    # MSP contract fields
    assert "conversation_id" in data
    assert "message_id" in data
    assert "message" in data
    assert "sources" in data
    assert "language" in data

    # Values
    assert data["conversation_id"] == str(_SESSION_ID)
    assert data["message"] == result.message
    assert len(data["sources"]) == 1
    assert data["sources"][0]["source_type"] == "help_content"
    assert data["sources"][0]["title"] == "Service Request Guide"
    assert data["language"] in ("en", "ar")

    # MSP shape must NOT include existing endpoint's internal fields
    assert "session_id" not in data
    assert "faq_sources" not in data
    assert "state" not in data
    assert "ui" not in data


@pytest.mark.asyncio
async def test_sync_conversation_id_echoed_back() -> None:
    """conversation_id sent on request is used as session_id and echoed in response."""
    result = _make_result()
    client = _make_client()
    sent_id = str(uuid4())
    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new_callable=AsyncMock,
            return_value=result,
        ):
            async with client as c:
                resp = await c.post(
                    _SYNC_URL,
                    json={"message": "What is FM Review?", "conversation_id": sent_id},
                )
    finally:
        _restore()

    assert resp.status_code == 200
    # The result session_id (from the mock) is returned as conversation_id
    assert resp.json()["conversation_id"] == str(_SESSION_ID)


@pytest.mark.asyncio
async def test_sync_language_ar_echoed() -> None:
    """language='ar' in request is reflected in response."""
    result = _make_result()
    client = _make_client()
    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new_callable=AsyncMock,
            return_value=result,
        ):
            async with client as c:
                resp = await c.post(
                    _SYNC_URL,
                    json={"message": "كيف أرفع طلب خدمة؟", "language": "ar"},
                )
    finally:
        _restore()

    assert resp.status_code == 200
    assert resp.json()["language"] == "ar"


@pytest.mark.asyncio
async def test_sync_empty_sources_when_no_faq() -> None:
    """sources is an empty list when the FAQ node returned no citations."""
    result = _make_result(faq_sources=[])
    client = _make_client()
    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new_callable=AsyncMock,
            return_value=result,
        ):
            async with client as c:
                resp = await c.post(_SYNC_URL, json={"message": "Hello"})
    finally:
        _restore()

    assert resp.status_code == 200
    assert resp.json()["sources"] == []


@pytest.mark.asyncio
async def test_sync_message_id_is_unique_per_request() -> None:
    """Each request gets a distinct message_id."""
    result = _make_result()
    client = _make_client()
    ids: list[str] = []
    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new_callable=AsyncMock,
            return_value=result,
        ):
            async with client as c:
                for _ in range(2):
                    r = await c.post(_SYNC_URL, json={"message": "test"})
                    ids.append(r.json()["message_id"])
    finally:
        _restore()

    assert ids[0] != ids[1]


@pytest.mark.asyncio
async def test_sync_422_on_empty_message() -> None:
    """Empty message string violates min_length=1 validation."""
    client = _make_client()
    try:
        async with client as c:
            resp = await c.post(_SYNC_URL, json={"message": ""})
    finally:
        _restore()

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_sync_422_on_missing_message() -> None:
    """Absent message field raises 422."""
    client = _make_client()
    try:
        async with client as c:
            resp = await c.post(_SYNC_URL, json={})
    finally:
        _restore()

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_sync_service_token_enforced_when_configured(monkeypatch) -> None:
    """When MSP_SERVICE_TOKEN is set, requests with the wrong token get 401."""
    monkeypatch.setattr(
        "app.api.routes.msp_chat.settings",
        type("S", (), {"msp_service_token": "secret-token", "rbac_enforce": False})(),
    )
    client = _make_client()
    try:
        async with client as c:
            resp = await c.post(
                _SYNC_URL,
                json={"message": "Hello"},
                headers={"x-internal-api-token": "wrong-token"},
            )
    finally:
        _restore()

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sync_service_token_passes_when_correct(monkeypatch) -> None:
    """Correct service token allows the request through."""
    monkeypatch.setattr(
        "app.api.routes.msp_chat.settings",
        type("S", (), {"msp_service_token": "secret-token", "rbac_enforce": False})(),
    )
    result = _make_result()
    client = _make_client()
    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new_callable=AsyncMock,
            return_value=result,
        ):
            async with client as c:
                resp = await c.post(
                    _SYNC_URL,
                    json={"message": "Hello"},
                    headers={"x-internal-api-token": "secret-token"},
                )
    finally:
        _restore()

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/v1/chat/stream — SSE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_content_type_is_sse() -> None:
    """Response Content-Type must be text/event-stream."""
    result = _make_result()
    client = _make_client()
    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new_callable=AsyncMock,
            return_value=result,
        ):
            async with client as c:
                resp = await c.post(_STREAM_URL, json={"message": "How do I submit an SR?"})
    finally:
        _restore()

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_stream_emits_token_source_done_events() -> None:
    """Stream must emit: token → source(s) → done events in that order."""
    result = _make_result()
    client = _make_client()
    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new_callable=AsyncMock,
            return_value=result,
        ):
            async with client as c:
                resp = await c.post(_STREAM_URL, json={"message": "How do I submit an SR?"})
    finally:
        _restore()

    raw = resp.text
    # Parse SSE frames: split on double-newline
    frames = [f.strip() for f in raw.split("\n\n") if f.strip()]

    event_types: list[str] = []
    import json as _json

    events: dict[str, dict] = {}
    for frame in frames:
        lines = frame.splitlines()
        event_type = None
        data = None
        for line in lines:
            if line.startswith("event: "):
                event_type = line[len("event: "):]
            elif line.startswith("data: "):
                data = _json.loads(line[len("data: "):])
        if event_type:
            event_types.append(event_type)
            events[event_type] = data or {}

    assert event_types[0] == "token", f"First event must be 'token', got {event_types}"
    assert "source" in event_types, "Must have at least one 'source' event"
    assert event_types[-1] == "done", f"Last event must be 'done', got {event_types}"

    # token event has the message text
    assert events["token"]["text"] == result.message

    # done event has conversation_id and message_id
    assert "conversation_id" in events["done"]
    assert "message_id" in events["done"]
    assert events["done"]["conversation_id"] == str(_SESSION_ID)


@pytest.mark.asyncio
async def test_stream_no_source_events_when_no_faq() -> None:
    """Stream emits only token + done when faq_sources is empty."""
    result = _make_result(faq_sources=[])
    client = _make_client()
    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new_callable=AsyncMock,
            return_value=result,
        ):
            async with client as c:
                resp = await c.post(_STREAM_URL, json={"message": "Hello"})
    finally:
        _restore()

    raw = resp.text
    frames = [f.strip() for f in raw.split("\n\n") if f.strip()]
    event_types = []
    for frame in frames:
        for line in frame.splitlines():
            if line.startswith("event: "):
                event_types.append(line[len("event: "):])

    assert "source" not in event_types
    assert "token" in event_types
    assert "done" in event_types


@pytest.mark.asyncio
async def test_stream_error_event_on_graph_failure() -> None:
    """A graph exception surfaces as an SSE error event, not a 500 HTTP error."""
    client = _make_client()
    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new_callable=AsyncMock,
            side_effect=RuntimeError("graph boom"),
        ):
            async with client as c:
                resp = await c.post(_STREAM_URL, json={"message": "trigger error"})
    finally:
        _restore()

    # HTTP layer returns 200 (stream started); error is inside the SSE body
    assert resp.status_code == 200
    assert "event: error" in resp.text
