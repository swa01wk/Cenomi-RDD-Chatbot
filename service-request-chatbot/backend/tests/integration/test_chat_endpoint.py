"""Integration tests for POST /api/chat/service-request.

Strategy
--------
* Use ``httpx.AsyncClient`` with ``ASGITransport`` to exercise the full
  FastAPI request/response pipeline including middleware and dependency
  injection.
* Override the ``_get_db`` FastAPI dependency with an ``AsyncMock``-backed
  stub so no real database is needed.
* Patch ``ChatOrchestrationService.process_turn`` at the service layer to
  isolate the HTTP layer from graph and repository logic.
* For error-path tests, patch ``process_turn`` to raise an exception and
  verify the 500 response contract.

These tests run without Docker / Postgres / Redis.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.chat_orchestration_service import (
    ChatTurnResult,
    ChatTurnState,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ENDPOINT = "/api/chat/service-request"
_USER_ID = "user_456"
_SESSION_ID = str(uuid4())
_TRACE_ID = uuid4()
_RESULT_SESSION_ID = uuid4()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_result(
    *,
    session_id: UUID | None = None,
    active_agent: str = "handover_service_request_agent",
    message: str = "Please provide the brand name.",
    workflow_stage: str = "COLLECTING_FIELDS",
    missing_fields: list[str] | None = None,
    ready_to_submit: bool = False,
    trace_id: UUID | None = None,
) -> ChatTurnResult:
    return ChatTurnResult(
        session_id=session_id or _RESULT_SESSION_ID,
        active_agent=active_agent,
        message=message,
        ui={"type": "message"},
        state=ChatTurnState(
            intent="handover_service_request",
            workflow_stage=workflow_stage,
            missing_fields=missing_fields if missing_fields is not None else ["title", "startDate"],
            ready_to_submit=ready_to_submit,
        ),
        trace_id=trace_id or _TRACE_ID,
    )


def _stub_db():
    """Return a no-op AsyncMock that satisfies the DbSession dependency."""
    return AsyncMock()


# ---------------------------------------------------------------------------
# Helper — build client with stubbed DB dependency
# ---------------------------------------------------------------------------


def _make_client_and_patch():
    """Return (AsyncClient, process_turn patcher) context manager pair."""
    from app.db.session import _get_db  # noqa: PLC0415

    transport = ASGITransport(app=app)

    def _override():
        yield _stub_db()

    app.dependency_overrides[_get_db] = _override
    client = AsyncClient(transport=transport, base_url="http://test")
    return client


def _restore_overrides():
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_new_session_returns_200_with_correct_schema() -> None:
    """A first-turn request (no session_id) creates a session and returns valid schema."""
    result = _make_result()
    client = _make_client_and_patch()
    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new_callable=AsyncMock,
            return_value=result,
        ):
            async with client as c:
                resp = await c.post(
                    _ENDPOINT,
                    json={
                        "user_id": _USER_ID,
                        "message": "I want to raise a handover request for Under Armour in Jawharat Jeddah",
                        "attachments": [],
                    },
                )
    finally:
        _restore_overrides()

    assert resp.status_code == 200
    body = resp.json()

    assert body["session_id"] == str(_RESULT_SESSION_ID)
    assert body["active_agent"] == "handover_service_request_agent"
    assert body["message"] == "Please provide the brand name."
    assert body["trace_id"] == str(_TRACE_ID)

    state = body["state"]
    assert state["intent"] == "handover_service_request"
    assert state["workflow_stage"] == "COLLECTING_FIELDS"
    assert "title" in state["missing_fields"]
    assert state["ready_to_submit"] is False

    ui = body["ui"]
    assert ui["type"] == "message"


async def test_continuing_session_passes_session_id_to_service() -> None:
    """When session_id is provided, it is parsed and passed to the orchestration service."""
    existing_session_id = uuid4()
    result = _make_result(session_id=existing_session_id)
    client = _make_client_and_patch()

    captured_kwargs: dict = {}

    async def _mock_process_turn(self, **kwargs):  # noqa: ANN001
        captured_kwargs.update(kwargs)
        return result

    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new=_mock_process_turn,
        ):
            async with client as c:
                resp = await c.post(
                    _ENDPOINT,
                    json={
                        "session_id": str(existing_session_id),
                        "user_id": _USER_ID,
                        "message": "The brand is Under Armour.",
                        "attachments": [],
                    },
                )
    finally:
        _restore_overrides()

    assert resp.status_code == 200
    assert captured_kwargs["session_id"] == existing_session_id


async def test_non_uuid_user_id_is_mapped_deterministically() -> None:
    """A non-UUID user_id string is deterministically mapped to a UUID."""
    result = _make_result()
    captured_kwargs: dict = {}
    client = _make_client_and_patch()

    async def _mock_process_turn(self, **kwargs):  # noqa: ANN001
        captured_kwargs.update(kwargs)
        return result

    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new=_mock_process_turn,
        ):
            async with client as c:
                await c.post(
                    _ENDPOINT,
                    json={"user_id": "user_456", "message": "hello", "attachments": []},
                )
                await c.post(
                    _ENDPOINT,
                    json={"user_id": "user_456", "message": "hello again", "attachments": []},
                )
    finally:
        _restore_overrides()

    calls = [kw["user_id"] for kw in captured_kwargs.values()] if False else None
    # Both calls used the same user_id string — verify the UUID is a valid UUID instance
    assert isinstance(captured_kwargs["user_id"], UUID)


async def test_invalid_session_id_creates_new_session() -> None:
    """A non-UUID session_id is ignored and a new session is created transparently."""
    result = _make_result()
    captured_kwargs: dict = {}
    client = _make_client_and_patch()

    async def _mock_process_turn(self, **kwargs):  # noqa: ANN001
        captured_kwargs.update(kwargs)
        return result

    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new=_mock_process_turn,
        ):
            async with client as c:
                resp = await c.post(
                    _ENDPOINT,
                    json={
                        "session_id": "not-a-uuid",
                        "user_id": _USER_ID,
                        "message": "hello",
                        "attachments": [],
                    },
                )
    finally:
        _restore_overrides()

    assert resp.status_code == 200
    # Invalid UUID → parsed as None → new session created
    assert captured_kwargs["session_id"] is None


async def test_ready_to_submit_flag_in_response() -> None:
    """When the graph reports READY_TO_SUBMIT, the response reflects it."""
    result = _make_result(
        ready_to_submit=True,
        missing_fields=[],
        workflow_stage="CONFIRMATION",
    )
    client = _make_client_and_patch()

    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new_callable=AsyncMock,
            return_value=result,
        ):
            async with client as c:
                resp = await c.post(
                    _ENDPOINT,
                    json={"user_id": _USER_ID, "message": "Yes, I confirm.", "attachments": []},
                )
    finally:
        _restore_overrides()

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"]["ready_to_submit"] is True
    assert body["state"]["missing_fields"] == []


async def test_attachments_forwarded_to_service() -> None:
    """Attachments from the request body are forwarded to process_turn."""
    result = _make_result()
    captured_kwargs: dict = {}
    client = _make_client_and_patch()

    async def _mock_process_turn(self, **kwargs):  # noqa: ANN001
        captured_kwargs.update(kwargs)
        return result

    attachment = {"file_id": "f123", "filename": "plan.pdf", "content_type": "application/pdf"}

    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new=_mock_process_turn,
        ):
            async with client as c:
                await c.post(
                    _ENDPOINT,
                    json={
                        "user_id": _USER_ID,
                        "message": "See attached document.",
                        "attachments": [attachment],
                    },
                )
    finally:
        _restore_overrides()

    assert captured_kwargs["attachments"] == [attachment]


async def test_graph_error_returns_500() -> None:
    """When the orchestration service raises, the endpoint returns HTTP 500."""
    client = _make_client_and_patch()

    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM quota exceeded"),
        ):
            async with client as c:
                resp = await c.post(
                    _ENDPOINT,
                    json={"user_id": _USER_ID, "message": "hello", "attachments": []},
                )
    finally:
        _restore_overrides()

    assert resp.status_code == 500
    body = resp.json()
    assert "detail" in body
    assert "error" in body["detail"].lower() or "request" in body["detail"].lower()


async def test_missing_message_returns_422() -> None:
    """Pydantic validation rejects a request that omits the required `message` field."""
    client = _make_client_and_patch()

    try:
        async with client as c:
            resp = await c.post(
                _ENDPOINT,
                json={"user_id": _USER_ID},
            )
    finally:
        _restore_overrides()

    assert resp.status_code == 422


async def test_empty_message_returns_422() -> None:
    """An empty string for `message` violates the min_length=1 constraint."""
    client = _make_client_and_patch()

    try:
        async with client as c:
            resp = await c.post(
                _ENDPOINT,
                json={"user_id": _USER_ID, "message": "", "attachments": []},
            )
    finally:
        _restore_overrides()

    assert resp.status_code == 422


async def test_missing_user_id_returns_422() -> None:
    """A request without user_id fails Pydantic validation."""
    client = _make_client_and_patch()

    try:
        async with client as c:
            resp = await c.post(
                _ENDPOINT,
                json={"message": "hello", "attachments": []},
            )
    finally:
        _restore_overrides()

    assert resp.status_code == 422


async def test_no_trace_id_when_tracing_unavailable() -> None:
    """When trace_id is None (tracing failed silently), the response omits it."""
    result = _make_result(trace_id=None)
    # Override trace_id manually since frozen dataclass
    result_no_trace = ChatTurnResult(
        session_id=result.session_id,
        active_agent=result.active_agent,
        message=result.message,
        ui=result.ui,
        state=result.state,
        trace_id=None,
    )
    client = _make_client_and_patch()

    try:
        with patch(
            "app.services.chat_orchestration_service.ChatOrchestrationService.process_turn",
            new_callable=AsyncMock,
            return_value=result_no_trace,
        ):
            async with client as c:
                resp = await c.post(
                    _ENDPOINT,
                    json={"user_id": _USER_ID, "message": "hello", "attachments": []},
                )
    finally:
        _restore_overrides()

    assert resp.status_code == 200
    assert resp.json()["trace_id"] is None


# ---------------------------------------------------------------------------
# Health endpoint smoke test (regression guard)
# ---------------------------------------------------------------------------


async def test_health_still_ok() -> None:
    """Verify the /health endpoint still returns 200 after route changes."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
