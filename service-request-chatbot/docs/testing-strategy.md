# Testing Strategy

## Overview

Tests live under `backend/tests/` and are split into three layers:

```
backend/tests/
├── unit/          # Pure function and service tests (30+ files)
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

**Prerequisite:** The `users` table must exist for tests that exercise auth. Run `alembic upgrade head` once before tests, or ensure tests that test auth mock the `UserRepository`.

**Node import paths changed:** Nodes are now grouped into subdirectories. Update imports in any new tests:

| Old path | New path |
|---|---|
| `app.agents.graph.nodes.supervisor_node` | `app.agents.graph.nodes.shared.supervisor_node` |
| `app.agents.graph.nodes.registry_node` | `app.agents.graph.nodes.shared.registry_node` |
| `app.agents.graph.nodes.load_session_node` | `app.agents.graph.nodes.shared.load_session_node` |
| `app.agents.graph.nodes.faq_node` | `app.agents.graph.nodes.faq.faq_node` |
| `app.agents.graph.nodes.handover_entry_node` | `app.agents.graph.nodes.handover.handover_entry_node` |
| `app.agents.graph.nodes.validation_node` | `app.agents.graph.nodes.handover.validation_node` |
| `app.agents.registries.service_request_registry` | `app.agents.registry` |

Backward-compat re-export stubs exist at all old paths — existing tests continue to work unchanged.

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
| `test_supervisor_node.py` | Intent classification including `ASK_HELP`, confidence thresholding, `SupervisorDecision` parsing |
| `test_field_extraction_node.py` | LLM extraction, confidence filtering, field merge |
| `test_merge_state_node.py` | Backend field protection, confidence threshold (0.6), `collected_data` update |
| `test_validation_node.py` | Date format, date order, required field presence, blocking vs non-blocking errors |
| `test_confirmation_node.py` | `confirmation_card` UI structure, `_CONFIRMATION_DISPLAY_FIELDS` subset |
| `test_payload_builder_service.py` | `build_create_handover_payload` — required key validation, output shape |
| `test_injection_guard.py` | Pattern catalog, score thresholds, `HIGH_RISK_THRESHOLD` |
| `test_trace_manager.py` | `start_trace`, `finish_trace`, `fail_trace`, `capture_*` methods |
| `test_conversation_state_service.py` | `load` merging draft into state, `save_checkpoint` upsert logic |
| `test_observability_*.py` | Repository methods, state diff, sanitization |

### New unit tests to add for Helper Agent additions

| File to create | What to test |
|---|---|
| `test_auth.py` | `hash_password`, `verify_password`, `create_access_token`, `decode_access_token` — happy path + expired token |
| `test_user_repo.py` | `get_by_username` — found, not found, inactive user |
| `test_helper_schema.py` | `intents_for_roles`, `HelperIntent` as `str`, `ALL_INTENTS` derived from registry |
| `test_faq_node.py` | LLM call dispatched, FAQ answer returned, fallback on JSON parse error |
| `test_helper_agent_graph.py` | `_route_after_sync` data-driven, `_route_after_validation` data-driven, `_route_after_supervisor` RBAC + fallbacks, `_SR_ACTION_INTENTS` derived |
| `test_workflow_config.py` | `WorkflowConfig` registry shape, `get_workflow_config()`, `register_workflow()`, second workflow independent |
| `test_security_guardrails.py` (extend) | RBAC mismatch returns role-appropriate message, `auth_context` injected correctly |

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

The integration tests now use `get_compiled_helper_graph()` (the Helper Agent graph) rather than the old `get_compiled_graph()`. The helper graph includes the `faq_node` path and role-aware routing.

```python
# tests/integration/conftest.py
@pytest.fixture
def mock_llm_gateway():
    gateway = AsyncMock()
    # complete_json returns (parsed_model, raw_dict) tuple
    # For supervisor: use ASK_HELP for FAQ tests, CREATE_HANDOVER_SR for SR tests
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
def mock_auth_context_mall_manager():
    """AuthContext for a MALL_MANAGER with mall 7 access."""
    from app.types.chat import AuthContext
    return AuthContext(
        subject_id="aisha-uuid",
        roles=frozenset({"MALL_MANAGER"}),
        unique_property_ids=(7,),
        mall_names=("Jawharat Jeddah",),
        is_global_admin=False,
    )

@pytest.fixture
def mock_auth_context_fm_manager():
    from app.types.chat import AuthContext
    return AuthContext(
        subject_id="khalid-uuid",
        roles=frozenset({"FM_MANAGER"}),
        unique_property_ids=(7,),
        mall_names=("Jawharat Jeddah",),
        is_global_admin=False,
    )

