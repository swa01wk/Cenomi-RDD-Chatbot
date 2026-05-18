"""Unit tests for app.observability.trace_manager.TraceManager.

Coverage
--------
TestTraceLifecycle   — start_trace, finish_trace, fail_trace: repo delegation,
                       UUID return, status values, error swallowing.
TestRunLifecycle     — start_run, finish_run: latency computation, start-time
                       bookkeeping, missing-start graceful handling.
TestStateCapture     — capture_state_snapshot (sanitize call, run_id=None skip),
                       capture_state_diff (build_json_diff delegation, both-state
                       sanitization).
TestCallCapture      — capture_tool_call, capture_llm_call: kwarg delegation,
                       error swallowing.
TestCurrentTraceId   — returns None before start; tracks last-started UUID;
                       unchanged after failed start.

No database, no network.  All six repos are replaced with AsyncMock instances
injected directly onto the TraceManager instance after construction.
"""

from __future__ import annotations

import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.trace_manager import TraceManager


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _make_tm() -> tuple[TraceManager, dict[str, AsyncMock]]:
    """Return (TraceManager, repos_dict) with all repos replaced by AsyncMock."""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()

    tm = TraceManager(session)

    from app.observability.repositories.llm_call_repo import LLMCallRepository
    from app.observability.repositories.run_repo import RunRepository
    from app.observability.repositories.state_diff_repo import StateDiffRepository
    from app.observability.repositories.state_snapshot_repo import StateSnapshotRepository
    from app.observability.repositories.tool_call_repo import ToolCallRepository
    from app.observability.repositories.trace_repo import TraceRepository

    repos: dict[str, AsyncMock] = {
        "trace": AsyncMock(spec=TraceRepository),
        "run": AsyncMock(spec=RunRepository),
        "snapshot": AsyncMock(spec=StateSnapshotRepository),
        "diff": AsyncMock(spec=StateDiffRepository),
        "tool": AsyncMock(spec=ToolCallRepository),
        "llm": AsyncMock(spec=LLMCallRepository),
    }

    tm._trace_repo = repos["trace"]
    tm._run_repo = repos["run"]
    tm._snapshot_repo = repos["snapshot"]
    tm._diff_repo = repos["diff"]
    tm._tool_repo = repos["tool"]
    tm._llm_repo = repos["llm"]

    return tm, repos


def _trace_row(trace_id: UUID | None = None) -> MagicMock:
    row = MagicMock()
    row.id = trace_id or uuid4()
    return row


def _run_row(run_id: UUID | None = None) -> MagicMock:
    row = MagicMock()
    row.id = run_id or uuid4()
    return row


# ===========================================================================
# TestTraceLifecycle
# ===========================================================================


