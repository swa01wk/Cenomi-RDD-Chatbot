# Testing Strategy

## Overview

Tests live under `backend/tests/` and are split into three layers:

```
backend/tests/
├── unit/          # Pure function and service tests (25+ files)
├── integration/   # Compiled graph with mocked LLM/API/DB
└── e2e/           # Full HTTP stack via ASGI transport
```

Run all tests:
```bash
cd backend
pytest
```

Run a single layer:
```bash
pytest tests/unit/
pytest tests/integration/
pytest tests/e2e/
```

---

## Unit Tests

**Location:** `backend/tests/unit/`  
**Purpose:** Test individual nodes, services, schemas, and utilities in isolation. No database, no LLM, no HTTP.

### What is unit-tested

| File | What it tests |
|------|--------------|
| `test_security_guardrails.py` | Injection detection, confirmation bypass prevention, validation blocking submission, backend field protection |
| `test_handover_schema.py` | `CREATE_SR_STAGE` required fields, `HandoverExtractedFields` validator stripping backend-only keys, `EXTRACTABLE_FIELDS` membership |
| `test_service_request_graph.py` | Routing functions (`_route_after_*`) with various state combinations |
| `test_supervisor_node.py` | Intent classification, confidence thresholding, `SupervisorDecision` parsing |
| `test_field_extraction_node.py` | LLM extraction, confidence filtering, field merge |
| `test_merge_state_node.py` | Backend field protection, confidence threshold (0.6), `collected_data` update |
| `test_validation_node.py` | Date format, date order, required field presence, blocking vs non-blocking errors |
| `test_confirmation_node.py` | `confirmation_card` UI structure, `_CONFIRMATION_DISPLAY_FIELDS` subset |
| `test_payload_builder_service.py` | `build_create_handover_payload` — required key validation, output shape |
| `test_injection_guard.py` | Pattern catalog, score thresholds, `HIGH_RISK_THRESHOLD` |
| `test_trace_manager.py` | `start_trace`, `finish_trace`, `fail_trace`, `capture_*` methods |
| `test_conversation_state_service.py` | `load` merging draft into state, `save_checkpoint` upsert logic |
| `test_observability_*.py` | Repository methods, state diff, sanitization |

### DB mocking pattern

Unit tests mock the `AsyncSession` directly:

```python
# tests/unit/conftest.py
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.fixture
def mock_session():
    session = AsyncMock(spec=AsyncSession)
    return session

def make_execute_result(rows):
    """Factory for sqlalchemy execute() return values."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    return result
```

Usage in a test:

```python
async def test_creates_draft(mock_session):
    mock_session.execute.return_value = make_execute_result([])
    service = ConversationStateService(mock_session)
    await service.save_checkpoint(session_id="uuid", state={...})
    mock_session.add.assert_called_once()
    mock_session.commit.assert_awaited_once()
```

---

## Integration Tests

**Location:** `backend/tests/integration/`  
**Purpose:** Test the full compiled LangGraph graph end-to-end with mocked external dependencies (LLM, Lease API, SR API, database).

### Key fixture: `compiled_graph`

```python
# tests/integration/conftest.py
@pytest.fixture
def mock_llm_gateway():
    gateway = AsyncMock()
    # complete_json returns (parsed_model, raw_dict) tuple
    gateway.complete_json.return_value = (
        SupervisorDecision(
            intent="CREATE_HANDOVER_SERVICE_REQUEST",
            service_category="FIT_OUT_AND_HANDOVER",
            sub_category="HANDOVER",
            confidence=0.95,
            reasoning="User wants handover SR",
        ),
        {"intent": "CREATE_HANDOVER_SERVICE_REQUEST", ...}
    )
    return gateway

@pytest.fixture
def mock_db():
    return AsyncMock(spec=AsyncSession)

@pytest.fixture
def mock_lease_api():
    api = AsyncMock()
    api.get_leases.return_value = [SAMPLE_LEASE]
    return api

@pytest.fixture
def mock_sr_api():
    api = AsyncMock()
    api.create_service_request.return_value = {"sr_id": "SR-001", "status": "CREATED"}
    return api
```

### What integration tests verify

- Complete happy-path graph execution (CREATE_SR from first message to submission).
- Confirmation bypass prevention — graph does not reach `api_submission_node` without `confirmation_status == "CONFIRMED"`.
- Validation blocking — graph loops through `missing_field_node` when required fields are absent.
- Lease disambiguation — multiple leases route to `WAITING_FOR_USER`.
- Observability data — `TraceManager` called with correct arguments at each node.
- Chat HTTP endpoint (`POST /api/chat/service-request`) response shape.

---

## E2E Tests

**Location:** `backend/tests/e2e/`  
**Purpose:** Test the full HTTP stack via `httpx.AsyncClient` with `ASGITransport`. The actual FastAPI app is loaded. Database is overridden with `AsyncMock`; LLM gateway and external APIs are patched at the module level.

**What is NOT mocked in E2E:**

- `ChatOrchestrationService` — runs for real.
- LangGraph graph (`get_compiled_graph()`) — runs for real.
- Routing, validation, payload building — run for real.