@pytest.fixture
def mock_auth_context_dd_engineer():
    from app.types.chat import AuthContext
    return AuthContext(
        subject_id="sara-uuid",
        roles=frozenset({"DD_ENGINEER"}),
        unique_property_ids=(),
        mall_names=(),
        is_global_admin=False,
    )
```

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
- **FAQ path** — `ASK_HELP` intent routes to `faq_node`, no SR workflow activated, no session draft created.
- **RBAC routing** — FM Manager intent `CREATE_SR` routes to `response_generation` with denial, not to `registry`.
- Confirmation bypass prevention — graph does not reach `api_submission_node` without `confirmation_status == "CONFIRMED"`.
- Validation blocking — graph loops through `missing_field_node` when required fields are absent.
- Lease disambiguation — multiple leases route to `WAITING_FOR_USER`.
- **FM Review flow** — `sr_status_sync` detecting `FM_REVIEW` routes to `fm_review_entry`.
- **RDD Review flow** — `sr_status_sync` detecting `RDD_REVIEW` routes to `rdd_review_entry`.
- Observability data — `TraceManager` called with correct arguments at each node.
- Chat HTTP endpoint (`POST /api/chat/service-request`) response shape including new `sr_id` field.
- Login endpoint (`POST /api/auth/login`) — returns JWT with correct claims for each role.

### New integration test files to add

| File | What it covers |
|---|---|
| `test_auth_endpoint.py` | `POST /api/auth/login` — success, wrong password, inactive user, `GET /api/auth/me` |
| `test_faq_path.py` | `ASK_HELP` intent: `faq_node` called, `active_agent = null` in response, no draft created |
| `test_rbac_routing.py` | FM Manager / DD Engineer blocked from SR creation; all roles can ask FAQ questions |
| `test_sr_status_sync.py` | `sr_id` in request → `sr_status_sync` → correct stage entry node |

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

E2E tests that exercise auth-gated paths must include an `Authorization` header. The `app_client` fixture should be extended with an auth helper:

```python
# tests/e2e/helpers.py addition
async def get_test_token(client, username="aisha@cenomi.com", password="test1234"):
    """Get a JWT for a seeded test user. Requires users table to be seeded."""
    resp = await client.post("/api/auth/login", json={"username": username, "password": password})
    return resp.json()["access_token"]
```

In shadow mode (`RBAC_ENFORCE=false`, the default), requests without a token still work — `AuthContext` defaults to anonymous with empty roles. This means the existing E2E test suite continues to pass without changes. Enable `RBAC_ENFORCE=true` in tests that specifically verify auth enforcement.

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
    "auth: Tests that exercise login and JWT validation",
    "rbac: Tests that exercise role-based access control",
]
```

---

## Test Coverage Map — New Features

| Feature | Unit | Integration | E2E |
|---|---|---|---|
| Login (`POST /api/auth/login`) | `test_auth.py` | `test_auth_endpoint.py` | `test_handover_sr_e2e.py` (login step) |
| JWT validation + AuthContext | `test_auth.py` | — | — |
| UserRepository | `test_user_repo.py` | — | — |
| Helper schema / RBAC intents | `test_helper_schema.py` | `test_rbac_routing.py` | — |
| FAQ node | `test_faq_node.py` | `test_faq_path.py` | — |
| Helper agent graph routing | `test_helper_agent_graph.py` | `test_faq_path.py`, `test_rbac_routing.py` | — |
| FM Review flow | `test_fm_nodes.py` (existing) | `test_fm_review_e2e.py` (existing) | `test_handover_sr_e2e.py` |
| RDD Review flow | `test_rdd_nodes.py` (existing) | `test_rdd_review_e2e.py` (existing) | `test_handover_sr_e2e.py` |
| `sr_id` in request → `sr_status_sync` | — | `test_sr_status_sync.py` | — |
| Node reorganisation (backward compat) | All existing unit tests (stubs in place) | — | — |
| **WorkflowConfig registry** | `test_workflow_config.py` | — | — |
| **Multi-workflow routing** (`_route_after_sync`, `_route_after_validation`) | `test_helper_agent_graph.py` | — | — |
| **Per-workflow extraction prompt** | `test_field_extraction.py::TestFieldExtractionWorkflowConfig` | — | — |
| **Per-workflow field questions** | `test_missing_field_node.py::TestMissingFieldNodeWorkflowConfig` | — | — |
| **`HelperIntent` as `str`** | `test_helper_schema.py` | — | — |