class TestTraceLifecycle:
    @pytest.mark.asyncio
    async def test_start_trace_returns_uuid(self) -> None:
        tm, repos = _make_tm()
        expected = uuid4()
        repos["trace"].create = AsyncMock(return_value=_trace_row(expected))

        result = await tm.start_trace(session_id=uuid4(), user_id=uuid4(), input_message="hello")

        assert result == expected

    @pytest.mark.asyncio
    async def test_start_trace_sets_active_trace_id(self) -> None:
        tm, repos = _make_tm()
        trace_id = uuid4()
        repos["trace"].create = AsyncMock(return_value=_trace_row(trace_id))

        assert tm.current_trace_id() is None
        await tm.start_trace(session_id=uuid4(), user_id=uuid4(), input_message="msg")
        assert tm.current_trace_id() == trace_id

    @pytest.mark.asyncio
    async def test_start_trace_passes_in_progress_status_to_repo(self) -> None:
        tm, repos = _make_tm()
        session_id = uuid4()
        user_id = uuid4()
        repos["trace"].create = AsyncMock(return_value=_trace_row())

        await tm.start_trace(session_id=session_id, user_id=user_id, input_message="msg")

        repos["trace"].create.assert_awaited_once()
        kw = repos["trace"].create.call_args.kwargs
        assert kw["status"] == "IN_PROGRESS"
        assert kw["session_id"] == session_id
        assert kw["user_id"] == user_id
        assert kw["input_message"] == "msg"

    @pytest.mark.asyncio
    async def test_start_trace_converts_string_ids_to_uuid(self) -> None:
        tm, repos = _make_tm()
        repos["trace"].create = AsyncMock(return_value=_trace_row())
        session_str = str(uuid4())
        user_str = str(uuid4())

        await tm.start_trace(session_id=session_str, user_id=user_str, input_message="msg")

        kw = repos["trace"].create.call_args.kwargs
        assert isinstance(kw["session_id"], UUID)
        assert isinstance(kw["user_id"], UUID)

    @pytest.mark.asyncio
    async def test_start_trace_passes_metadata_to_repo(self) -> None:
        tm, repos = _make_tm()
        repos["trace"].create = AsyncMock(return_value=_trace_row())

        await tm.start_trace(
            session_id=uuid4(),
            user_id=uuid4(),
            input_message="hi",
            metadata={"attachments_count": 2},
        )

        kw = repos["trace"].create.call_args.kwargs
        assert kw["metadata"] == {"attachments_count": 2}

    @pytest.mark.asyncio
    async def test_start_trace_repo_failure_returns_none(self) -> None:
        tm, repos = _make_tm()
        repos["trace"].create = AsyncMock(side_effect=RuntimeError("DB down"))

        result = await tm.start_trace(session_id=uuid4(), user_id=uuid4(), input_message="x")
        assert result is None

    @pytest.mark.asyncio
    async def test_start_trace_repo_failure_does_not_raise(self) -> None:
        tm, repos = _make_tm()
        repos["trace"].create = AsyncMock(side_effect=Exception("fatal DB error"))

        # Must not raise
        result = await tm.start_trace(session_id=uuid4(), user_id=uuid4(), input_message="x")
        assert result is None

    @pytest.mark.asyncio
    async def test_finish_trace_calls_repo_complete_with_success_status(self) -> None:
        tm, repos = _make_tm()
        trace_id = uuid4()
        repos["trace"].complete = AsyncMock()

        await tm.finish_trace(trace_id=trace_id, output_message="Done")

        repos["trace"].complete.assert_awaited_once()
        args = repos["trace"].complete.call_args
        assert args.args[0] == trace_id
        assert args.kwargs.get("status") == "SUCCESS"
        assert args.kwargs.get("output_message") == "Done"

    @pytest.mark.asyncio
    async def test_finish_trace_custom_status_forwarded(self) -> None:
        tm, repos = _make_tm()
        repos["trace"].complete = AsyncMock()

        await tm.finish_trace(trace_id=uuid4(), output_message="ok", status="PARTIAL")

        kw = repos["trace"].complete.call_args.kwargs
        assert kw["status"] == "PARTIAL"

    @pytest.mark.asyncio
    async def test_finish_trace_with_final_state_does_not_raise(self) -> None:
        """Snapshot path (run_id=None) must be silently skipped — no crash."""
        tm, repos = _make_tm()
        repos["trace"].complete = AsyncMock()

        await tm.finish_trace(
            trace_id=uuid4(),
            output_message="done",
            final_state={"status": "SUBMITTED", "workflow_stage": "SR_CREATED"},
        )

        repos["trace"].complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_finish_trace_repo_failure_does_not_raise(self) -> None:
        tm, repos = _make_tm()
        repos["trace"].complete = AsyncMock(side_effect=RuntimeError("DB down"))

        await tm.finish_trace(trace_id=uuid4(), output_message="ok")  # must not raise

    @pytest.mark.asyncio
    async def test_fail_trace_calls_repo_complete_with_failed_status(self) -> None:
        tm, repos = _make_tm()
        trace_id = uuid4()
        repos["trace"].complete = AsyncMock()

        await tm.fail_trace(trace_id=trace_id, error_message="Something broke")

        repos["trace"].complete.assert_awaited_once()
        kw = repos["trace"].complete.call_args.kwargs
        assert kw["status"] == "FAILED"
        assert kw["error_message"] == "Something broke"

    @pytest.mark.asyncio
    async def test_fail_trace_repo_failure_does_not_raise(self) -> None:
        tm, repos = _make_tm()
        repos["trace"].complete = AsyncMock(side_effect=RuntimeError("DB down"))

        await tm.fail_trace(trace_id=uuid4(), error_message="err")  # must not raise


