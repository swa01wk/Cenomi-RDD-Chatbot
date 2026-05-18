"""Unit tests for AuditLogRepository."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4


from app.db.models import ServiceRequestChatAuditLog
from app.db.repositories.audit_log_repo import AuditLogRepository


# ── helpers ────────────────────────────────────────────────────────────────


def _make_log(**kwargs: object) -> ServiceRequestChatAuditLog:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "session_id": uuid4(),
        "action": "draft.updated",
        "actor_user_id": None,
        "before_state": None,
        "after_state": None,
        "metadata_": {},
    }
    defaults.update(kwargs)
    return ServiceRequestChatAuditLog(**defaults)  # type: ignore[arg-type]


# ── create ─────────────────────────────────────────────────────────────────


async def test_create_returns_audit_log(mock_session: AsyncMock) -> None:
    session_id = uuid4()
    repo = AuditLogRepository(mock_session)

    result = await repo.create(session_id=session_id, action="draft.created")

    assert isinstance(result, ServiceRequestChatAuditLog)
    assert result.session_id == session_id
    assert result.action == "draft.created"
    assert result.actor_user_id is None
    assert result.before_state is None
    assert result.after_state is None
    assert result.metadata_ == {}
    mock_session.add.assert_called_once_with(result)
    mock_session.flush.assert_awaited_once()


async def test_create_with_actor_and_states(mock_session: AsyncMock) -> None:
    actor_id = uuid4()
    before = {"status": "IN_PROGRESS"}
    after = {"status": "COMPLETED"}
    repo = AuditLogRepository(mock_session)

    result = await repo.create(
        session_id=uuid4(),
        action="session.completed",
        actor_user_id=actor_id,
        before_state=before,
        after_state=after,
        metadata={"source": "api"},
    )

    assert result.actor_user_id == actor_id
    assert result.before_state == before
    assert result.after_state == after
    assert result.metadata_ == {"source": "api"}


async def test_create_none_metadata_defaults_to_empty_dict(mock_session: AsyncMock) -> None:
    repo = AuditLogRepository(mock_session)
    result = await repo.create(
        session_id=uuid4(),
        action="x",
        metadata=None,
    )
    assert result.metadata_ == {}


async def test_create_with_only_after_state(mock_session: AsyncMock) -> None:
    repo = AuditLogRepository(mock_session)
    result = await repo.create(
        session_id=uuid4(),
        action="draft.created",
        after_state={"service_category": "maintenance"},
    )
    assert result.before_state is None
    assert result.after_state == {"service_category": "maintenance"}


# ── get_by_id ──────────────────────────────────────────────────────────────


async def test_get_by_id_returns_log(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    log = _make_log()
    mock_session.execute.return_value = make_execute_result(scalar=log)  # type: ignore[operator]
    repo = AuditLogRepository(mock_session)

    result = await repo.get_by_id(log.id)  # type: ignore[arg-type]

    assert result is log


async def test_get_by_id_returns_none_when_missing(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = AuditLogRepository(mock_session)

    assert await repo.get_by_id(uuid4()) is None


# ── list_by_session ────────────────────────────────────────────────────────


async def test_list_by_session_returns_all_logs(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    session_id = uuid4()
    logs = [_make_log(session_id=session_id, action=f"action.{i}") for i in range(3)]
    mock_session.execute.return_value = make_execute_result(scalars=logs)  # type: ignore[operator]
    repo = AuditLogRepository(mock_session)

    result = await repo.list_by_session(session_id)

    assert result == logs
    mock_session.execute.assert_awaited_once()


async def test_list_by_session_returns_empty_when_none(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalars=[])  # type: ignore[operator]
    repo = AuditLogRepository(mock_session)

    assert await repo.list_by_session(uuid4()) == []


async def test_list_by_session_respects_limit(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    session_id = uuid4()
    logs = [_make_log(session_id=session_id) for _ in range(2)]
    mock_session.execute.return_value = make_execute_result(scalars=logs)  # type: ignore[operator]
    repo = AuditLogRepository(mock_session)

    result = await repo.list_by_session(session_id, limit=2)

    assert len(result) == 2
    mock_session.execute.assert_awaited_once()


async def test_list_by_session_no_limit_returns_all(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    session_id = uuid4()
    logs = [_make_log(session_id=session_id) for _ in range(10)]
    mock_session.execute.return_value = make_execute_result(scalars=logs)  # type: ignore[operator]
    repo = AuditLogRepository(mock_session)

    result = await repo.list_by_session(session_id)

    assert len(result) == 10


# ── audit log is append-only (no update method) ───────────────────────────


def test_audit_log_repo_has_no_update_method() -> None:
    """Audit logs must be immutable — no update method should exist."""
    assert not hasattr(AuditLogRepository, "update")
