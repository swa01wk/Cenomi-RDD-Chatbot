"""Integration tests — observability trace lifecycle through the graph.

Each test exercises a real compiled LangGraph with:
  - A real TraceManager whose six repositories are replaced by AsyncMocks.
  - A real ConversationStateService backed by a mocked AsyncSession.
  - All external I/O (LLM, Lease API, SR API) patched at the node level.

The tests verify that the correct observability data is produced as a side-
effect of graph execution — no database connection required.

Test groups
-----------
test_trace_created_for_every_turn    — TraceRepository.create called per turn
test_run_tree_created                — RunRepository.create called per traced node
test_llm_call_logged                 — LLMCallRepository.create called for supervisor
test_tool_call_logged                — ToolCallRepository.create called for lease lookup
test_state_persistence               — save_state_node calls ConversationStateService
test_audit_log_created               — AuditLogRepository.create called by orchestration
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID

import pytest

from app.agents.graph.service_request_graph import build_service_request_graph
from app.agents.schemas.supervisor_schema import SupervisorDecision
from app.agents.services.lease_lookup_service import LeaseRecord, LeaseLookupResult
from app.observability.trace_manager import TraceManager
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Graph singleton
# ---------------------------------------------------------------------------

_GRAPH = build_service_request_graph()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trace_manager_with_mocked_repos() -> tuple[TraceManager, dict[str, AsyncMock]]:
    """Return a TraceManager whose repos are all AsyncMock instances.

    We directly replace the private repo attributes after construction so the
    real session is never needed for the repos themselves.
    """
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

    def _async_repo(spec_class: type) -> AsyncMock:
        m = AsyncMock(spec=spec_class)
        row = MagicMock()
        row.id = uuid4()
        m.create = AsyncMock(return_value=row)
        m.complete = AsyncMock(return_value=row)
        return m

    repos = {
        "trace": _async_repo(TraceRepository),
        "run": _async_repo(RunRepository),
        "snapshot": _async_repo(StateSnapshotRepository),
        "diff": _async_repo(StateDiffRepository),
        "tool": _async_repo(ToolCallRepository),
        "llm": _async_repo(LLMCallRepository),
    }

    tm._trace_repo = repos["trace"]
    tm._run_repo = repos["run"]
    tm._snapshot_repo = repos["snapshot"]
    tm._diff_repo = repos["diff"]
    tm._tool_repo = repos["tool"]
    tm._llm_repo = repos["llm"]

    return tm, repos


def _supervisor_decision_mock() -> AsyncMock:
    decision = SupervisorDecision(
        intent="CREATE_HANDOVER_SERVICE_REQUEST",
        confidence=0.92,
        service_category="FIT_OUT_AND_HANDOVER",
        sub_category="HANDOVER",
        target_agent="handover_service_request_agent",
        reasoning="Integration test",
    )
    return AsyncMock(return_value=(decision, 100, 60, 150))


def _field_extraction_mock(fields: dict | None = None) -> MagicMock:
    result = MagicMock()
    result.to_state_dict.return_value = fields or {}
    result.summary = "test"
    meta = MagicMock()
    meta.parse_success = True
    meta.latency_ms = 80
    meta.retry_count = 0
    meta.input_tokens = 50
    meta.output_tokens = 30
    meta.parse_error = None
    svc = MagicMock()
    svc.extract = AsyncMock(return_value=(result, meta))
    return MagicMock(return_value=svc)


def _lease_service_mock(records: list[LeaseRecord] | None = None) -> MagicMock:
    svc = AsyncMock()
    svc.lookup = AsyncMock(
        return_value=LeaseLookupResult(
            matches=records or [],
            endpoint="mock://lease-api/leases",
            request_payload={},
            response_payload={},
            latency_ms=20,
            status_code=200,
        )
    )
    return MagicMock(return_value=svc)


def _sample_lease() -> LeaseRecord:
    return LeaseRecord(
        lease_code="LC-TRC-001",
        lease_id=5001,
        contract_id=4001,
        brand="Nike",
        brand_id=312,
        mall="Riyadh Park",
        property_id=2018,
        tenant_profile_id=204,
        unit_codes=["RP-101"],
        contracted_area=680.0,
        city="Riyadh",
        lease_brand_mall="LC-TRC-001 - Nike - Riyadh Park",
    )


def _base_state(
    *,
    trace_manager: TraceManager,
    trace_id: UUID | None = None,
    active_agent: str | None = None,
    collected_data: dict | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    return {
        "session_id": str(uuid4()),
        "user_id": str(uuid4()),
        "user_message": "I want to create a handover service request",
        "trace_manager": trace_manager,
        "trace_id": str(trace_id or uuid4()),
        "active_agent": active_agent,
        "collected_data": collected_data or {},
        **overrides,
    }


# ===========================================================================
# Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_trace_created_for_every_turn() -> None:
    """TraceRepository.create must be called exactly once per process_turn call.

    Strategy: invoke ChatOrchestrationService.process_turn with a patched
    TraceRepository class so we can count real create calls, without needing
    an actual DB or LangGraph run.
    """
    from unittest.mock import AsyncMock as AM, MagicMock as MM

    from app.services.chat_orchestration_service import ChatOrchestrationService
    from app.db.models import ChatSession
    from uuid import uuid4 as u4

    # Build a minimal ChatSession stub returned by the session repo
    mock_chat_session = ChatSession(user_id=u4())

    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    result_mock.scalar_one.return_value = 0
    scalars_mock = MagicMock()
    scalars_mock.__iter__ = MagicMock(return_value=iter([]))
    result_mock.scalars.return_value = scalars_mock
    mock_db.execute = AsyncMock(return_value=result_mock)

    # Stub out the compiled graph so we avoid running LangGraph
    stub_result: dict[str, Any] = {
        "response_message": "Please provide a lease code.",
        "status": "WAITING_FOR_USER",
        "active_agent": "handover_service_request_agent",
        "response_ui": {"type": "message"},
        "missing_fields": ["lease_code"],
        "intent": "CREATE_HANDOVER_SERVICE_REQUEST",
        "workflow_stage": "CREATE_SR",
    }

    trace_create_call_count = 0

    async def _mock_trace_repo_create(**kwargs: Any) -> Any:
        nonlocal trace_create_call_count
        trace_create_call_count += 1
        row = MagicMock()
        row.id = u4()
        return row

    with (
        patch(
            "app.observability.repositories.trace_repo.TraceRepository.create",
            new=_mock_trace_repo_create,
        ),
        patch(
            "app.observability.repositories.trace_repo.TraceRepository.complete",
            new=AsyncMock(),
        ),
        patch(
            "app.services.chat_orchestration_service.get_compiled_graph",
            return_value=MagicMock(ainvoke=AsyncMock(return_value=stub_result)),
        ),
        patch(
            "app.db.repositories.chat_session_repo.ChatSessionRepository.create",
            new=AsyncMock(return_value=mock_chat_session),
        ),
        patch(
            "app.db.repositories.chat_session_repo.ChatSessionRepository.get_by_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.db.repositories.chat_message_repo.ChatMessageRepository.create",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "app.db.repositories.audit_log_repo.AuditLogRepository.create",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "app.db.repositories.chat_session_repo.ChatSessionRepository.update",
            new=AsyncMock(return_value=mock_chat_session),
        ),
    ):
        svc = ChatOrchestrationService(mock_db)
        await svc.process_turn(
            session_id=None,
            user_id=u4(),
            message="I want to raise a handover request",
            attachments=[],
        )

    assert trace_create_call_count == 1, (
        f"Expected TraceRepository.create to be called once per turn; "
        f"got {trace_create_call_count}"
    )


@pytest.mark.asyncio
async def test_run_tree_created() -> None:
    """RunRepository.create must be called once per @trace_node-decorated node.

    The supervisor node uses @trace_node("supervisor", "SUPERVISOR"), so at
    minimum one run must be created when the supervisor runs.
    """
    tm, repos = _make_trace_manager_with_mocked_repos()

    with (
        patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            _supervisor_decision_mock(),
        ),
        patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(model="gpt-4o-mini"),
        ),
        patch(
            "app.agents.graph.nodes.field_extraction_node.FieldExtractionService",
            _field_extraction_mock(),
        ),
        patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=MagicMock(model="gpt-4o-mini"),
        ),
    ):
        await _GRAPH.ainvoke(
            _base_state(
                trace_manager=tm,
                user_message="I want to create a handover SR",
            )
        )

    # RunRepository.create is called for each @trace_node decorated node.
    # The graph runs at minimum: supervisor, registry, handover_entry,
    # field_extraction, merge_state, lease_lookup (or some subset).
    run_create_count = repos["run"].create.await_count
    assert run_create_count >= 2, (
        f"Expected at least 2 RunRepository.create calls (one per node), "
        f"got {run_create_count}"
    )


@pytest.mark.asyncio
async def test_llm_call_logged() -> None:
    """LLMCallRepository.create must be called when the supervisor node runs.

    The supervisor node explicitly calls trace_manager.capture_llm_call() after
    the LLM classification, which delegates to LLMCallRepository.create.
    """
    tm, repos = _make_trace_manager_with_mocked_repos()

    decision = SupervisorDecision(
        intent="CREATE_HANDOVER_SERVICE_REQUEST",
        confidence=0.9,
        service_category="FIT_OUT_AND_HANDOVER",
        sub_category="HANDOVER",
        target_agent="handover_service_request_agent",
        reasoning="test",
    )

    with (
        patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            AsyncMock(return_value=(decision, 120, 70, 180)),
        ),
        patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(model="gpt-4o-mini"),
        ),
        patch(
            "app.agents.graph.nodes.field_extraction_node.FieldExtractionService",
            _field_extraction_mock(),
        ),
        patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=MagicMock(model="gpt-4o-mini"),
        ),
    ):
        await _GRAPH.ainvoke(
            _base_state(
                trace_manager=tm,
                user_message="Create a handover SR for Zara",
            )
        )

    llm_create_count = repos["llm"].create.await_count
    assert llm_create_count >= 1, (
        f"Expected at least one LLMCallRepository.create call after supervisor, "
        f"got {llm_create_count}"
    )

    # Verify the LLM call recorded token counts
    call_kwargs = repos["llm"].create.call_args.kwargs
    assert call_kwargs.get("input_tokens") is not None
    assert call_kwargs.get("output_tokens") is not None
    assert call_kwargs.get("prompt_name") == "supervisor_prompt"


@pytest.mark.asyncio
async def test_tool_call_logged() -> None:
    """ToolCallRepository.create must be called after the lease lookup node.

    The lease_lookup_node calls trace_manager.capture_tool_call() for each
    external API call it makes (even when the result is zero matches).
    """
    tm, repos = _make_trace_manager_with_mocked_repos()

    with (
        patch(
            "app.agents.graph.nodes.field_extraction_node.FieldExtractionService",
            _field_extraction_mock(
                {"lease_code": {"value": "LC-TRC-001", "confidence": 0.95}}
            ),
        ),
        patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=MagicMock(model="gpt-4o-mini"),
        ),
        patch(
            "app.agents.graph.nodes.lease_lookup_node.get_lease_lookup_service",
            _lease_service_mock([_sample_lease()]),
        ),
        patch(
            "app.agents.graph.nodes.validation_node._validation_service.validate_draft",
            MagicMock(return_value=[]),
        ),
    ):
        await _GRAPH.ainvoke(
            _base_state(
                trace_manager=tm,
                user_message="Lease code is LC-TRC-001",
                active_agent="handover_service_request_agent",
                collected_data={},
                workflow_stage="CREATE_SR",
            )
        )

    tool_create_count = repos["tool"].create.await_count
    assert tool_create_count >= 1, (
        f"Expected at least one ToolCallRepository.create call for lease lookup, "
        f"got {tool_create_count}"
    )

    call_kwargs = repos["tool"].create.call_args.kwargs
    assert call_kwargs.get("tool_name") is not None
    assert call_kwargs.get("tool_type") is not None


@pytest.mark.asyncio
async def test_state_persistence() -> None:
    """save_state_node must call ConversationStateService.save_checkpoint once.

    The save_state_node reads ``conversation_state_service`` from the graph
    state (injected at turn start).  This test verifies the call happens at
    least once and passes the correct session_id.
    """
    tm, repos = _make_trace_manager_with_mocked_repos()
    session_id = uuid4()

    mock_state_service = AsyncMock()
    mock_state_service.save_checkpoint = AsyncMock()

    with (
        patch(
            "app.agents.graph.nodes.field_extraction_node.FieldExtractionService",
            _field_extraction_mock(),
        ),
        patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=MagicMock(model="gpt-4o-mini"),
        ),
        patch(
            "app.agents.graph.nodes.validation_node._validation_service.validate_draft",
            MagicMock(return_value=[]),
        ),
    ):
        await _GRAPH.ainvoke(
            {
                "session_id": str(session_id),
                "user_id": str(uuid4()),
                "user_message": "what next?",
                "trace_manager": tm,
                "trace_id": str(uuid4()),
                "active_agent": "handover_service_request_agent",
                "collected_data": {
                    "tenant_profile_id": 77,
                    "property_id": 2018,
                    "lease_code": "LC-TRC-001",
                    "lease_id": 5001,
                    "brand_id": 312,
                    "unit_codes": ["RP-101"],
                    "city": "Riyadh",
                    "contracted_area": 680.0,
                    "lease_brand_mall": "LC-TRC-001 - Nike - Riyadh Park",
                    "mall": "Riyadh Park",
                    "brand": "Nike",
                },
                "workflow_stage": "CREATE_SR",
                "conversation_state_service": mock_state_service,
            }
        )

    mock_state_service.save_checkpoint.assert_awaited_once()
    call_args = mock_state_service.save_checkpoint.call_args
    # First arg should be the session UUID
    saved_session_id = call_args.args[0] if call_args.args else call_args.kwargs.get("session_id")
    assert str(saved_session_id) == str(session_id)


@pytest.mark.asyncio
async def test_audit_log_created() -> None:
    """AuditLogRepository.create must be called for turn.started and turn.completed.

    This is validated through ChatOrchestrationService.process_turn, which is
    the component responsible for writing audit log entries around each turn.
    """
    from app.services.chat_orchestration_service import ChatOrchestrationService
    from app.db.models import ChatSession
    from uuid import uuid4 as u4

    mock_chat_session = ChatSession(user_id=u4())

    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    result_mock.scalar_one.return_value = 0
    scalars_mock = MagicMock()
    scalars_mock.__iter__ = MagicMock(return_value=iter([]))
    result_mock.scalars.return_value = scalars_mock
    mock_db.execute = AsyncMock(return_value=result_mock)

    stub_result: dict[str, Any] = {
        "response_message": "How can I help you?",
        "status": "WAITING_FOR_USER",
        "active_agent": None,
        "response_ui": {"type": "message"},
        "missing_fields": [],
        "intent": None,
        "workflow_stage": None,
    }

    audit_log_calls: list[dict] = []

    async def _mock_audit_create(**kwargs: Any) -> Any:
        audit_log_calls.append(kwargs)
        return MagicMock()

    with (
        patch(
            "app.observability.repositories.trace_repo.TraceRepository.create",
            new=AsyncMock(return_value=MagicMock(id=u4())),
        ),
        patch(
            "app.observability.repositories.trace_repo.TraceRepository.complete",
            new=AsyncMock(),
        ),
        patch(
            "app.services.chat_orchestration_service.get_compiled_graph",
            return_value=MagicMock(ainvoke=AsyncMock(return_value=stub_result)),
        ),
        patch(
            "app.db.repositories.chat_session_repo.ChatSessionRepository.create",
            new=AsyncMock(return_value=mock_chat_session),
        ),
        patch(
            "app.db.repositories.chat_session_repo.ChatSessionRepository.get_by_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.db.repositories.chat_message_repo.ChatMessageRepository.create",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "app.db.repositories.audit_log_repo.AuditLogRepository.create",
            new=_mock_audit_create,
        ),
        patch(
            "app.db.repositories.chat_session_repo.ChatSessionRepository.update",
            new=AsyncMock(return_value=mock_chat_session),
        ),
    ):
        svc = ChatOrchestrationService(mock_db)
        await svc.process_turn(
            session_id=None,
            user_id=u4(),
            message="Hello, I need help",
            attachments=[],
        )

    actions = [c.get("action") for c in audit_log_calls]
    assert "turn.started" in actions, (
        f"Expected 'turn.started' audit action; found: {actions}"
    )
    assert "turn.completed" in actions, (
        f"Expected 'turn.completed' audit action; found: {actions}"
    )