# ===========================================================================
# TestRunLifecycle
# ===========================================================================


class TestRunLifecycle:
    @pytest.mark.asyncio
    async def test_start_run_returns_run_uuid(self) -> None:
        tm, repos = _make_tm()
        run_id = uuid4()
        repos["run"].create = AsyncMock(return_value=_run_row(run_id))

        result = await tm.start_run(
            trace_id=uuid4(), run_name="supervisor_node", run_type="LANGGRAPH_NODE"
        )

        assert result == run_id

    @pytest.mark.asyncio
    async def test_start_run_records_start_time(self) -> None:
        tm, repos = _make_tm()
        run_id = uuid4()
        repos["run"].create = AsyncMock(return_value=_run_row(run_id))

        t_before = time.monotonic()
        await tm.start_run(trace_id=uuid4(), run_name="n", run_type="LANGGRAPH_NODE")
        t_after = time.monotonic()

        assert run_id in tm._run_start_times
        assert t_before <= tm._run_start_times[run_id] <= t_after

    @pytest.mark.asyncio
    async def test_start_run_forwards_kwargs_to_repo(self) -> None:
        tm, repos = _make_tm()
        trace_id = uuid4()
        parent_id = uuid4()
        repos["run"].create = AsyncMock(return_value=_run_row())

        await tm.start_run(
            trace_id=trace_id,
            run_name="field_extraction_node",
            run_type="LANGGRAPH_NODE",
            parent_run_id=parent_id,
            input={"user_message": "test"},
        )

        kw = repos["run"].create.call_args.kwargs
        assert kw["trace_id"] == trace_id
        assert kw["run_name"] == "field_extraction_node"
        assert kw["parent_run_id"] == parent_id

    @pytest.mark.asyncio
    async def test_finish_run_calls_repo_complete(self) -> None:
        tm, repos = _make_tm()
        run_id = uuid4()
        repos["run"].create = AsyncMock(return_value=_run_row(run_id))
        repos["run"].complete = AsyncMock()

        await tm.start_run(trace_id=uuid4(), run_name="n", run_type="LANGGRAPH_NODE")
        await tm.finish_run(run_id=run_id, status="SUCCESS")

        repos["run"].complete.assert_awaited_once()
        args = repos["run"].complete.call_args
        assert args.args[0] == run_id
        assert args.kwargs.get("status") == "SUCCESS"

    @pytest.mark.asyncio
    async def test_finish_run_computes_non_negative_latency_ms(self) -> None:
        tm, repos = _make_tm()
        run_id = uuid4()
        repos["run"].create = AsyncMock(return_value=_run_row(run_id))
        repos["run"].complete = AsyncMock()

        await tm.start_run(trace_id=uuid4(), run_name="n", run_type="LANGGRAPH_NODE")
        await tm.finish_run(run_id=run_id, status="SUCCESS")

        latency = repos["run"].complete.call_args.kwargs.get("latency_ms")
        assert latency is not None
        assert latency >= 0

    @pytest.mark.asyncio
    async def test_finish_run_without_prior_start_uses_none_latency(self) -> None:
        tm, repos = _make_tm()
        run_id = uuid4()
        repos["run"].complete = AsyncMock()

        # finish_run on a run that was never started
        await tm.finish_run(run_id=run_id, status="SUCCESS")

        latency = repos["run"].complete.call_args.kwargs.get("latency_ms")
        assert latency is None

    @pytest.mark.asyncio
    async def test_finish_run_removes_start_time_entry(self) -> None:
        tm, repos = _make_tm()
        run_id = uuid4()
        repos["run"].create = AsyncMock(return_value=_run_row(run_id))
        repos["run"].complete = AsyncMock()

        await tm.start_run(trace_id=uuid4(), run_name="n", run_type="LANGGRAPH_NODE")
        assert run_id in tm._run_start_times

        await tm.finish_run(run_id=run_id)
        assert run_id not in tm._run_start_times

    @pytest.mark.asyncio
    async def test_finish_run_default_status_is_success(self) -> None:
        tm, repos = _make_tm()
        run_id = uuid4()
        repos["run"].complete = AsyncMock()

        await tm.finish_run(run_id=run_id)  # no explicit status

        kw = repos["run"].complete.call_args.kwargs
        assert kw.get("status") == "SUCCESS"

    @pytest.mark.asyncio
    async def test_start_run_repo_failure_returns_none(self) -> None:
        tm, repos = _make_tm()
        repos["run"].create = AsyncMock(side_effect=RuntimeError("DB down"))

        result = await tm.start_run(trace_id=uuid4(), run_name="n", run_type="T")
        assert result is None

    @pytest.mark.asyncio
    async def test_finish_run_repo_failure_does_not_raise(self) -> None:
        tm, repos = _make_tm()
        repos["run"].complete = AsyncMock(side_effect=RuntimeError("DB down"))

        await tm.finish_run(run_id=uuid4())  # must not raise


