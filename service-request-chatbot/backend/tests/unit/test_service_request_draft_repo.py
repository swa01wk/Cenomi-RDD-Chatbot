"""Unit tests for ServiceRequestDraftRepository."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.db.exceptions import InvalidUpdateFieldError, RecordNotFoundError
from app.db.models import ServiceRequestDraft
from app.db.repositories.service_request_draft_repo import ServiceRequestDraftRepository


# ── helpers ────────────────────────────────────────────────────────────────


def _make_draft(**kwargs: object) -> ServiceRequestDraft:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "session_id": uuid4(),
        "service_category": "maintenance",
        "sub_category": "plumbing",
        "workflow_stage": "collect_fields",
        "collected_data": {},
        "missing_fields": [],
        "documents": [],
        "sr_id": None,
        "service_request_status": None,
        "ready_to_submit": False,
    }
    defaults.update(kwargs)
    return ServiceRequestDraft(**defaults)  # type: ignore[arg-type]


# ── create ─────────────────────────────────────────────────────────────────


async def test_create_returns_draft(mock_session: AsyncMock) -> None:
    session_id = uuid4()
    repo = ServiceRequestDraftRepository(mock_session)

    result = await repo.create(
        session_id=session_id,
        service_category="cleaning",
        sub_category="deep_clean",
        workflow_stage="collect_fields",
    )

    assert isinstance(result, ServiceRequestDraft)
    assert result.session_id == session_id
    assert result.service_category == "cleaning"
    assert result.sub_category == "deep_clean"
    assert result.workflow_stage == "collect_fields"
    assert result.collected_data == {}
    assert result.missing_fields == []
    assert result.documents == []
    assert result.ready_to_submit is False
    mock_session.add.assert_called_once_with(result)
    mock_session.flush.assert_awaited_once()


async def test_create_with_all_optional_fields(mock_session: AsyncMock) -> None:
    repo = ServiceRequestDraftRepository(mock_session)

    result = await repo.create(
        session_id=uuid4(),
        service_category="maintenance",
        sub_category="electrical",
        workflow_stage="validate",
        collected_data={"unit": "101"},
        missing_fields=["description"],
        documents=[{"name": "photo.jpg", "url": "https://..."}],
        sr_id="SR-001",
        service_request_status="pending",
        ready_to_submit=True,
    )

    assert result.collected_data == {"unit": "101"}
    assert result.missing_fields == ["description"]
    assert result.documents == [{"name": "photo.jpg", "url": "https://..."}]
    assert result.sr_id == "SR-001"
    assert result.service_request_status == "pending"
    assert result.ready_to_submit is True


async def test_create_none_collected_data_defaults_to_empty(mock_session: AsyncMock) -> None:
    repo = ServiceRequestDraftRepository(mock_session)
    result = await repo.create(
        session_id=uuid4(),
        service_category="x",
        sub_category="y",
        workflow_stage="z",
        collected_data=None,
        missing_fields=None,
        documents=None,
    )
    assert result.collected_data == {}
    assert result.missing_fields == []
    assert result.documents == []


# ── get_by_id ──────────────────────────────────────────────────────────────


async def test_get_by_id_returns_draft(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    draft = _make_draft()
    mock_session.execute.return_value = make_execute_result(scalar=draft)  # type: ignore[operator]
    repo = ServiceRequestDraftRepository(mock_session)

    result = await repo.get_by_id(draft.id)  # type: ignore[arg-type]

    assert result is draft


async def test_get_by_id_returns_none_when_missing(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = ServiceRequestDraftRepository(mock_session)

    assert await repo.get_by_id(uuid4()) is None


# ── get_by_session ─────────────────────────────────────────────────────────


async def test_get_by_session_returns_most_recent(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    draft = _make_draft()
    mock_session.execute.return_value = make_execute_result(scalar=draft)  # type: ignore[operator]
    repo = ServiceRequestDraftRepository(mock_session)

    result = await repo.get_by_session(draft.session_id)  # type: ignore[arg-type]

    assert result is draft


async def test_get_by_session_returns_none_when_no_drafts(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = ServiceRequestDraftRepository(mock_session)

    assert await repo.get_by_session(uuid4()) is None


# ── update ─────────────────────────────────────────────────────────────────


async def test_update_applies_changes(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    draft = _make_draft()
    mock_session.execute.return_value = make_execute_result(scalar=draft)  # type: ignore[operator]
    repo = ServiceRequestDraftRepository(mock_session)

    updated = await repo.update(
        draft.id,  # type: ignore[arg-type]
        {"workflow_stage": "validate", "ready_to_submit": True},
    )

    assert updated.workflow_stage == "validate"
    assert updated.ready_to_submit is True
    mock_session.flush.assert_awaited_once()


async def test_update_collected_data(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    draft = _make_draft(collected_data={})
    mock_session.execute.return_value = make_execute_result(scalar=draft)  # type: ignore[operator]
    repo = ServiceRequestDraftRepository(mock_session)

    data = {"unit_number": "5B", "description": "Leaking pipe"}
    updated = await repo.update(draft.id, {"collected_data": data})  # type: ignore[arg-type]

    assert updated.collected_data == data


async def test_update_raises_not_found(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = ServiceRequestDraftRepository(mock_session)

    with pytest.raises(RecordNotFoundError) as exc_info:
        await repo.update(uuid4(), {"workflow_stage": "done"})

    assert "ServiceRequestDraft" in str(exc_info.value)


async def test_update_raises_for_non_updatable_field(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    draft = _make_draft()
    mock_session.execute.return_value = make_execute_result(scalar=draft)  # type: ignore[operator]
    repo = ServiceRequestDraftRepository(mock_session)

    with pytest.raises(InvalidUpdateFieldError) as exc_info:
        await repo.update(draft.id, {"session_id": uuid4()})  # type: ignore[arg-type]

    assert "session_id" in str(exc_info.value)


async def test_update_does_not_flush_on_not_found(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalar=None)  # type: ignore[operator]
    repo = ServiceRequestDraftRepository(mock_session)

    with pytest.raises(RecordNotFoundError):
        await repo.update(uuid4(), {"workflow_stage": "done"})

    mock_session.flush.assert_not_awaited()


# ── list_by_session ────────────────────────────────────────────────────────


async def test_list_by_session_returns_all_drafts(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    session_id = uuid4()
    drafts = [_make_draft(session_id=session_id) for _ in range(2)]
    mock_session.execute.return_value = make_execute_result(scalars=drafts)  # type: ignore[operator]
    repo = ServiceRequestDraftRepository(mock_session)

    result = await repo.list_by_session(session_id)

    assert result == drafts


async def test_list_by_session_returns_empty_list(
    mock_session: AsyncMock,
    make_execute_result: object,
) -> None:
    mock_session.execute.return_value = make_execute_result(scalars=[])  # type: ignore[operator]
    repo = ServiceRequestDraftRepository(mock_session)

    assert await repo.list_by_session(uuid4()) == []
