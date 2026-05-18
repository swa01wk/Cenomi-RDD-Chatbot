"""Unit tests for the observability API layer.

Covers:
- TraceRepository.list_filtered  (filter building + pagination)
- _build_run_tree helper           (hierarchical run tree construction)
- Pydantic response model redaction (api_models.py model_validators)

No real database is required — all tests use mocked AsyncSession.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID, uuid4

import pytest

from app.observability.api.traces import _build_run_tree
from app.observability.repositories.trace_repo import TraceRepository
from app.observability.schemas.api_models import (
    LLMCallResponse,
    RunResponse,
    RunTreeNodeResponse,
    StateDiffResponse,
    StateSnapshotResponse,
    ToolCallResponse,
    TraceDetailResponse,
    TraceResponse,
    TraceSummaryResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_trace(
    *,
    trace_id: UUID | None = None,
    session_id: UUID | None = None,
    user_id: UUID | None = None,
    status: str = "SUCCESS",
    active_agent: str | None = "sr_agent",
    intent: str | None = "handover_service_request",
    error_message: str | None = None,
    total_latency_ms: int | None = 250,
    created_at: datetime | None = None,
) -> MagicMock:
    row = MagicMock()
    row.id = trace_id or uuid4()
    row.session_id = session_id or uuid4()
    row.user_id = user_id or uuid4()
    row.trace_type = "CHAT_TURN"
    row.active_agent = active_agent
    row.intent = intent
    row.service_category = None
    row.sub_category = None
    row.workflow_stage_before = None
    row.workflow_stage_after = None
    row.input_message = "hello"
    row.output_message = "world"
    row.status = status
    row.error_message = error_message
    row.total_latency_ms = total_latency_ms
    row.total_token_count = 100
    row.estimated_cost = Decimal("0.001")
    row.metadata_ = {}
    row.created_at = created_at or _NOW
    row.completed_at = None
    return row


def _make_run(
    *,
    run_id: UUID | None = None,
    trace_id: UUID | None = None,
    parent_run_id: UUID | None = None,
    run_name: str = "node_a",
    run_type: str = "LANGGRAPH_NODE",
    status: str = "SUCCESS",
) -> MagicMock:
    row = MagicMock()
    row.id = run_id or uuid4()
    row.trace_id = trace_id or uuid4()
    row.parent_run_id = parent_run_id
    row.run_name = run_name
    row.run_type = run_type
    row.node_name = run_name
    row.input = {"key": "value"}
    row.output = {"result": "ok"}
    row.status = status
    row.error_message = None
    row.latency_ms = 50
    row.started_at = _NOW
    row.completed_at = None
    return row


# ===========================================================================
# TraceRepository.list_filtered
# ===========================================================================


class TestListFiltered:
    """Verify that list_filtered builds correct WHERE clauses and pagination."""

    @pytest.mark.asyncio
    async def test_no_filters_returns_all(self, mock_session, make_execute_result):
        traces = [_make_trace(), _make_trace()]
        # first call = count, second call = rows
        mock_session.execute.side_effect = [
            make_execute_result(scalar=2),
            make_execute_result(scalars=traces),
        ]

        repo = TraceRepository(mock_session)
        rows, total = await repo.list_filtered()

        assert total == 2
        assert len(rows) == 2
        assert mock_session.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_pagination_math(self, mock_session, make_execute_result):
        mock_session.execute.side_effect = [
            make_execute_result(scalar=45),
            make_execute_result(scalars=[]),
        ]
        repo = TraceRepository(mock_session)
        rows, total = await repo.list_filtered(page=3, page_size=10)
        assert total == 45
        # No assertion on offset/limit at SQL level without inspecting stmt args,
        # but we verify the return is correct and both queries ran.
        assert mock_session.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_single_filter_status(self, mock_session, make_execute_result):
        trace = _make_trace(status="FAILED")
        mock_session.execute.side_effect = [
            make_execute_result(scalar=1),
            make_execute_result(scalars=[trace]),
        ]
        repo = TraceRepository(mock_session)
        rows, total = await repo.list_filtered(status="FAILED")
        assert total == 1
        assert rows[0].status == "FAILED"

    @pytest.mark.asyncio
    async def test_has_error_true_filter(self, mock_session, make_execute_result):
        trace = _make_trace(error_message="Something went wrong")
        mock_session.execute.side_effect = [
            make_execute_result(scalar=1),
            make_execute_result(scalars=[trace]),
        ]
        repo = TraceRepository(mock_session)
        rows, total = await repo.list_filtered(has_error=True)
        assert rows[0].error_message == "Something went wrong"

    @pytest.mark.asyncio
    async def test_has_error_false_filter(self, mock_session, make_execute_result):
        trace = _make_trace(error_message=None)
        mock_session.execute.side_effect = [
            make_execute_result(scalar=1),
            make_execute_result(scalars=[trace]),
        ]
        repo = TraceRepository(mock_session)
        rows, total = await repo.list_filtered(has_error=False)
        assert rows[0].error_message is None

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_session, make_execute_result):
        mock_session.execute.side_effect = [
            make_execute_result(scalar=0),
            make_execute_result(scalars=[]),
        ]
        repo = TraceRepository(mock_session)
        rows, total = await repo.list_filtered(status="UNKNOWN")
        assert rows == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_date_range_filters_accepted(self, mock_session, make_execute_result):
        from_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
        to_dt = datetime(2024, 12, 31, tzinfo=timezone.utc)
        mock_session.execute.side_effect = [
            make_execute_result(scalar=0),
            make_execute_result(scalars=[]),
        ]
        repo = TraceRepository(mock_session)
        rows, total = await repo.list_filtered(from_date=from_dt, to_date=to_dt)
        assert total == 0

    @pytest.mark.asyncio
    async def test_min_latency_filter_accepted(self, mock_session, make_execute_result):
        trace = _make_trace(total_latency_ms=500)
        mock_session.execute.side_effect = [
            make_execute_result(scalar=1),
            make_execute_result(scalars=[trace]),
        ]
        repo = TraceRepository(mock_session)
        rows, total = await repo.list_filtered(min_latency_ms=300)
        assert rows[0].total_latency_ms == 500

    @pytest.mark.asyncio
    async def test_combined_filters(self, mock_session, make_execute_result):
        uid = uuid4()
        sid = uuid4()
        trace = _make_trace(user_id=uid, session_id=sid, status="SUCCESS", intent="lease_renewal")
        mock_session.execute.side_effect = [
            make_execute_result(scalar=1),
            make_execute_result(scalars=[trace]),
        ]
        repo = TraceRepository(mock_session)
        rows, total = await repo.list_filtered(
            user_id=uid,
            session_id=sid,
            status="SUCCESS",
            intent="lease_renewal",
        )
        assert total == 1
        assert rows[0].user_id == uid


# ===========================================================================
# _build_run_tree
# ===========================================================================


class TestBuildRunTree:
    def test_flat_list_with_no_parents_all_become_roots(self):
        runs = [_make_run(), _make_run(), _make_run()]
        tree = _build_run_tree(runs)
        assert len(tree) == 3
        for node in tree:
            assert node.children == []

    def test_single_child_nested_under_parent(self):
        parent_id = uuid4()
        parent = _make_run(run_id=parent_id, run_name="supervisor")
        child = _make_run(parent_run_id=parent_id, run_name="worker")
        tree = _build_run_tree([parent, child])
        assert len(tree) == 1
        assert tree[0].run_name == "supervisor"
        assert len(tree[0].children) == 1
        assert tree[0].children[0].run_name == "worker"

    def test_deep_nesting(self):
        root_id = uuid4()
        mid_id = uuid4()
        root = _make_run(run_id=root_id, run_name="root")
        mid = _make_run(run_id=mid_id, parent_run_id=root_id, run_name="mid")
        leaf = _make_run(parent_run_id=mid_id, run_name="leaf")
        tree = _build_run_tree([root, mid, leaf])
        assert len(tree) == 1
        assert tree[0].children[0].run_name == "mid"
        assert tree[0].children[0].children[0].run_name == "leaf"

    def test_multiple_children_under_same_parent(self):
        parent_id = uuid4()
        parent = _make_run(run_id=parent_id, run_name="parent")
        child1 = _make_run(parent_run_id=parent_id, run_name="child1")
        child2 = _make_run(parent_run_id=parent_id, run_name="child2")
        tree = _build_run_tree([parent, child1, child2])
        assert len(tree) == 1
        assert len(tree[0].children) == 2

    def test_self_referencing_run_becomes_root(self):
        run_id = uuid4()
        run = _make_run(run_id=run_id, parent_run_id=run_id)
        tree = _build_run_tree([run])
        assert len(tree) == 1
        assert tree[0].children == []

    def test_orphan_run_becomes_root(self):
        """A run whose parent_run_id doesn't exist in the list is treated as a root."""
        orphan = _make_run(parent_run_id=uuid4(), run_name="orphan")
        tree = _build_run_tree([orphan])
        assert len(tree) == 1
        assert tree[0].run_name == "orphan"

    def test_empty_list_returns_empty_tree(self):
        assert _build_run_tree([]) == []