# ===========================================================================
# TestStateCapture
# ===========================================================================


class TestStateCapture:
    @pytest.mark.asyncio
    async def test_capture_state_snapshot_calls_sanitize_state(self) -> None:
        tm, repos = _make_tm()
        run_id = uuid4()
        repos["snapshot"].create = AsyncMock()

        with patch(
            "app.observability.trace_manager.sanitize_state_for_trace",
            return_value={"clean": "state"},
        ) as mock_sanitize:
            await tm.capture_state_snapshot(
                trace_id=uuid4(),
                run_id=run_id,
                snapshot_type="BEFORE_NODE",
                state={"password": "secret", "status": "IN_PROGRESS"},
            )

        mock_sanitize.assert_called_once()

    @pytest.mark.asyncio
    async def test_capture_state_snapshot_persists_sanitized_state(self) -> None:
        tm, repos = _make_tm()
        run_id = uuid4()
        trace_id = uuid4()
        repos["snapshot"].create = AsyncMock()

        with patch(
            "app.observability.trace_manager.sanitize_state_for_trace",
            return_value={"status": "IN_PROGRESS"},
        ):
            await tm.capture_state_snapshot(
                trace_id=trace_id,
                run_id=run_id,
                snapshot_type="AFTER_NODE",
                state={"status": "IN_PROGRESS"},
            )

        repos["snapshot"].create.assert_awaited_once()
        kw = repos["snapshot"].create.call_args.kwargs
        assert kw["trace_id"] == trace_id
        assert kw["run_id"] == run_id
        assert kw["snapshot_type"] == "AFTER_NODE"

    @pytest.mark.asyncio
    async def test_capture_state_snapshot_skips_when_run_id_is_none(self) -> None:
        tm, repos = _make_tm()
        repos["snapshot"].create = AsyncMock()

        await tm.capture_state_snapshot(
            trace_id=uuid4(),
            run_id=None,  # type: ignore[arg-type]
            snapshot_type="BEFORE_NODE",
            state={"x": 1},
        )

        repos["snapshot"].create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_capture_state_snapshot_repo_failure_does_not_raise(self) -> None:
        tm, repos = _make_tm()
        repos["snapshot"].create = AsyncMock(side_effect=RuntimeError("DB down"))

        with patch(
            "app.observability.trace_manager.sanitize_state_for_trace",
            return_value={"x": 1},
        ):
            await tm.capture_state_snapshot(
                trace_id=uuid4(), run_id=uuid4(), snapshot_type="AFTER_NODE", state={"x": 1}
            )  # must not raise

    @pytest.mark.asyncio
    async def test_capture_state_diff_calls_build_json_diff(self) -> None:
        tm, repos = _make_tm()
        repos["diff"].create = AsyncMock()
        expected_diff = {"added": {}, "changed": {"status": {"before": "A", "after": "B"}}, "removed": {}}

        with patch(
            "app.observability.trace_manager.sanitize_state_for_trace", side_effect=lambda s: s
        ):
            with patch(
                "app.observability.trace_manager.build_json_diff",
                return_value=expected_diff,
            ) as mock_diff:
                await tm.capture_state_diff(
                    trace_id=uuid4(),
                    run_id=uuid4(),
                    before_state={"status": "A"},
                    after_state={"status": "B"},
                )

        mock_diff.assert_called_once()

    @pytest.mark.asyncio
    async def test_capture_state_diff_sanitizes_both_states(self) -> None:
        tm, repos = _make_tm()
        repos["diff"].create = AsyncMock()
        sanitize_inputs: list = []

        def _fake_sanitize(state: dict) -> dict:
            sanitize_inputs.append(state)
            return {k: v for k, v in state.items() if k != "password"}

        with patch("app.observability.trace_manager.sanitize_state_for_trace", side_effect=_fake_sanitize):
            with patch("app.observability.trace_manager.build_json_diff", return_value={}):
                await tm.capture_state_diff(
                    trace_id=uuid4(),
                    run_id=uuid4(),
                    before_state={"status": "A", "password": "old"},
                    after_state={"status": "B", "password": "new"},
                )

        assert len(sanitize_inputs) == 2

    @pytest.mark.asyncio
    async def test_capture_state_diff_persists_diff(self) -> None:
        tm, repos = _make_tm()
        trace_id = uuid4()
        run_id = uuid4()
        repos["diff"].create = AsyncMock()
        fake_diff = {"added": {"new_key": "val"}, "changed": {}, "removed": {}}

        with patch("app.observability.trace_manager.sanitize_state_for_trace", side_effect=lambda s: s):
            with patch("app.observability.trace_manager.build_json_diff", return_value=fake_diff):
                await tm.capture_state_diff(
                    trace_id=trace_id, run_id=run_id, before_state={}, after_state={"new_key": "val"}
                )

        repos["diff"].create.assert_awaited_once()
        kw = repos["diff"].create.call_args.kwargs
        assert kw["trace_id"] == trace_id
        assert kw["run_id"] == run_id
        assert kw["diff"] == fake_diff

    @pytest.mark.asyncio
    async def test_capture_state_diff_repo_failure_does_not_raise(self) -> None:
        tm, repos = _make_tm()
        repos["diff"].create = AsyncMock(side_effect=RuntimeError("DB down"))

        with patch("app.observability.trace_manager.sanitize_state_for_trace", side_effect=lambda s: s):
            with patch("app.observability.trace_manager.build_json_diff", return_value={}):
                await tm.capture_state_diff(
                    trace_id=uuid4(), run_id=uuid4(), before_state={}, after_state={}
                )  # must not raise


