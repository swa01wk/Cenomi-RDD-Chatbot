"""Integration tests for the observability read/write API.

Strategy
--------
* httpx.AsyncClient + ASGITransport exercises the full FastAPI pipeline.
* The _get_db dependency is overridden with a no-op AsyncMock.
* Repository methods are patched at the class level so no real DB is hit.
* All four endpoints are covered:
    GET  /api/observability/traces
    GET  /api/observability/traces/{trace_id}
    GET  /api/observability/sessions/{session_id}/replay
    POST /api/observability/traces/{trace_id}/feedback
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TRACES_URL = "/api/observability/traces"
_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


def _stub_db():
    return AsyncMock()


def _make_app_client() -> AsyncClient:
    from app.db.session import _get_db

    app.dependency_overrides[_get_db] = lambda: (yield _stub_db())
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _restore():
    app.dependency_overrides.clear()


def _mock_trace(
    *,
    trace_id: UUID | None = None,
    session_id: UUID | None = None,
    user_id: UUID | None = None,
    status: str = "SUCCESS",
    error_message: str | None = None,
) -> MagicMock:
    row = MagicMock()
    row.id = trace_id or uuid4()
    row.session_id = session_id or uuid4()
    row.user_id = user_id or uuid4()
    row.trace_type = "CHAT_TURN"
    row.active_agent = "sr_agent"
    row.intent = "handover_service_request"
    row.service_category = None
    row.sub_category = None
    row.workflow_stage_before = None
    row.workflow_stage_after = None
    row.input_message = "hello"
    row.output_message = "world"
    row.status = status
    row.error_message = error_message
    row.total_latency_ms = 200
    row.total_token_count = 80
    row.estimated_cost = Decimal("0.001")
    row.metadata_ = {}
    row.created_at = _NOW
    row.completed_at = None
    return row


def _mock_run(
    *,
    run_id: UUID | None = None,
    trace_id: UUID | None = None,
    parent_run_id: UUID | None = None,
) -> MagicMock:
    row = MagicMock()
    row.id = run_id or uuid4()
    row.trace_id = trace_id or uuid4()
    row.parent_run_id = parent_run_id
    row.run_name = "node_a"
    row.run_type = "LANGGRAPH_NODE"
    row.node_name = "node_a"
    row.input = {}
    row.output = {}
    row.status = "SUCCESS"
    row.error_message = None
    row.latency_ms = 50
    row.started_at = _NOW
    row.completed_at = None
    return row


def _mock_feedback(*, trace_id: UUID) -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.trace_id = trace_id
    row.run_id = None
    row.user_id = None
    row.feedback_type = "ADMIN_REVIEW"
    row.score = 4
    row.label = "GOOD_EXTRACTION"
    row.comment = "Agent correctly extracted the lease."
    row.created_at = _NOW
    return row


# ---------------------------------------------------------------------------
# GET /api/observability/traces
# ---------------------------------------------------------------------------


class TestListTraces:
    @pytest.mark.asyncio
    async def test_returns_200_with_paginated_schema(self):
        traces = [_mock_trace(), _mock_trace()]
        client = _make_app_client()
        try:
            with (
                patch(
                    "app.observability.api.traces.TraceRepository.list_filtered",
                    new_callable=AsyncMock,
                    return_value=(traces, 2),
                ),
            ):
                async with client as c:
                    resp = await c.get(_TRACES_URL)
        finally:
            _restore()

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["page"] == 1
        assert body["page_size"] == 20
        assert body["has_next"] is False
        assert len(body["items"]) == 2

    @pytest.mark.asyncio
    async def test_pagination_has_next_when_more_pages(self):
        traces = [_mock_trace() for _ in range(20)]
        client = _make_app_client()
        try:
            with patch(
                "app.observability.api.traces.TraceRepository.list_filtered",
                new_callable=AsyncMock,
                return_value=(traces, 45),
            ):
                async with client as c:
                    resp = await c.get(_TRACES_URL, params={"page": 1, "page_size": 20})
        finally:
            _restore()

        body = resp.json()
        assert body["total"] == 45
        assert body["has_next"] is True

    @pytest.mark.asyncio
    async def test_query_params_forwarded_to_repository(self):
        captured: dict = {}

        async def _list_filtered(self, **kwargs):  # noqa: ANN001
            captured.update(kwargs)
            return [], 0

        client = _make_app_client()
        try:
            with patch(
                "app.observability.api.traces.TraceRepository.list_filtered",
                new=_list_filtered,
            ):
                async with client as c:
                    await c.get(
                        _TRACES_URL,
                        params={
                            "status": "FAILED",
                            "agent": "sr_agent",
                            "intent": "lease_renewal",
                            "has_error": "true",
                            "min_latency_ms": "300",
                            "page": "2",
                            "page_size": "10",
                        },
                    )
        finally:
            _restore()

        assert captured["status"] == "FAILED"
        assert captured["agent"] == "sr_agent"
        assert captured["intent"] == "lease_renewal"
        assert captured["has_error"] is True
        assert captured["min_latency_ms"] == 300
        assert captured["page"] == 2
        assert captured["page_size"] == 10

    @pytest.mark.asyncio
    async def test_empty_result_returns_200_not_404(self):
        client = _make_app_client()
        try:
            with patch(
                "app.observability.api.traces.TraceRepository.list_filtered",
                new_callable=AsyncMock,
                return_value=([], 0),
            ):
                async with client as c:
                    resp = await c.get(_TRACES_URL, params={"status": "UNKNOWN"})
        finally:
            _restore()

        assert resp.status_code == 200
        assert resp.json()["items"] == []

    @pytest.mark.asyncio
    async def test_page_size_capped_at_200(self):
        client = _make_app_client()
        try:
            with patch(
                "app.observability.api.traces.TraceRepository.list_filtered",
                new_callable=AsyncMock,
                return_value=([], 0),
            ):
                async with client as c:
                    resp = await c.get(_TRACES_URL, params={"page_size": "999"})
        finally:
            _restore()

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_sensitive_fields_not_exposed_in_summary(self):
        trace = _mock_trace()
        client = _make_app_client()
        try:
            with patch(
                "app.observability.api.traces.TraceRepository.list_filtered",
                new_callable=AsyncMock,
                return_value=([trace], 1),
            ):
                async with client as c:
                    resp = await c.get(_TRACES_URL)
        finally:
            _restore()

        item = resp.json()["items"][0]
        assert "metadata_" not in item
        assert "metadata" not in item


# ---------------------------------------------------------------------------
# GET /api/observability/traces/{trace_id}
# ---------------------------------------------------------------------------


class TestGetTrace:
    @pytest.mark.asyncio
    async def test_returns_full_detail_schema(self):
        tid = uuid4()
        trace = _mock_trace(trace_id=tid)
        run = _mock_run(trace_id=tid)

        client = _make_app_client()
        try:
            with (
                patch(
                    "app.observability.api.traces.TraceRepository.get",
                    new_callable=AsyncMock,
                    return_value=trace,
                ),
                patch(
                    "app.observability.api.traces.RunRepository.list_for_trace",
                    new_callable=AsyncMock,
                    return_value=[run],
                ),
                patch(
                    "app.observability.api.traces.StateSnapshotRepository.list_for_trace",
                    new_callable=AsyncMock,
                    return_value=[],
                ),
                patch(
                    "app.observability.api.traces.StateDiffRepository.list_for_trace",
                    new_callable=AsyncMock,
                    return_value=[],
                ),
                patch(
                    "app.observability.api.traces.LLMCallRepository.list_for_trace",
                    new_callable=AsyncMock,
                    return_value=[],
                ),
                patch(
                    "app.observability.api.traces.ToolCallRepository.list_for_trace",
                    new_callable=AsyncMock,
                    return_value=[],
                ),
                patch(
                    "app.observability.api.traces.FeedbackRepository.list_for_trace",
                    new_callable=AsyncMock,
                    return_value=[],
                ),
            ):
                async with client as c:
                    resp = await c.get(f"{_TRACES_URL}/{tid}")
        finally:
            _restore()

        assert resp.status_code == 200
        body = resp.json()
        assert "trace" in body
        assert "runs" in body
        assert "run_tree" in body
        assert "state_snapshots" in body
        assert "state_diffs" in body
        assert "llm_calls" in body
        assert "tool_calls" in body
        assert "feedback" in body
        assert body["trace"]["id"] == str(tid)
        assert len(body["runs"]) == 1

    @pytest.mark.asyncio
    async def test_run_tree_nested_correctly(self):
        tid = uuid4()
        parent_id = uuid4()
        child_id = uuid4()
        trace = _mock_trace(trace_id=tid)
        parent_run = _mock_run(run_id=parent_id, trace_id=tid)
        child_run = _mock_run(run_id=child_id, trace_id=tid, parent_run_id=parent_id)

        client = _make_app_client()
        try:
            with (
                patch("app.observability.api.traces.TraceRepository.get", new_callable=AsyncMock, return_value=trace),
                patch("app.observability.api.traces.RunRepository.list_for_trace", new_callable=AsyncMock, return_value=[parent_run, child_run]),
                patch("app.observability.api.traces.StateSnapshotRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.traces.StateDiffRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.traces.LLMCallRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.traces.ToolCallRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.traces.FeedbackRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
            ):
                async with client as c:
                    resp = await c.get(f"{_TRACES_URL}/{tid}")
        finally:
            _restore()

        body = resp.json()
        run_tree = body["run_tree"]
        assert len(run_tree) == 1  # one root
        assert run_tree[0]["id"] == str(parent_id)
        assert len(run_tree[0]["children"]) == 1
        assert run_tree[0]["children"][0]["id"] == str(child_id)

    @pytest.mark.asyncio
    async def test_unknown_trace_id_returns_404(self):
        client = _make_app_client()
        try:
            with patch(
                "app.observability.api.traces.TraceRepository.get",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with client as c:
                    resp = await c.get(f"{_TRACES_URL}/{uuid4()}")
        finally:
            _restore()

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_metadata_not_in_trace_detail_response(self):
        tid = uuid4()
        trace = _mock_trace(trace_id=tid)
        client = _make_app_client()
        try:
            with (
                patch("app.observability.api.traces.TraceRepository.get", new_callable=AsyncMock, return_value=trace),
                patch("app.observability.api.traces.RunRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.traces.StateSnapshotRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.traces.StateDiffRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.traces.LLMCallRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.traces.ToolCallRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.traces.FeedbackRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
            ):
                async with client as c:
                    resp = await c.get(f"{_TRACES_URL}/{tid}")
        finally:
            _restore()

        trace_body = resp.json()["trace"]
        assert "metadata_" not in trace_body


# ---------------------------------------------------------------------------
# GET /api/observability/sessions/{session_id}/replay
# ---------------------------------------------------------------------------


class TestSessionReplay:
    @pytest.mark.asyncio
    async def test_returns_ordered_replay(self):
        sid = uuid4()
        older = _mock_trace(session_id=sid)
        older.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        newer = _mock_trace(session_id=sid)
        newer.created_at = datetime(2024, 6, 1, tzinfo=timezone.utc)

        client = _make_app_client()
        try:
            with (
                patch(
                    "app.observability.api.sessions.TraceRepository.list_by_session",
                    new_callable=AsyncMock,
                    # list_by_session returns most-recent first
                    return_value=[newer, older],
                ),
                patch("app.observability.api.sessions.RunRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.sessions.StateSnapshotRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.sessions.StateDiffRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.sessions.LLMCallRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.sessions.ToolCallRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.sessions.FeedbackRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
            ):
                async with client as c:
                    resp = await c.get(f"/api/observability/sessions/{sid}/replay")
        finally:
            _restore()

        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == str(sid)
        assert body["trace_count"] == 2
        # Verify oldest-first order (list is reversed inside endpoint)
        assert body["traces"][0]["trace"]["id"] == str(older.id)
        assert body["traces"][1]["trace"]["id"] == str(newer.id)

    @pytest.mark.asyncio
    async def test_no_traces_returns_404(self):
        sid = uuid4()
        client = _make_app_client()
        try:
            with patch(
                "app.observability.api.sessions.TraceRepository.list_by_session",
                new_callable=AsyncMock,
                return_value=[],
            ):
                async with client as c:
                    resp = await c.get(f"/api/observability/sessions/{sid}/replay")
        finally:
            _restore()

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_each_trace_entry_has_full_schema(self):
        sid = uuid4()
        trace = _mock_trace(session_id=sid)
        run = _mock_run(trace_id=trace.id)

        client = _make_app_client()
        try:
            with (
                patch("app.observability.api.sessions.TraceRepository.list_by_session", new_callable=AsyncMock, return_value=[trace]),
                patch("app.observability.api.sessions.RunRepository.list_for_trace", new_callable=AsyncMock, return_value=[run]),
                patch("app.observability.api.sessions.StateSnapshotRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.sessions.StateDiffRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.sessions.LLMCallRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.sessions.ToolCallRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
                patch("app.observability.api.sessions.FeedbackRepository.list_for_trace", new_callable=AsyncMock, return_value=[]),
            ):
                async with client as c:
                    resp = await c.get(f"/api/observability/sessions/{sid}/replay")
        finally:
            _restore()

        entry = resp.json()["traces"][0]
        for key in ("trace", "runs", "run_tree", "state_snapshots", "state_diffs", "llm_calls", "tool_calls", "feedback"):
            assert key in entry, f"Missing key '{key}' in replay entry"


# ---------------------------------------------------------------------------
# POST /api/observability/traces/{trace_id}/feedback
# ---------------------------------------------------------------------------


class TestSubmitFeedback:
    @pytest.mark.asyncio
    async def test_returns_201_with_feedback_schema(self):
        tid = uuid4()
        trace = _mock_trace(trace_id=tid)
        fb = _mock_feedback(trace_id=tid)

        client = _make_app_client()
        try:
            with (
                patch(
                    "app.observability.api.feedback.TraceRepository.get",
                    new_callable=AsyncMock,
                    return_value=trace,
                ),
                patch(
                    "app.observability.api.feedback.FeedbackRepository.create",
                    new_callable=AsyncMock,
                    return_value=fb,
                ),
            ):
                async with client as c:
                    resp = await c.post(
                        f"{_TRACES_URL}/{tid}/feedback",
                        json={
                            "feedback_type": "ADMIN_REVIEW",
                            "score": 4,
                            "label": "GOOD_EXTRACTION",
                            "comment": "Agent correctly extracted the lease and title.",
                        },
                    )
        finally:
            _restore()

        assert resp.status_code == 201
        body = resp.json()
        assert body["feedback_type"] == "ADMIN_REVIEW"
        assert body["score"] == 4
        assert body["label"] == "GOOD_EXTRACTION"
        assert body["trace_id"] == str(tid)

    @pytest.mark.asyncio
    async def test_feedback_for_unknown_trace_returns_404(self):
        client = _make_app_client()
        try:
            with patch(
                "app.observability.api.feedback.TraceRepository.get",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with client as c:
                    resp = await c.post(
                        f"{_TRACES_URL}/{uuid4()}/feedback",
                        json={"feedback_type": "ADMIN_REVIEW"},
                    )
        finally:
            _restore()

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_score_above_5_rejected(self):
        client = _make_app_client()
        try:
            async with client as c:
                resp = await c.post(
                    f"{_TRACES_URL}/{uuid4()}/feedback",
                    json={"feedback_type": "ADMIN_REVIEW", "score": 10},
                )
        finally:
            _restore()

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_feedback_type_rejected(self):
        client = _make_app_client()
        try:
            async with client as c:
                resp = await c.post(
                    f"{_TRACES_URL}/{uuid4()}/feedback",
                    json={"score": 3},
                )
        finally:
            _restore()

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_feedback_type_only_is_valid(self):
        tid = uuid4()
        trace = _mock_trace(trace_id=tid)
        fb = _mock_feedback(trace_id=tid)
        fb.score = None
        fb.label = None
        fb.comment = None
        fb.feedback_type = "THUMB_UP"

        client = _make_app_client()
        try:
            with (
                patch("app.observability.api.feedback.TraceRepository.get", new_callable=AsyncMock, return_value=trace),
                patch("app.observability.api.feedback.FeedbackRepository.create", new_callable=AsyncMock, return_value=fb),
            ):
                async with client as c:
                    resp = await c.post(
                        f"{_TRACES_URL}/{tid}/feedback",
                        json={"feedback_type": "THUMB_UP"},
                    )
        finally:
            _restore()

        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_feedback_repo_receives_correct_args(self):
        tid = uuid4()
        trace = _mock_trace(trace_id=tid)
        fb = _mock_feedback(trace_id=tid)
        captured: dict = {}

        async def _create(self, **kwargs):  # noqa: ANN001
            captured.update(kwargs)
            return fb

        client = _make_app_client()
        try:
            with (
                patch("app.observability.api.feedback.TraceRepository.get", new_callable=AsyncMock, return_value=trace),
                patch("app.observability.api.feedback.FeedbackRepository.create", new=_create),
            ):
                async with client as c:
                    await c.post(
                        f"{_TRACES_URL}/{tid}/feedback",
                        json={
                            "feedback_type": "ADMIN_REVIEW",
                            "score": 3,
                            "label": "PARTIAL_EXTRACTION",
                            "comment": "Missed one field.",
                        },
                    )
        finally:
            _restore()

        assert captured["trace_id"] == tid
        assert captured["feedback_type"] == "ADMIN_REVIEW"
        assert captured["score"] == 3
        assert captured["label"] == "PARTIAL_EXTRACTION"
        assert captured["comment"] == "Missed one field."