**What IS mocked in E2E:**

- Database session (`AsyncSession`) — `AsyncMock`.
- `LLMGateway.complete_json` — returns controlled supervisor/extraction outputs.
- `LeaseTenantAPIClient` — returns controlled lease data.
- `ServiceRequestAPIClient.create_service_request` — returns controlled `sr_id`.

### App client fixture

```python
# tests/e2e/conftest.py
@pytest.fixture(scope="function")
async def app_client(mock_db_session, mock_llm, mock_lease_api, mock_sr_api):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        yield client
```

### E2E test endpoint

All E2E tests use `POST /api/chat/service-request` (not `/api/v1/chat/service-request`).

### Helper utilities

**`tests/e2e/helpers.py`:**

```python
def make_supervisor_mock(intent, service_category, sub_category, confidence=0.95):
    """Returns (SupervisorDecision, dict) tuple for LLM mock."""

def all_collected_data():
    """Returns a complete collected_data dict with all CREATE_SR required fields."""

def make_extracted_fields(subset: dict):
    """Returns (HandoverExtractedFields, dict) tuple for field extraction mock."""
```

### Representative E2E test: `test_handover_sr_e2e.py`

```python
async def test_full_create_sr_happy_path(app_client, mock_llm, mock_lease_api, mock_sr_api):
    # Turn 1: classify intent
    resp = await app_client.post("/api/chat/service-request", json={
        "user_id": "user-1",
        "message": "I want to submit a handover request"
    })
    data = resp.json()
    session_id = data["session_id"]
    assert data["active_agent"] == "handover_service_request_agent"

    # Turn 2: select lease
    resp = await app_client.post("/api/chat/service-request", json={
        "session_id": session_id,
        "user_id": "user-1",
        "message": "",
        "attachments": [{"lease_id": "uuid-lease-1"}]
    })
    # ... and so on through field collection, confirmation, submission
```

---

## Mocking Strategy

### LLM mocking

LLM calls are the most important mock because they introduce non-determinism. The `LLMGateway.complete_json` method is patched to return pre-defined Pydantic model instances:

```python
mock_llm.complete_json.side_effect = [
    # First call: supervisor
    (SupervisorDecision(intent="CREATE_HANDOVER_SERVICE_REQUEST", ...), {...}),
    # Second call: field extraction
    (HandoverExtractedFields(title="My request", ...), {...}),
]
```

Using `side_effect` as a list allows different LLM responses for different turns in a multi-turn test.

### Database mocking

For unit and E2E tests, `AsyncSession` is mocked with `AsyncMock(spec=AsyncSession)`. Key method behaviours set:

- `execute()` → returns `make_execute_result([...])` for SELECT queries.
- `add()`, `commit()`, `refresh()` → `AsyncMock()` (no-ops).
- `get()` → returns specific model instance for PK lookups.

For integration tests, repositories are instantiated with the mocked session:

```python
repo = ChatSessionRepository(mock_db)
mock_db.execute.return_value = make_execute_result([existing_session])
```

### External API mocking

```python
# Lease API
@pytest.fixture
def mock_lease_api(monkeypatch):
    mock = AsyncMock()
    mock.get_leases_for_user.return_value = [SAMPLE_LEASE_DICT]
    monkeypatch.setattr("app.services.lease_lookup_service.lease_api_client", mock)
    return mock

# SR API
@pytest.fixture
def mock_sr_api(monkeypatch):
    mock = AsyncMock()
    mock.create_service_request.return_value = {"sr_id": "SR-TEST-001"}
    monkeypatch.setattr("app.services.service_request_api_service.sr_api_client", mock)
    return mock
```

---

## Test Fixtures

### Shared data fixtures

**`SAMPLE_LEASE_DICT`** — used across unit, integration, and E2E tests:

```python
SAMPLE_LEASE_DICT = {
    "lease_id": "uuid-lease-test-1",
    "lease_code": "LC-TEST-001",
    "tenant_profile_id": "uuid-tenant-1",
    "property_id": "uuid-property-1",
    "brand_id": "uuid-brand-1",
    "mall": "Test Mall",
    "brand": "Test Brand",
    "unit_codes": ["T-101"],
    "city": "Riyadh",
    "contracted_area": 200.0,
}
```

**`ALL_COLLECTED_DATA`** — complete `collected_data` dict with all `CREATE_SR_STAGE.required_fields` populated. Used to bypass field collection in tests focused on confirmation or submission.

**`MINIMAL_SESSION`** — a `ChatSession` model instance in `active_agent=None` state for testing supervisor routing.

**`ACTIVE_SESSION`** — a `ChatSession` model instance with `active_agent="handover_service_request_agent"` for testing handover-entry routing.

### pytest markers

```ini
# pyproject.toml
[tool.pytest.ini_options]
markers = [
    "unit: Pure unit tests",
    "integration: Integration tests with mocked I/O",
    "e2e: End-to-end HTTP tests",
    "slow: Tests that take > 2s",
]
```