# ===========================================================================
# TestCallCapture
# ===========================================================================


class TestCallCapture:
    @pytest.mark.asyncio
    async def test_capture_tool_call_delegates_to_tool_repo(self) -> None:
        tm, repos = _make_tm()
        trace_id = uuid4()
        run_id = uuid4()
        repos["tool"].create = AsyncMock()

        await tm.capture_tool_call(
            trace_id=trace_id,
            run_id=run_id,
            tool_name="lease_lookup_api",
            tool_type="LEASE_LOOKUP",
            request_payload={"lease_code": "LC-001"},
            response_payload={"matches": []},
            status_code=200,
            success=True,
            latency_ms=55,
        )

        repos["tool"].create.assert_awaited_once()
        kw = repos["tool"].create.call_args.kwargs
        assert kw["trace_id"] == trace_id
        assert kw["run_id"] == run_id
        assert kw["tool_name"] == "lease_lookup_api"
        assert kw["tool_type"] == "LEASE_LOOKUP"
        assert kw["success"] is True
        assert kw["latency_ms"] == 55

    @pytest.mark.asyncio
    async def test_capture_tool_call_with_error_message(self) -> None:
        tm, repos = _make_tm()
        repos["tool"].create = AsyncMock()

        await tm.capture_tool_call(
            trace_id=uuid4(),
            run_id=uuid4(),
            tool_name="sr_api",
            tool_type="API",
            success=False,
            error_message="Connection timeout",
        )

        kw = repos["tool"].create.call_args.kwargs
        assert kw["success"] is False
        assert kw["error_message"] == "Connection timeout"

    @pytest.mark.asyncio
    async def test_capture_tool_call_repo_failure_does_not_raise(self) -> None:
        tm, repos = _make_tm()
        repos["tool"].create = AsyncMock(side_effect=RuntimeError("DB down"))

        await tm.capture_tool_call(
            trace_id=uuid4(), run_id=uuid4(), tool_name="t", tool_type="API"
        )  # must not raise

    @pytest.mark.asyncio
    async def test_capture_llm_call_delegates_to_llm_repo(self) -> None:
        tm, repos = _make_tm()
        trace_id = uuid4()
        run_id = uuid4()
        repos["llm"].create = AsyncMock()

        await tm.capture_llm_call(
            trace_id=trace_id,
            run_id=run_id,
            provider="openai",
            model="gpt-4o-mini",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            latency_ms=200,
            parse_success=True,
        )

        repos["llm"].create.assert_awaited_once()
        kw = repos["llm"].create.call_args.kwargs
        assert kw["trace_id"] == trace_id
        assert kw["run_id"] == run_id
        assert kw["provider"] == "openai"
        assert kw["model"] == "gpt-4o-mini"
        assert kw["input_tokens"] == 100
        assert kw["output_tokens"] == 50
        assert kw["total_tokens"] == 150
        assert kw["parse_success"] is True

    @pytest.mark.asyncio
    async def test_capture_llm_call_with_temperature_and_cost(self) -> None:
        tm, repos = _make_tm()
        repos["llm"].create = AsyncMock()

        await tm.capture_llm_call(
            trace_id=uuid4(),
            run_id=uuid4(),
            provider="openai",
            model="gpt-4o-mini",
            temperature=Decimal("0.7"),
            estimated_cost=Decimal("0.0015"),
            structured_output={"intent": "CREATE_HANDOVER_SERVICE_REQUEST"},
        )

        kw = repos["llm"].create.call_args.kwargs
        assert kw["temperature"] == Decimal("0.7")
        assert kw["estimated_cost"] == Decimal("0.0015")

    @pytest.mark.asyncio
    async def test_capture_llm_call_with_parse_error(self) -> None:
        tm, repos = _make_tm()
        repos["llm"].create = AsyncMock()

        await tm.capture_llm_call(
            trace_id=uuid4(),
            run_id=uuid4(),
            parse_success=False,
            parse_error="JSONDecodeError: bad json at position 0",
        )

        kw = repos["llm"].create.call_args.kwargs
        assert kw["parse_success"] is False
        assert "JSONDecodeError" in kw["parse_error"]

    @pytest.mark.asyncio
    async def test_capture_llm_call_repo_failure_does_not_raise(self) -> None:
        tm, repos = _make_tm()
        repos["llm"].create = AsyncMock(side_effect=RuntimeError("DB down"))

        await tm.capture_llm_call(
            trace_id=uuid4(), run_id=uuid4(), provider="openai", model="gpt-4o-mini"
        )  # must not raise


