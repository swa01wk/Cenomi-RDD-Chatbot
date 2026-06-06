# Cenomi RDD Chatbot — Developer Handover Document

> **Prepared:** June 2026  
> **Audience:** Incoming developer(s) taking over this repository  
> **Purpose:** Full current-state walkthrough and tenant platform integration guide

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Repository Structure](#2-repository-structure)
3. [Technology Stack](#3-technology-stack)
4. [Local Development Setup](#4-local-development-setup)
5. [Architecture Overview](#5-architecture-overview)
6. [Backend — Detailed Walkthrough](#6-backend--detailed-walkthrough)
7. [Frontend — Detailed Walkthrough](#7-frontend--detailed-walkthrough)
8. [Database & State Management](#8-database--state-management)
9. [Observability System](#9-observability-system)
10. [Security Guardrails](#10-security-guardrails)
11. [Testing Strategy](#11-testing-strategy)
12. [Current Implementation State](#12-current-implementation-state)
13. [Known Gaps & Issues](#13-known-gaps--issues)
14. [Tenant Platform Integration Guide](#14-tenant-platform-integration-guide)
15. [Recommended Implementation Order](#15-recommended-implementation-order)
16. [Environment Variables Reference](#16-environment-variables-reference)
17. [Key Design Principles](#17-key-design-principles)

---

## 1. Project Overview

This is a conversational AI chatbot for creating and managing **Handover Service Requests** on the Cenomi platform. It replaces the manual form-filling process with a natural-language chat interface.

### What it does today

- Tenant (Mall Manager) opens a chat and says something like *"I want to raise a handover request for Under Armour in Jawharat Jeddah"*
- The bot asks for required fields (start/end dates, inspection responsible, description)
- The bot resolves backend-derived fields (property ID, brand ID, lease IDs) via platform lookup APIs
- The bot shows a confirmation summary before any platform action
- The bot calls the Cenomi platform API to create the Service Request and returns the SR ID

### What it needs to do next (the gap)

The full lifecycle after SR creation is designed but not yet fully wired end-to-end:

```
CREATE_SR  →  FM_REVIEW  →  RDD_REVIEW  →  COMPLETED
```

Full details on the gap are in Section 13 and Section 14.

---

## 2. Repository Structure

```
Cenomi-RDD-Chatbot/
├── service-request-chatbot/        # Main application
│   ├── backend/                    # FastAPI + LangGraph Python app
│   │   ├── app/                    # Application source
│   │   │   ├── agents/             # LangGraph graph, nodes, prompts, schemas, services
│   │   │   ├── api/routes/         # HTTP route handlers
│   │   │   ├── core/               # Config, logging, security, Redis, injection guard
│   │   │   ├── db/                 # ORM models, async session, repositories
│   │   │   ├── observability/      # Trace manager, decorators, redaction, API routes
│   │   │   ├── services/           # Chat orchestration service
│   │   │   ├── types/              # Shared Pydantic types
│   │   │   └── main.py             # FastAPI app factory
│   │   ├── alembic/                # Database migrations
│   │   ├── tests/                  # Unit, integration, e2e, eval
│   │   ├── pyproject.toml          # Python dependencies
│   │   └── .env.example            # Environment variable template
│   ├── frontend/                   # Next.js 15 app
│   │   ├── app/                    # App Router pages
│   │   ├── components/             # React components
│   │   ├── lib/                    # API clients and types
│   │   └── package.json
│   ├── docs/                       # 14 documentation files
│   ├── results/                    # Test result reports
│   ├── docker-compose.yml          # Postgres + Redis
│   └── README.md
└── gaps_and_pc/                    # Postman collection + gap analysis docs
    ├── Handover SR — FIT_OUT_AND_HANDOVER - HANDOVER.postman_collection.json
    ├── chatbot_postman_gap_implementation_plan.md
    └── handover_chatbot_gap_closure_implementation.md
```

### Key documentation files (read these first)

| File | What it covers |
|------|---------------|
| `docs/architecture.md` | Full-stack design, LangGraph flow, DB schema, integration diagram |
| `docs/agent-design.md` | Supervisor, registry, node responsibilities, routing rules, LLM boundary |
| `docs/handover-workflow.md` | CREATE_SR / FM_REVIEW / RDD_REVIEW stages, field list, validation, payload shapes |
| `docs/security-guardrails.md` | Injection guard, confirmation gates, backend field protection, permissions |
| `docs/local-development.md` | Step-by-step setup, env vars, Alembic migrations |
| `docs/api-reference.md` | Complete REST API contract |
| `docs/observability.md` | Trace hierarchy, admin UI, redaction |
| `docs/extensibility-guide.md` | How to add new service request types / agents |
| `docs/debugging-guide.md` | SQL queries, trace inspection, common debugging patterns |
| `gaps_and_pc/chatbot_postman_gap_implementation_plan.md` | **Primary gap document** — gaps and acceptance criteria |
| `gaps_and_pc/handover_chatbot_gap_closure_implementation.md` | Detailed implementation instructions per gap |

---

## 3. Technology Stack

### Backend

| Component | Technology |
|-----------|-----------|
| Web framework | **FastAPI** (Python 3.11+) |
| Agent orchestration | **LangGraph** |
| LLM provider | **OpenAI** (configurable — GPT-4o-mini default) |
| ORM | **SQLAlchemy 2 async** + asyncpg |
| Migrations | **Alembic** |
| HTTP client | **httpx** (async) |
| Cache/messaging | **Redis** |
| Logging | **structlog** |
| Validation | **Pydantic v2** |
| Dependency spec | `pyproject.toml` |

### Frontend

| Component | Technology |
|-----------|-----------|
| Framework | **Next.js 15.3** (App Router) |
| UI library | **React 19** |
| Styling | **Tailwind CSS 3** |
| Language | **TypeScript 5** |
| State management | Local `useState` / `useCallback` (no Redux/Zustand) |

### Infrastructure

| Component | Technology |
|-----------|-----------|
| Database | **PostgreSQL 16** (via Docker) |
| Cache | **Redis 7** (via Docker) |
| Local containers | `docker-compose.yml` |
| Application containers | **None yet** — no Dockerfile for app |
| CI/CD | **None yet** |

---

## 4. Local Development Setup

### Prerequisites

- Docker Desktop (for Postgres + Redis)
- Python 3.11+
- Node.js 18+ / npm
- An OpenAI API key

### Step 1 — Start infrastructure

```bash
cd service-request-chatbot
docker compose up -d
```

This starts:
- PostgreSQL on `localhost:5432` — database: `service_request_chatbot`
- Redis on `localhost:6379`

### Step 2 — Backend setup

```bash
cd service-request-chatbot/backend

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Create environment file
cp .env.example .env
# Edit .env — minimum required: OPENAI_API_KEY

# Run migrations
alembic upgrade head

# Start backend
uvicorn app.main:app --reload --port 8000
```

Backend will be available at:
- `http://localhost:8000` — API
- `http://localhost:8000/docs` — Swagger UI
- `http://localhost:8000/redoc` — ReDoc

### Step 3 — Frontend setup

```bash
cd service-request-chatbot/frontend

npm install

# Create environment file
cp .env.example .env.local
# Default: NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

npm run dev
```

Frontend will be available at:
- `http://localhost:3000` — Chat UI
- `http://localhost:3000/admin/agent-observability` — Observability admin

### Running tests

```bash
cd service-request-chatbot/backend

# All unit + integration + e2e tests
pytest

# With coverage
pytest --cov=app

# Live eval (requires running backend)
python -m tests.eval.run_eval
```

### Mock mode

If `SERVICE_REQUEST_API_BASE_URL` and `LEASE_TENANT_API_BASE_URL` are left empty in `.env`, the system uses built-in mocks:

- **Mock leases:** `t0105712`, `t0208831`, `t0301144`, `t0419977`
- **Mock SR creation:** returns a fake SR ID
- All graph logic, extraction, validation, and state persistence still run end-to-end

---

## 5. Architecture Overview

### High-level flow

```
User message (browser)
        ↓
Next.js frontend (POST /api/chat/service-request)
        ↓
ChatOrchestrationService
  ├── Injection scan (injection_guard.py)
  ├── Load session from DB
  ├── Restore graph state (ConversationStateService)
  ├── Invoke LangGraph (service_request_graph.py)
  └── Persist state + trace
        ↓
LangGraph Nodes (25 nodes, stateless per turn)
  ├── load_session → sr_status_sync → supervisor
  ├── supervisor → handover_entry / fm_review_entry / rdd_review_entry
  ├── field_extraction → merge_state → lease_lookup → validation
  ├── missing_field (loop) or confirmation
  ├── payload_builder → api_submission
  └── response_generation → save_state
        ↓
Cenomi Platform APIs (or mocks)
  ├── POST /service-requests  (CREATE_SR)
  ├── PATCH /service-requests/{id}  (FM review save/approve)
  ├── POST /service-requests (RDD report submit)
  └── PUT /files  (document upload)
```

### Critical design rule: LLM proposes, code decides

| LLM does | Code does |
|----------|----------|
| Understand user intent | Route to correct workflow stage |
| Extract user-provided fields | Validate fields deterministically |
| Ask natural follow-up questions | Protect backend-derived fields |
| Generate conversational responses | Build API payloads |
| Summarize collected data | Call platform endpoints |
| Help user correct missing info | Enforce permissions and confirmation |

**The LLM never builds payloads, never calls APIs, and never decides if a platform action is safe.**

---

## 6. Backend — Detailed Walkthrough

### 6.1 Entry point and app factory

`app/main.py` — `create_app()` creates the FastAPI instance, registers routes and CORS middleware.

### 6.2 API routes

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | Liveness check |
| `GET` | `/api/v1/ready` | Readiness (DB + Redis ping) |
| `POST` | `/api/chat/service-request` | **Primary chat endpoint** |
| `POST` | `/api/v1/upload` | File upload (MIME validation stub — needs completion) |
| `GET` | `/api/observability/traces` | Paginated trace list |
| `GET` | `/api/observability/traces/{trace_id}` | Trace detail |
| `POST` | `/api/observability/traces/{trace_id}/feedback` | Submit feedback |
| `GET` | `/api/observability/sessions/{session_id}/replay` | Session replay |
| `GET` | `/api/v1/observability/metrics/summary` | Aggregate metrics |

### 6.3 Chat orchestration service

`app/services/chat_orchestration_service.py` → `ChatOrchestrationService.process_turn()`

Per-turn sequence:
1. Validate user_id and message
2. Scan message for prompt injection (`injection_guard.scan_message()`)
3. Load or create `ChatSession` from DB
4. Load `ServiceRequestDraft` state via `ConversationStateService`
5. Build `ServiceRequestGraphState` from persisted data
6. Invoke compiled LangGraph (`get_compiled_graph().invoke(state)`)
7. Extract response from final state
8. Persist messages + updated draft
9. Return response to frontend

### 6.4 LangGraph — the agent graph

File: `app/agents/graph/service_request_graph.py`

The graph is compiled once at startup via `get_compiled_graph()` and reused. It is **stateless** — full state is loaded from the DB at the start of every turn and saved at the end.

#### Graph nodes (25 total)

| Node | File | Purpose |
|------|------|---------|
| `load_session` | `load_session_node.py` | Load session + draft from DB |
| `sr_status_sync` | `sr_status_sync_node.py` | Sync SR status from platform (if sr_id exists) |
| `supervisor` | `supervisor_node.py` | LLM classifies user intent → routes |
| `preview` | `preview_node.py` | Draft SR preview for user |
| `registry` | `registry_node.py` | Select correct agent from registry |
| `handover_entry` | `handover_entry_node.py` | Entry for CREATE_SR stage |
| `fm_review_entry` | `fm_review_entry_node.py` | Entry for FM_REVIEW stage |
| `rdd_review_entry` | `rdd_review_entry_node.py` | Entry for RDD_REVIEW stage |
| `field_extraction` | `field_extraction_node.py` | LLM extracts fields from user message |
| `merge_state` | `merge_state_node.py` | Merges extracted fields (protects backend fields) |
| `lease_lookup` | `lease_lookup_node.py` | Fetches/resolves lease details |
| `validation` | `validation_node.py` | Deterministic field validation |
| `missing_field` | `missing_field_node.py` | Generates follow-up question for missing field |
| `confirmation` / `fm_confirmation` / `rdd_confirmation` | `confirmation_node.py` | Confirmation gate before platform call |
| `payload_builder` | `payload_builder_node.py` | Builds CREATE SR payload |
| `fm_payload_builder` | `fm_payload_builder_node.py` | Builds FM review payload |
| `rdd_payload_builder` | `rdd_payload_builder_node.py` | Builds RDD report payload |
| `api_submission` | `api_submission_node.py` | Calls platform POST /service-requests |
| `fm_api_submission` | `fm_api_submission_node.py` | Calls platform PATCH /service-requests |
| `rdd_api_submission` | `rdd_api_submission_node.py` | Calls platform POST /service-requests (report) |
| `response_generation` | `response_generation_node.py` | LLM generates natural language response |
| `save_state` | `save_state_node.py` | Persists updated draft to DB |

#### Graph state type

`ServiceRequestGraphState` in `app/agents/graph/state.py` — a TypedDict containing:
- `session_id`, `user_id`, `user_message`, `action_override`
- `intent`, `active_agent`, `workflow_stage`
- `collected_data` — all fields gathered so far
- `missing_fields`, `validation_errors`
- `response_text`, `ui_components`
- `backend_refs` — sr_id, platform references (protected from LLM)
- `documents` — uploaded document metadata

#### Supervisor intents

`SupervisorDecision` in `supervisor_schema.py`:
- `CREATE_HANDOVER_SERVICE_REQUEST`
- `UPDATE_HANDOVER_SERVICE_REQUEST`
- `APPROVE_HANDOVER_SERVICE_REQUEST`
- `CHECK_SERVICE_REQUEST_STATUS`
- `PREVIEW_SERVICE_REQUEST`
- `UNKNOWN`

#### Agent registry

`SERVICE_REQUEST_AGENT_REGISTRY` in `agents/registries/service_request_registry.py`

Currently one entry: `("FIT_OUT_AND_HANDOVER", "HANDOVER")` → `handover_service_request_agent`

### 6.5 Services layer

| Service | File | Purpose |
|---------|------|---------|
| `ChatOrchestrationService` | `services/chat_orchestration_service.py` | Per-turn orchestration |
| `ConversationStateService` | `agents/services/conversation_state_service.py` | State ↔ DB persistence |
| `LLMGateway` | `agents/llm/gateway.py` | OpenAI JSON-mode completions |
| `FieldExtractionService` | `agents/services/...` | LLM field extraction |
| `ValidationService` | `agents/services/validation_service.py` | Deterministic validation |
| `PayloadBuilderService` | `agents/services/payload_builder_service.py` | Payload construction |
| `LeaseLookupService` | `agents/services/lease_lookup_service.py` | HTTP / mock lease lookup |
| `ServiceRequestAPIService` | `agents/services/service_request_api_service.py` | Platform SR API calls |
| `ServiceRequestPlatformClient` | `agents/services/platform_api_client.py` | Unified platform HTTP client |
| `PermissionService` | `core/permissions.py` | Role-based access checks |

### 6.6 Platform API client

`app/agents/services/platform_api_client.py` → `ServiceRequestPlatformClient`

Handles authentication (login + bearer token) and all platform HTTP calls. When `SERVICE_REQUEST_API_BASE_URL` is empty, it falls back to mock responses.

---

## 7. Frontend — Detailed Walkthrough

### 7.1 Pages

| Route | Component | Description |
|-------|-----------|-------------|
| `/` | Redirect | Redirects to `/service-request-chat` |
| `/service-request-chat` | `ServiceRequestChat` | Main tenant chat interface |
| `/admin/agent-observability` | Trace list | Admin trace/metrics view |
| `/admin/agent-observability/traces/[traceId]` | Trace detail | Per-trace run tree + replay |

### 7.2 Chat components

`components/chatbot/`:

| Component | Purpose |
|-----------|---------|
| `ServiceRequestChat.tsx` | Main orchestrator — manages messages, session, workflow state |
| `MessageBubble.tsx` | Renders text chat messages |
| `ChatInput.tsx` | User text input |
| `LeaseSelectionCard.tsx` | Multi-lease disambiguation UI |
| `ServiceRequestSummaryCard.tsx` | Confirmation card before SR creation |
| `FieldCorrectionPanel.tsx` | Inline field editing |
| `WorkflowProgressCard.tsx` | Step-by-step workflow progress indicator |
| `SRPreviewCard.tsx` | Draft SR preview |
| `DocumentRequirementCard.tsx` | FM/RDD document upload requirements |
| `FileUploadButton.tsx` | File picker |
| `AttachmentPreview.tsx` | Preview of uploaded files |

### 7.3 API clients

`lib/api/`:

| Client | File | Endpoint |
|--------|------|----------|
| Chat | `chat-client.ts` → `postServiceRequestChat()` | `POST {API_BASE_URL}/api/chat/service-request` |
| Observability | `observability-client.ts` | `/api/observability/...`, `/api/v1/observability/metrics/summary` |
| Upload | `upload-client.ts` → `uploadDocument()` | `POST {API_BASE_URL}/api/v1/upload` |

### 7.4 Known frontend issues

- `chat-client.ts` **hardcodes** `user_id: "demo_user"` — this needs to come from real auth
- `NEXT_PUBLIC_API_V1_PREFIX` is used by upload + metrics clients but the **chat client hardcodes `/api`** — verify consistency when wiring auth
- No global state management — all state is local to `ServiceRequestChat.tsx`

---

## 8. Database & State Management

### 8.1 Databases

| Store | Role | Connection |
|-------|------|-----------|
| **PostgreSQL 16** | Primary persistence | `DATABASE_URL` env var |
| **Redis 7** | Readiness probe only today; reserved for caching/rate limiting | `REDIS_URL` env var |

### 8.2 Domain tables

| Table | Model | Key fields |
|-------|-------|-----------|
| `chat_sessions` | `ChatSession` | `session_id`, `user_id`, `active_agent`, `intent`, `workflow_stage`, `status` |
| `chat_messages` | `ChatMessage` | `session_id`, `role`, `content`, `timestamp` |
| `service_request_drafts` | `ServiceRequestDraft` | `session_id`, `collected_data (JSONB)`, `missing_fields`, `documents`, `backend_refs` |
| `service_request_chat_audit_logs` | `ServiceRequestChatAuditLog` | All platform-bound actions with payloads |

### 8.3 Observability tables

| Table | Purpose |
|-------|---------|
| `agent_traces` | Per-session trace container |
| `agent_runs` | Per-node execution record |
| `agent_state_snapshots` | State before/after each node |
| `agent_state_diffs` | Diff between snapshots |
| `agent_llm_calls` | Every LLM call with tokens/latency |
| `agent_tool_calls` | Every tool/API call |
| `agent_feedback` | User feedback on traces |

### 8.4 Workflow stages

Stored in `chat_sessions.workflow_stage`:

| Stage | Meaning |
|-------|---------|
| `CREATE_SR` | Collecting fields for initial SR creation |
| `FM_REVIEW` | FM Manager reviewing and uploading documents |
| `RDD_REVIEW` | DD Engineer uploading and submitting handover report |
| `SR_CREATED` | SR created, awaiting platform status update |
| `SR_COMPLETED` | Full workflow complete |

### 8.5 Migrations

Run with `alembic upgrade head`. Two migrations:

| Revision | Creates |
|----------|---------|
| `001_initial_schema` | Domain tables + legacy stubs |
| `002_agent_observability` | All observability tables |

---

## 9. Observability System

### 9.1 Trace hierarchy

```
AgentTrace (per session/conversation)
  └── AgentRun (per graph node execution)
        ├── AgentStateSnapshot (state before node)
        ├── AgentStateSnapshot (state after node)
        ├── AgentStateDiff (what changed)
        ├── AgentLLMCall (if node used LLM)
        └── AgentToolCall (if node called external API)
```

### 9.2 Admin UI

Available at `http://localhost:3000/admin/agent-observability`:
- Trace list with filters and metrics
- Per-trace run tree visualization
- State diff viewer
- LLM call inspector (prompt, response, tokens, latency)
- Tool call inspector
- Conversation replay
- Feedback panel

### 9.3 Sensitive field redaction

`app/observability/redaction.py` — fields like `access_token`, `internal_api_token`, `contract_id`, `brand_id` are automatically redacted in stored traces.

---

## 10. Security Guardrails

### Injection guard

`app/core/injection_guard.py` → `scan_message()` — runs before the graph on every user message. Detects prompt injection patterns and blocks the request before any LLM call.

### Confirmation gate

The graph will **never** call a platform write API without passing through a confirmation node. The user must either:
- Send an explicit confirmation keyword (e.g. "confirm", "yes proceed")
- OR send an `action_override` field in the request body (for structured UI button clicks)

### Backend field protection

Fields marked as backend-derived (e.g., `tenant_profile_id`, `property_id`, `brand_id`, `lease_id`) are set in `merge_state_node` with a protection flag. Any LLM-extracted values for these fields are silently discarded.

### Permissions

`app/core/permissions.py` → `PermissionService` — checks user role against allowed roles for each action.

**Known issue:** Unknown/unrecognised actions currently **fail-open** (allow by default). This must be changed to **fail-closed** before production.

### Auth status

Auth is POC-level: `user_id` is passed in the request body from the frontend. `HTTPBearer` is optional and defaults to anonymous. A proper JWT/session integration is needed before production use.

---

## 11. Testing Strategy

### Test layers

```
backend/tests/
├── unit/           # ~33 files — isolated, mocked DB/LLM/APIs
├── integration/    # 5 files — compiled graph with mocked LLM and APIs
├── e2e/            # 1 file — full ASGI stack, all external mocked
└── eval/           # Live HTTP scenario runner (not pytest)
```

### Notable test files

| Area | Test file |
|------|----------|
| Security guardrails | `unit/test_security_guardrails.py`, `unit/test_injection_guard.py` |
| Graph routing | `unit/test_supervisor_routing.py`, `integration/test_service_request_graph.py` |
| FM/RDD nodes | `unit/test_fm_nodes.py`, `unit/test_rdd_nodes.py` |
| Validation (100 tests) | `unit/test_validation_service.py` |
| Payload builder | `unit/test_payload_builder_service.py` |
| Lease lookup | `unit/test_lease_lookup_service.py` |
| Platform client | `unit/test_platform_api_client.py` |
| Observability | `unit/test_trace_manager.py`, `unit/test_observability_api.py` |
| E2E | `e2e/test_handover_sr_e2e.py` (10 scenarios) |

### Running eval against live backend

```bash
# Start backend first, then:
cd service-request-chatbot/backend
python -m tests.eval.run_eval
```

This drives 9 scenarios from `docs/e2e-test-guide.md` against the real running backend. Results are written to `results/`.

---

## 12. Current Implementation State

### What is fully implemented and working

| Feature | Status |
|---------|--------|
| FastAPI backend skeleton | ✅ Complete |
| Next.js frontend with chat UI | ✅ Complete |
| LangGraph graph with 25 nodes | ✅ Complete |
| Supervisor intent classification (LLM) | ✅ Complete |
| Field extraction (LLM, per-stage schemas) | ✅ Complete |
| Backend field protection in merge_state | ✅ Complete |
| Lease lookup (HTTP + mock) | ✅ Complete |
| Deterministic validation for CREATE_SR | ✅ Complete |
| Confirmation gate (keyword + action_override) | ✅ Complete |
| CREATE_SR payload builder | ✅ Complete (verify exact Postman shape — see Gap 1) |
| Platform SR creation API call | ✅ Complete |
| Conversation state persistence (PostgreSQL) | ✅ Complete |
| Per-turn tracing and observability | ✅ Complete |
| Admin observability UI | ✅ Complete |
| Prompt injection guard | ✅ Complete |
| Role-based permission checks (partial) | ✅ Partial |
| FM/RDD graph nodes (entry, payload builder, submission) | ✅ Nodes exist |
| SR status sync node | ✅ Node exists |
| Alembic migrations | ✅ Complete |
| Unit test suite (~33 files) | ✅ Complete |
| E2E test suite (10 scenarios) | ✅ Complete |
| Docker Compose infrastructure | ✅ Complete |
| Mock mode for all external APIs | ✅ Complete |

### What is partially implemented

| Feature | Status | Gap |
|---------|--------|-----|
| File upload route | ⚠️ Partial stub | Does not call `PUT /files` on platform yet |
| FM_REVIEW end-to-end | ⚠️ Nodes exist | Upload + save progress + approve not fully wired |
| RDD_REVIEW end-to-end | ⚠️ Nodes exist | Upload + submit report not fully wired |
| Platform status sync | ⚠️ Node exists | Full mapping from platform operation status not verified |
| Permission enforcement | ⚠️ Partial | Unknown actions fail-open; should fail-closed |
| Frontend auth | ⚠️ Demo only | `user_id` hardcoded as `"demo_user"` |
| CREATE_SR payload | ⚠️ Working | Exact Postman field names/shape needs verification |

### What is not implemented

| Feature | Status |
|---------|--------|
| Real file upload through platform `PUT /files` | ❌ Not done |
| Structured UI actions (beyond generic confirm/cancel) | ❌ Not done |
| Token re-authentication on expiry | ❌ Not done |
| Webhook/polling for platform status changes | ❌ Not done |
| Application Docker images | ❌ Not done |
| CI/CD pipeline | ❌ Not done |
| Redis usage beyond health check | ❌ Not done |

---

## 13. Known Gaps & Issues

These are documented in full in `gaps_and_pc/chatbot_postman_gap_implementation_plan.md`.

### Gap 1 — CREATE_SR payload must exactly match Postman

The platform expects specific field names and structure. The current `build_create_handover_payload()` needs to be verified against the Postman collection. Key fields to verify:

- `inspectionDoneBy` AND `inspection_done_by` (both must be sent)
- `startDateLT` / `endDateLT` (local display format derived from ISO dates)
- `lease_brand_mall` (derived: `"{lease_code} - {brand} - {mall}"`)
- `documents_ids: []` and `document_status_map: []` (empty arrays for create)
- `user_action: null`
- Top-level `status` must **NOT** be sent during initial create

### Gap 2 — Backend-derived field enrichment

When the user provides a lease code / brand / mall, the lease lookup must resolve all of:
`tenant_profile_id`, `property_id`, `brand_id`, `lease_id`, `contract_id`, `mall`, `brand`, `city`, `unit_codes`, `contracted_area`, `company_name`, `tenant_contact`, `lease_brand_mall`

If the current lease endpoint does not return all of these, an enrichment call must be added.

### Gap 3 — File upload not wired to platform

`POST /api/v1/upload` validates MIME type but does not call the platform `PUT /files` endpoint. The full upload flow must be:

```
Frontend → POST /api/v1/upload
Backend → validate MIME + document type
Backend → call platform PUT /files?query=SERVICE_REQUEST&...
Platform → returns document_id
Backend → store document metadata in draft
```

### Gap 4 — FM_REVIEW not end-to-end

The graph nodes exist but the following need verification/completion:
- Collect `unit_readiness_date` and `expected_handover_date`
- Upload FM documents (`SR_HANDOVER_CHECKLIST`, `SR_HANDOVER_SITE_SURVEY`, `SR_COP_CHECKLIST_OTHER`)
- Call `PATCH /service-requests/{sr_id}` with `status: IN_PROCESS` (save progress)
- Call `PATCH /service-requests/{sr_id}` with `status: APPROVED` (approve)

### Gap 5 — RDD_REVIEW not end-to-end

The graph nodes exist but need completion:
- Collect `guideLineLink`, `actual_handover_date`, `fitout_start_date`, `fitout_end_date`, `trading_date`
- Upload `DR_SR_HANDOVER_REPORT` with `document_type_status: APPROVED`
- Call `POST /service-requests` with `status: REPORT_SUBMITTED` and existing `service_request_id`
- Enforce date ordering: `actual_handover_date ≤ fitout_start_date ≤ fitout_end_date ≤ trading_date`

### Gap 6 — Platform status sync needs validation

`sr_status_sync_node` exists but the mapping from `service_request_operations` fields to chatbot `workflow_stage` needs to be verified and completed.

### Gap 7 — Permissions fail-open on unknown actions

`PermissionService` allows unknown action names by default. This must be flipped to fail-closed before production.

### Gap 8 — Structured UI actions

The frontend only supports generic `confirm`/`cancel`. Stage-specific actions are needed:
`confirm_create_sr`, `save_fm_progress`, `approve_fm_review`, `submit_rdd_report`, `select_lease`, `upload_document`

### Gap 9 — No application Dockerfile

Only infrastructure (Postgres, Redis) is containerised. The backend and frontend have no Dockerfiles. These are needed for any deployment beyond local development.

---

## 14. Tenant Platform Integration Guide

This section covers everything needed to integrate the chatbot with the Cenomi tenant platform APIs.

### 14.1 Authentication

All platform calls use a service-to-service login flow:

**Login endpoint:**
```
POST {PLATFORM_AUTH_BASE_URL}/cenomi-ai/login
```

Headers:
```
Content-Type: application/json
x-internal-api-token: {PLATFORM_INTERNAL_API_TOKEN}
```

Body:
```json
{ "email": "{PLATFORM_LOGIN_EMAIL}" }
```

Response:
```json
{ "success": true, "data": { "access_token": "..." } }
```

The returned `access_token` is used as a Bearer token for all subsequent platform calls.

**Config variables to set:**
- `PLATFORM_AUTH_BASE_URL` — defaults to `SERVICE_REQUEST_API_BASE_URL` if blank
- `PLATFORM_INTERNAL_API_TOKEN` — internal API token (secret)
- `PLATFORM_LOGIN_EMAIL` — login email for the service account

This is implemented in `ServiceRequestPlatformClient.login()`. Token refresh on expiry is not yet implemented — add a try/re-login wrapper around API calls.

---

### 14.2 Platform endpoints reference

#### Fetch workflow schema
```
GET {BASE}/service-requests/workflows?service_category=FIT_OUT_AND_HANDOVER&sub_category=HANDOVER&sort_by=updated_at&order=ASC
```
Use this to verify the expected form fields and document types for the Handover workflow. Cache the response.

---

#### Create Handover Service Request
```
POST {BASE}/service-requests
Authorization: Bearer {access_token}
```

Request body (exact shape — verify against `gaps_and_pc/chatbot_postman_gap_implementation_plan.md`):
```json
{
  "payload": {
    "mall": "...",
    "brand": "...",
    "lease": "{lease_code}",
    "notes": "",
    "title": "...",
    "endDate": "2026-05-13T13:50:00.000Z",
    "comments": "...",
    "startDate": "2026-05-12T13:50:00.000Z",
    "attachments": "",
    "description": "...",
    "documents_ids": [],
    "guideLineLink": "",
    "inspectionDoneBy": "FM_MANAGER",
    "lease_brand_mall": "{lease_code} - {brand} - {mall}",
    "inspection_done_by": "FM_MANAGER",
    "document_status_map": [],
    "unit_readiness_date": "",
    "expected_handover_date": "",
    "company_name": "...",
    "tenant_contact": "",
    "user_action": null,
    "unit_codes": ["FF050"],
    "contracted_area": 420,
    "city": "...",
    "brand_id": 123,
    "tenant_profile_id": 116,
    "contract_id": 456,
    "property_id": 789,
    "startDateLT": "12/05/2026 07:20 PM",
    "endDateLT": "13/05/2026 07:20 PM"
  },
  "title": "...",
  "tenant_profile_id": 116,
  "property_id": 789,
  "service_category": "FIT_OUT_AND_HANDOVER",
  "sub_category": "HANDOVER",
  "lease_code": "{lease_code}",
  "lease_id": 456,
  "service_request_id": ""
}
```

**Important:** Do NOT include top-level `status` field during initial create.

Response:
```json
{ "success": true, "data": { "service_request_id": "10197" } }
```

Store the `service_request_id` in `backend_refs.sr_id` in the session draft.

---

#### Get Service Request by ID (status sync)
```
GET {BASE}/service-requests/{sr_id}
Authorization: Bearer {access_token}
```

Use this at the start of every chat turn when `sr_id` exists. Map `service_request_operations` to chatbot `workflow_stage`:

| Platform operation role | Platform status | Chatbot stage |
|------------------------|----------------|--------------|
| `MALL_MANAGER` | `IN_PROGRESS` | `CREATE_SR` |
| `FM_MANAGER` or `OPERATIONS` | `IN_PROGRESS` | `FM_REVIEW` |
| `DD_ENGINEER` | `IN_PROGRESS` | `RDD_REVIEW` |
| All operations | `FINISHED` / completed | `SR_COMPLETED` |

---

#### Upload file
```
PUT {FILE_UPLOAD_API_BASE_URL}/files?query=SERVICE_REQUEST&file_extension=pdf&document_type_id={document_type_id}&lease_id={lease_id}&brand_id={brand_id}&property_id={property_id}&lease_code={lease_code}&sr_id={sr_id}&tenant_profile_id={tenant_profile_id}&document_type_status={status}&signed_url=true&file_name={file_name}
Authorization: Bearer {access_token}
```

All query parameters are required. Source for each:

| Parameter | Source |
|-----------|--------|
| `file_extension` | Derived from uploaded file |
| `document_type_id` | Selected document type (e.g., `SR_HANDOVER_CHECKLIST`) |
| `lease_id`, `brand_id`, `property_id`, `lease_code`, `tenant_profile_id` | Backend lookup (stored in draft) |
| `sr_id` | `backend_refs.sr_id` (must exist before upload) |
| `document_type_status` | Empty for FM docs; `APPROVED` for RDD report |
| `signed_url` | Always `true` |

Response:
```json
{
  "success": true,
  "data": {
    "document_id": "uuid",
    "file_path": "...",
    "signed_url": "...",
    "document_type_id": "SR_HANDOVER_CHECKLIST",
    "appian_document_id": 0
  }
}
```

Store the `document_id` in `draft.documents` and add to `documents_ids`.

**Supported document types:**
- FM stage: `SR_HANDOVER_CHECKLIST`, `SR_HANDOVER_SITE_SURVEY`, `SR_COP_CHECKLIST_OTHER`, `SR_HANDOVER_OTHER`
- RDD stage: `DR_SR_HANDOVER_REPORT`, `SR_REJECTED_HANDOVER_REPORT`, `SR_HANDOVER_OTHER`

---

#### Save FM review progress
```
PATCH {BASE}/service-requests/{sr_id}
Authorization: Bearer {access_token}
```

Body:
```json
{
  "payload": {
    "documents_ids": ["{doc_fm_uuid}"],
    "document_status_map": [
      {
        "id": "{doc_fm_uuid}",
        "document_status": "",
        "handover_date": "",
        "actual_handover_date": "",
        "fitout_start_date": "",
        "fitout_end_date": "",
        "trading_date": ""
      }
    ],
    "unit_readiness_date": "2026-05-12",
    "expected_handover_date": "2026-05-20",
    "document_saved": true
  },
  "status": "IN_PROCESS",
  "service_request_id": "{sr_id}"
}
```

---

#### Approve FM review
```
PATCH {BASE}/service-requests/{sr_id}
Authorization: Bearer {access_token}
```

Body:
```json
{
  "payload": {
    "documents_ids": ["{doc_fm_uuid}"],
    "document_status_map": [
      {
        "id": "{doc_fm_uuid}",
        "document_status": "",
        "expected_handover_date": "2026-05-20"
      }
    ],
    "unit_readiness_date": "2026-05-12",
    "expected_handover_date": "2026-05-20"
  },
  "user_action": null,
  "status": "APPROVED",
  "comment": "ok",
  "title": "...",
  "sub_category": "HANDOVER"
}
```

After approval, `DD_ENGINEER` operation moves to `IN_PROGRESS` on the platform.

---

#### Submit RDD handover report
```
POST {BASE}/service-requests
Authorization: Bearer {access_token}
```

Body:
```json
{
  "payload": {
    "guideLineLink": "http://...",
    "documents_ids": ["{doc_fm_uuid}", "{doc_dd_report_uuid}"],
    "document_status_map": [
      {
        "id": "{doc_fm_uuid}",
        "document_status": "",
        "expected_handover_date": "2026-05-20"
      },
      {
        "id": "{doc_dd_report_uuid}",
        "document_status": "APPROVED",
        "handover_date": "",
        "actual_handover_date": "12/05/2026",
        "fitout_start_date": "14/05/2026",
        "fitout_end_date": "21/05/2026",
        "trading_date": "28/05/2026"
      }
    ]
  },
  "status": "REPORT_SUBMITTED",
  "service_request_id": "{sr_id}"
}
```

Note: `POST /service-requests` is used for both create (empty `service_request_id`) and report submission (existing `service_request_id`).

---

### 14.3 Role → action mapping (enforce in PermissionService)

| Action | Allowed roles |
|--------|--------------|
| `CREATE_HANDOVER_SR` | `MALL_MANAGER` |
| `VIEW_HANDOVER_SR` | `MALL_MANAGER`, `FM_MANAGER`, `OPERATIONS`, `DD_ENGINEER` |
| `UPLOAD_FM_HANDOVER_DOCUMENT` | `FM_MANAGER`, `OPERATIONS` |
| `SAVE_FM_HANDOVER_PROGRESS` | `FM_MANAGER`, `OPERATIONS` |
| `APPROVE_FM_HANDOVER` | `FM_MANAGER` or `OPERATIONS` (based on `inspection_done_by` field) |
| `REJECT_FM_HANDOVER` | `FM_MANAGER` or `OPERATIONS` |
| `UPLOAD_RDD_HANDOVER_REPORT` | `DD_ENGINEER` |
| `SUBMIT_RDD_HANDOVER_REPORT` | `DD_ENGINEER` |
| Any unknown action | **DENY** (fail-closed) |

---

### 14.4 Lease / tenant lookup

When the user mentions a brand, mall, or lease code, the chatbot calls the lease lookup service to resolve all backend-derived fields. The lookup must return (or the response must be enriched to include):

```
tenant_profile_id, property_id, brand_id, lease_id, contract_id,
mall, brand, city, unit_codes, contracted_area, company_name, tenant_contact
```

The derived field `lease_brand_mall` is then computed as: `"{lease_code} - {brand} - {mall}"`

Config: `LEASE_TENANT_API_BASE_URL` — leave empty to use mock data.

---

### 14.5 Wiring the integration — step by step

1. **Set environment variables** in `backend/.env`:
   ```
   SERVICE_REQUEST_API_BASE_URL=https://your-platform-api.cenomi.com
   LEASE_TENANT_API_BASE_URL=https://your-lease-api.cenomi.com
   FILE_UPLOAD_API_BASE_URL=https://your-file-api.cenomi.com
   PLATFORM_AUTH_BASE_URL=https://your-platform-api.cenomi.com
   PLATFORM_INTERNAL_API_TOKEN=your-token
   PLATFORM_LOGIN_EMAIL=service-account@cenomi.com
   ```

2. **Verify `ServiceRequestPlatformClient`** (`app/agents/services/platform_api_client.py`) has all the methods needed (`login`, `create_service_request`, `get_service_request`, `patch_service_request`, `upload_file`, `submit_service_request_report`).

3. **Verify `build_create_handover_payload()`** output matches the exact Postman payload shape (Gap 1).

4. **Wire file upload** — update `app/api/routes/upload.py` to call `ServiceRequestPlatformClient.upload_file()` and store the returned `document_id` in the session draft.

5. **Wire status sync** — ensure `sr_status_sync_node` calls `GET /service-requests/{sr_id}` and maps `service_request_operations` to `workflow_stage` correctly.

6. **Wire FM_REVIEW** — ensure `fm_payload_builder_node` and `fm_api_submission_node` call the correct `PATCH` endpoints with the correct payloads.

7. **Wire RDD_REVIEW** — ensure `rdd_payload_builder_node` and `rdd_api_submission_node` call `POST /service-requests` with `status: REPORT_SUBMITTED`.

8. **Harden permissions** — change `PermissionService` unknown action handling from fail-open to fail-closed.

9. **Add structured UI actions** — extend frontend to send specific `action_override` values (`save_fm_progress`, `approve_fm_review`, `submit_rdd_report`) from button clicks instead of relying on natural language confirmation alone.

---

## 15. Recommended Implementation Order

From `gaps_and_pc/handover_chatbot_gap_closure_implementation.md`:

```
1.  Align CREATE_SR payload exactly with Postman
2.  Verify lease lookup resolves all backend-derived fields
3.  Fix any frontend/backend route mismatches
4.  Implement real file upload: frontend → backend → platform PUT /files
5.  Store uploaded document metadata in draft state
6.  Add status sync: GET /service-requests/{sr_id} before every turn with existing SR
7.  Implement FM_REVIEW routing and entry node (if not complete)
8.  Implement FM_REVIEW payload builders: save progress + approve
9.  Implement FM_REVIEW endpoint calls: PATCH IN_PROCESS + PATCH APPROVED
10. Implement RDD_REVIEW routing and entry node (if not complete)
11. Implement RDD_REVIEW payload builder: submit report
12. Implement RDD endpoint calls: PUT DR_SR_HANDOVER_REPORT + POST REPORT_SUBMITTED
13. Harden permission service: unknown actions fail-closed
14. Add structured UI actions for all platform-changing actions
15. Add platform API error recovery and retry handling
16. Add E2E tests mirroring the Postman collection sequence
17. Refactor into registries: payload builder registry, extraction registry, dynamic stage routing
18. Add application Dockerfiles
19. Add CI/CD pipeline
```

---

## 16. Environment Variables Reference

### Backend (`backend/.env`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_NAME` | No | `service-request-chatbot-api` | App name |
| `ENVIRONMENT` | No | `development` | `development` / `production` |
| `DEBUG` | No | `false` | Enable debug mode |
| `API_V1_PREFIX` | No | `/api/v1` | API prefix |
| `CORS_ORIGINS` | No | `http://localhost:3000` | Comma-separated allowed origins |
| `DATABASE_URL` | **Yes** | — | `postgresql+asyncpg://postgres:postgres@localhost:5432/service_request_chatbot` |
| `REDIS_URL` | No | — | `redis://localhost:6379/0` |
| `SERVICE_REQUEST_API_BASE_URL` | No | *(empty = mock)* | Cenomi platform SR API base URL |
| `LEASE_TENANT_API_BASE_URL` | No | *(empty = mock)* | Cenomi lease/tenant API base URL |
| `FILE_UPLOAD_API_BASE_URL` | No | *(empty = mock)* | Cenomi file upload API base URL |
| `PLATFORM_AUTH_BASE_URL` | No | *(defaults to SR URL)* | Platform auth endpoint base |
| `PLATFORM_INTERNAL_API_TOKEN` | **Yes (prod)** | — | Internal API token for service login |
| `PLATFORM_LOGIN_EMAIL` | **Yes (prod)** | — | Service account email for platform login |
| `JWT_SECRET_KEY` | **Yes (prod)** | `change-me-in-production` | JWT signing key |
| `JWT_ALGORITHM` | No | `HS256` | JWT algorithm |
| `OPENAI_API_KEY` | **Yes** | — | OpenAI API key |
| `LLM_MODEL` | No | `gpt-4o-mini` | OpenAI model name |
| `LLM_BASE_URL` | No | — | Custom LLM base URL (Azure/proxy) |
| `LLM_CONFIDENCE_THRESHOLD` | No | `0.6` | Minimum confidence for LLM extraction |

### Frontend (`frontend/.env.local`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEXT_PUBLIC_API_BASE_URL` | No | `http://localhost:8000` | Backend API base URL |
| `NEXT_PUBLIC_API_V1_PREFIX` | No | `/api/v1` | Used by upload and metrics clients |

---

## 17. Key Design Principles

These must be preserved by any developer extending this codebase:

### 1. LLM proposes, code decides

The LLM is used only for:
- **Supervisor** — intent classification
- **Field extraction** — extracting user-provided values from natural language
- **Response generation** — generating the natural language reply

Everything else is deterministic Python:
- Routing between graph nodes
- Field validation
- Payload construction
- Permission checks
- Platform API calls
- Confirmation enforcement

### 2. Stateless graph, stateful database

The LangGraph graph is compiled once and reused. It holds no persistent state. All state is loaded from PostgreSQL at the start of each turn (`load_session_node`) and saved back at the end (`save_state_node`). This means every HTTP request is a full, independent graph run.

### 3. No LangGraph interrupt/resume

The system does not use LangGraph's built-in interrupt/resume mechanism. Multi-turn conversation state is managed entirely through the `ServiceRequestDraft` DB record.

### 4. Backend-derived fields are immutable

Fields like `tenant_profile_id`, `brand_id`, `property_id` come from platform APIs, not from the user or LLM. Once set in `collected_data`, they cannot be overwritten by LLM extraction. This is enforced in `merge_state_node`.

### 5. No platform action without confirmation

The graph will never call a write API without passing through a confirmation node. The confirmation node requires either an explicit text confirmation or a structured `action_override`. This is non-negotiable for safety.

### 6. Defense in depth

- Injection guard runs before the graph (pre-LLM)
- Backend field protection runs in merge_state (post-LLM)
- Confirmation gate runs before every submission node
- Permission checks run at the action decision point
- Payload is built by code only, never by LLM

### 7. Full observability on every turn

Every chat turn creates a trace with nested runs, state snapshots, diffs, LLM calls, and tool calls. This is not optional — it is core to debugging, auditing, and production support.

---

*For questions about the architecture or specific implementation decisions, review the relevant docs file first. If still unclear, check the test files — they often reveal the intended behavior more clearly than the docs.*