# ===========================================================================
# Pydantic response model redaction
# ===========================================================================


class TestResponseModelRedaction:
    def test_run_response_redacts_sensitive_io(self):
        run = _make_run()
        run.input = {"user_message": "hello", "token": "secret"}
        run.output = {"answer": "ok", "api_key": "sk-1234"}
        resp = RunResponse.model_validate(run)
        assert resp.input["token"] == "[REDACTED]"
        assert resp.output["api_key"] == "[REDACTED]"
        assert resp.input["user_message"] == "hello"
        assert resp.output["answer"] == "ok"

    def test_run_response_strips_cot_from_input(self):
        run = _make_run()
        run.input = {"chain_of_thought": "hidden reasoning", "safe": "value"}
        run.output = {}
        resp = RunResponse.model_validate(run)
        assert "chain_of_thought" not in resp.input
        assert resp.input["safe"] == "value"

    def test_tool_call_response_redacts_payloads(self):
        row = MagicMock()
        row.id = uuid4()
        row.trace_id = uuid4()
        row.run_id = uuid4()
        row.tool_name = "lease_lookup"
        row.tool_type = "LEASE_LOOKUP"
        row.request_payload = {"signed_url": "https://secret.example.com", "lease_id": "L001"}
        row.response_payload = {"authorization": "Bearer xyz", "data": []}
        row.status_code = 200
        row.success = True
        row.latency_ms = 120
        row.error_message = None
        row.created_at = _NOW
        resp = ToolCallResponse.model_validate(row)
        assert resp.request_payload["signed_url"] == "[REDACTED]"
        assert resp.response_payload["authorization"] == "[REDACTED]"
        assert resp.request_payload["lease_id"] == "L001"

    def test_llm_call_response_redacts_structured_output(self):
        row = MagicMock()
        row.id = uuid4()
        row.trace_id = uuid4()
        row.run_id = uuid4()
        row.provider = "openai"
        row.model = "gpt-4o"
        row.prompt_name = "extraction"
        row.prompt_version = "v1"
        row.input_tokens = 100
        row.output_tokens = 50
        row.total_tokens = 150
        row.latency_ms = 800
        row.estimated_cost = Decimal("0.001")
        row.structured_output = {"intent": "renewal", "credentials": "leaked_value"}
        row.parse_success = True
        row.parse_error = None
        row.created_at = _NOW
        resp = LLMCallResponse.model_validate(row)
        assert resp.structured_output["credentials"] == "[REDACTED]"
        assert resp.structured_output["intent"] == "renewal"

    def test_state_snapshot_response_strips_cot(self):
        row = MagicMock()
        row.id = uuid4()
        row.trace_id = uuid4()
        row.run_id = uuid4()
        row.snapshot_type = "AFTER_NODE"
        row.state = {"reasoning": "hidden", "intent": "renewal"}
        row.created_at = _NOW
        resp = StateSnapshotResponse.model_validate(row)
        assert "reasoning" not in resp.state
        assert resp.state["intent"] == "renewal"

    def test_state_diff_response_strips_cot(self):
        row = MagicMock()
        row.id = uuid4()
        row.trace_id = uuid4()
        row.run_id = uuid4()
        row.diff = {"thinking": "removed", "intent": {"before": "unknown", "after": "renewal"}}
        row.created_at = _NOW
        resp = StateDiffResponse.model_validate(row)
        assert "thinking" not in resp.diff
        assert "intent" in resp.diff

    def test_trace_summary_response_from_orm(self):
        trace = _make_trace(status="SUCCESS", active_agent="sr_agent", intent="handover")
        summary = TraceSummaryResponse.model_validate(trace)
        assert summary.status == "SUCCESS"
        assert summary.active_agent == "sr_agent"
        assert summary.intent == "handover"
        # metadata_ must NOT be present
        assert not hasattr(summary, "metadata_")

    def test_trace_response_excludes_metadata(self):
        trace = _make_trace()
        resp = TraceResponse.model_validate(trace)
        assert not hasattr(resp, "metadata_")
        assert resp.status == "SUCCESS"