# ===========================================================================
# TestCurrentTraceId
# ===========================================================================


class TestCurrentTraceId:
    def test_returns_none_before_any_trace_started(self) -> None:
        session = AsyncMock(spec=AsyncSession)
        tm = TraceManager(session)
        assert tm.current_trace_id() is None

    @pytest.mark.asyncio
    async def test_returns_last_started_trace_id(self) -> None:
        tm, repos = _make_tm()
        trace_id_1 = uuid4()
        trace_id_2 = uuid4()
        repos["trace"].create = AsyncMock(
            side_effect=[_trace_row(trace_id_1), _trace_row(trace_id_2)]
        )

        await tm.start_trace(session_id=uuid4(), user_id=uuid4(), input_message="first")
        assert tm.current_trace_id() == trace_id_1

        await tm.start_trace(session_id=uuid4(), user_id=uuid4(), input_message="second")
        assert tm.current_trace_id() == trace_id_2

    @pytest.mark.asyncio
    async def test_active_trace_id_unchanged_after_failed_start(self) -> None:
        """A failed start must not overwrite the last valid trace_id."""
        tm, repos = _make_tm()
        trace_id = uuid4()
        repos["trace"].create = AsyncMock(
            side_effect=[_trace_row(trace_id), RuntimeError("DB error")]
        )

        await tm.start_trace(session_id=uuid4(), user_id=uuid4(), input_message="ok")
        assert tm.current_trace_id() == trace_id

        await tm.start_trace(session_id=uuid4(), user_id=uuid4(), input_message="fail")
        # Exception path doesn't update _active_trace_id
        assert tm.current_trace_id() == trace_id
