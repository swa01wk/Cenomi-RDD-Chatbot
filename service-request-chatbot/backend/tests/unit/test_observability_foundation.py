"""Unit tests for the observability foundation layer.

Covers:
- redact_payload  (redaction.py)
- build_json_diff (state_diff.py)
- @trace_node     (decorators.py)

No database connection or real TraceManager is required.
AsyncMock is used to simulate TraceManager behaviour.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from app.observability.redaction import redact_payload, sanitise, strip_cot
from app.observability.state_diff import build_json_diff, shallow_dict_diff
from app.observability.decorators import trace_node


# ===========================================================================
# redact_payload
# ===========================================================================


class TestRedactPayload:
    def test_sensitive_key_is_redacted(self):
        result = redact_payload({"password": "secret123"})
        assert result["password"] == "[REDACTED]"

    def test_all_eleven_sensitive_keys(self):
        keys = [
            "authorization",
            "access_token",
            "refresh_token",
            "cookie",
            "password",
            "secret",
            "api_key",
            "signed_url",
            "token",
            "credentials",
            "connection_string",
        ]
        payload = {k: f"value_{k}" for k in keys}
        result = redact_payload(payload)
        for k in keys:
            assert result[k] == "[REDACTED]", f"key '{k}' was not redacted"

    def test_non_sensitive_key_is_preserved(self):
        result = redact_payload({"user_id": "abc", "intent": "lease_renewal"})
        assert result["user_id"] == "abc"
        assert result["intent"] == "lease_renewal"

    def test_case_insensitive_key_matching(self):
        result = redact_payload({"Password": "s3cr3t", "ACCESS_TOKEN": "tok"})
        assert result["Password"] == "[REDACTED]"
        assert result["ACCESS_TOKEN"] == "[REDACTED]"

    def test_nested_dict_is_recursed(self):
        payload = {"outer": {"inner": {"password": "hunter2", "name": "Alice"}}}
        result = redact_payload(payload)
        assert result["outer"]["inner"]["password"] == "[REDACTED]"
        assert result["outer"]["inner"]["name"] == "Alice"

    def test_list_elements_are_recursed(self):
        payload = [{"token": "abc"}, {"safe": "value"}]
        result = redact_payload(payload)
        assert result[0]["token"] == "[REDACTED]"
        assert result[1]["safe"] == "value"

    def test_list_nested_in_dict(self):
        payload = {"items": [{"api_key": "k1"}, {"data": 42}]}
        result = redact_payload(payload)
        assert result["items"][0]["api_key"] == "[REDACTED]"
        assert result["items"][1]["data"] == 42

    def test_primitives_passed_through(self):
        assert redact_payload("hello") == "hello"
        assert redact_payload(42) == 42
        assert redact_payload(None) is None
        assert redact_payload(3.14) == 3.14
        assert redact_payload(True) is True

    def test_empty_dict(self):
        assert redact_payload({}) == {}

    def test_empty_list(self):
        assert redact_payload([]) == []

    def test_original_dict_not_mutated(self):
        original = {"password": "secret", "name": "Bob"}
        redact_payload(original)
        assert original["password"] == "secret"

    def test_sanitise_strips_cot_and_redacts(self):
        payload = {
            "chain_of_thought": "hidden reasoning",
            "password": "s3cr3t",
            "intent": "renewal",
        }
        result = sanitise(payload)
        assert "chain_of_thought" not in result
        assert result["password"] == "[REDACTED]"
        assert result["intent"] == "renewal"

    def test_strip_cot_removes_only_cot_keys(self):
        payload = {"reasoning": "...", "thinking": "...", "name": "test"}
        result = strip_cot(payload)
        assert "reasoning" not in result
        assert "thinking" not in result
        assert result["name"] == "test"


# ===========================================================================
# build_json_diff
# ===========================================================================


class TestBuildJsonDiff:
    def test_added_key(self):
        before = {"a": 1}
        after = {"a": 1, "b": 2}
        diff = build_json_diff(before, after)
        assert diff["added"] == {"b": 2}
        assert diff["changed"] == {}
        assert diff["removed"] == {}

    def test_removed_key(self):
        before = {"a": 1, "b": 2}
        after = {"a": 1}
        diff = build_json_diff(before, after)
        assert diff["removed"] == {"b": 2}
        assert diff["added"] == {}
        assert diff["changed"] == {}

    def test_changed_key(self):
        before = {"a": 1}
        after = {"a": 99}
        diff = build_json_diff(before, after)
        assert diff["changed"] == {"a": {"before": 1, "after": 99}}
        assert diff["added"] == {}
        assert diff["removed"] == {}

    def test_unchanged_key_excluded(self):
        before = {"a": 1, "b": 2}
        after = {"a": 1, "b": 3}
        diff = build_json_diff(before, after)
        assert "a" not in diff["changed"]
        assert "a" not in diff["added"]
        assert "a" not in diff["removed"]
        assert diff["changed"]["b"] == {"before": 2, "after": 3}

    def test_empty_states_produce_empty_diff(self):
        diff = build_json_diff({}, {})
        assert diff == {"added": {}, "changed": {}, "removed": {}}

    def test_identical_states_produce_empty_diff(self):
        state = {"x": 1, "y": "hello"}
        diff = build_json_diff(state, state)
        assert diff == {"added": {}, "changed": {}, "removed": {}}

    def test_combined_add_change_remove(self):
        before = {"keep": "same", "change": "old", "drop": "gone"}
        after = {"keep": "same", "change": "new", "fresh": "added"}
        diff = build_json_diff(before, after)
        assert diff["added"] == {"fresh": "added"}
        assert diff["changed"] == {"change": {"before": "old", "after": "new"}}
        assert diff["removed"] == {"drop": "gone"}

    def test_none_value_can_be_added(self):
        diff = build_json_diff({}, {"key": None})
        assert diff["added"] == {"key": None}

    def test_shallow_dict_diff_alias_still_works(self):
        before = {"a": 1}
        after = {"a": 2, "b": 3}
        result = shallow_dict_diff(before, after)
        assert "a" in result
        assert result["a"] == {"before": 1, "after": 2}


# ===========================================================================
# @trace_node decorator
# ===========================================================================


def _make_trace_manager(run_id: UUID | None = None) -> MagicMock:
    """Return a MagicMock with all TraceManager async methods pre-configured."""
    tm = MagicMock()
    _run_id = run_id or uuid4()
    tm.start_run = AsyncMock(return_value=_run_id)
    tm.finish_run = AsyncMock(return_value=None)
    tm.capture_state_snapshot = AsyncMock(return_value=None)
    tm.capture_state_diff = AsyncMock(return_value=None)
    tm._run_id = _run_id
    return tm


class TestTraceNodeDecorator:
    @pytest.mark.asyncio
    async def test_happy_path_executes_node(self):
        tm = _make_trace_manager()
        trace_id = uuid4()

        @trace_node("test_node", "LANGGRAPH_NODE")
        async def my_node(state):
            return {"result": "ok"}

        result = await my_node({"trace_manager": tm, "trace_id": str(trace_id)})
        assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_happy_path_calls_start_and_finish_run(self):
        tm = _make_trace_manager()
        trace_id = uuid4()

        @trace_node("my_node", "LANGGRAPH_NODE")
        async def my_node(state):
            return {}

        await my_node({"trace_manager": tm, "trace_id": str(trace_id)})

        tm.start_run.assert_awaited_once()
        assert tm.finish_run.await_args.kwargs.get("status") == "SUCCESS" or \
               tm.finish_run.call_args[1].get("status") == "SUCCESS"

    @pytest.mark.asyncio
    async def test_happy_path_captures_before_and_after_snapshots(self):
        tm = _make_trace_manager()
        trace_id = uuid4()

        @trace_node("snap_node", "LANGGRAPH_NODE")
        async def snap_node(state):
            return {"new_key": "new_value"}

        await snap_node({"trace_manager": tm, "trace_id": str(trace_id)})

        calls = [c.kwargs.get("snapshot_type") or c.args[2]
                 for c in tm.capture_state_snapshot.await_args_list]
        assert "BEFORE_NODE" in calls
        assert "AFTER_NODE" in calls

    @pytest.mark.asyncio
    async def test_happy_path_captures_state_diff(self):
        tm = _make_trace_manager()
        trace_id = uuid4()

        @trace_node("diff_node", "LANGGRAPH_NODE")
        async def diff_node(state):
            return {"added_key": "value"}

        await diff_node({"trace_manager": tm, "trace_id": str(trace_id)})
        tm.capture_state_diff.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_marks_run_failed_and_reraises(self):
        tm = _make_trace_manager()
        trace_id = uuid4()

        @trace_node("fail_node", "LANGGRAPH_NODE")
        async def fail_node(state):
            raise ValueError("something went wrong")

        with pytest.raises(ValueError, match="something went wrong"):
            await fail_node({"trace_manager": tm, "trace_id": str(trace_id)})

        finish_call = tm.finish_run.await_args
        assert finish_call is not None
        status = finish_call.kwargs.get("status") or finish_call.args[1] if finish_call.args else None
        if status is None:
            kwargs = tm.finish_run.call_args[1]
            status = kwargs.get("status")
        assert status == "FAILED"

    @pytest.mark.asyncio
    async def test_exception_does_not_swallow_original_error(self):
        tm = _make_trace_manager()
        trace_id = uuid4()

        @trace_node("err_node", "LANGGRAPH_NODE")
        async def err_node(state):
            raise RuntimeError("critical failure")

        with pytest.raises(RuntimeError, match="critical failure"):
            await err_node({"trace_manager": tm, "trace_id": str(trace_id)})

    @pytest.mark.asyncio
    async def test_no_trace_manager_in_state_node_still_executes(self):
        @trace_node("plain_node", "LANGGRAPH_NODE")
        async def plain_node(state):
            return {"executed": True}

        result = await plain_node({"user_id": "abc"})
        assert result == {"executed": True}

    @pytest.mark.asyncio
    async def test_no_trace_id_in_state_skips_tracing(self):
        tm = _make_trace_manager()

        @trace_node("no_trace_id", "LANGGRAPH_NODE")
        async def no_trace_id_node(state):
            return {"done": True}

        result = await no_trace_id_node({"trace_manager": tm})
        assert result == {"done": True}
        tm.start_run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tracing_failure_does_not_crash_node(self):
        tm = MagicMock()
        tm.start_run = AsyncMock(side_effect=Exception("DB down"))
        tm.finish_run = AsyncMock(return_value=None)
        tm.capture_state_snapshot = AsyncMock(return_value=None)
        tm.capture_state_diff = AsyncMock(return_value=None)
        trace_id = uuid4()

        @trace_node("resilient_node", "LANGGRAPH_NODE")
        async def resilient_node(state):
            return {"resilient": True}

        result = await resilient_node({"trace_manager": tm, "trace_id": str(trace_id)})
        assert result == {"resilient": True}

    @pytest.mark.asyncio
    async def test_state_without_dict_first_arg_node_still_executes(self):
        @trace_node("no_state_node", "LANGGRAPH_NODE")
        async def no_state_node():
            return {"ok": True}

        result = await no_state_node()
        assert result == {"ok": True}
