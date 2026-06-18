# Cenomi RDD Chatbot — Developer Handover Document

> **Prepared:** June 2026 — Updated June 2026 (Sprint 1 + Eval fixes)
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

### What it does today (Sprint 1 — complete)

**CREATE_SR (Mall Manager):**
- Tenant opens a chat and says something like *"I want to raise a handover request for Under Armour in Jawharat Jeddah"*
- The bot asks for required fields (start/end dates, inspection responsible, description)
- The bot resolves backend-derived fields (property ID, brand ID, lease IDs) via platform lookup APIs
- The bot shows a confirmation summary before any platform action
- The bot calls the Cenomi platform API to create the Service Request and returns the SR ID

**FM_REVIEW (FM Manager / Operations):**
- FM Manager opens a chat session for an existing SR
- The bot collects `unit_readiness_date` and auto-computes `expected_handover_date` (+7 days)
- FM Manager uploads inspection documents (`SR_HANDOVER_CHECKLIST`, `SR_HANDOVER_SITE_SURVEY`, `SR_COP_CHECKLIST_OTHER`)
- FM Manager saves progress (`PATCH IN_PROCESS`) or approves the review (`PATCH APPROVED`)

**RDD_REVIEW (DD Engineer) — two phases:**
- Phase 3a: DD Engineer uploads the handover report, provides guideline link and 4 contractual dates, submits report (`POST REPORT_SUBMITTED`)
- Phase 3b: DD Engineer performs final approval (`PATCH APPROVED`) → SR lifecycle complete (`SR_COMPLETED`)

### Full lifecycle

```
CREATE_SR  →  FM_REVIEW  →  RDD_REVIEW (submit)  →  RDD_REVIEW (final approve)  →  SR_COMPLETED
```

The one remaining integration gap is real file upload to the platform `PUT /files` endpoint (see Gap 3 in Section 13). All business logic, routing, payloads, permissions, and UI are complete.

---

## 2. Repository Structure

```
Cenomi-RDD-Chatbot/
├── service-request-chatbot/        # Main application
│   ├── backend/                    # FastAPI + LangGraph Python app
│   │   ├── app/                    # Application source
│   │   │   ├── agents/             # LangGraph graph, nodes, prompts, schemas, services
│   │   │   │   ├── graph/          # state.py, service_request_graph.py, nodes/
│   │   │   │   ├── prompts/        # supervisor_prompt.py, response_generation_prompt.py
│   │   │   │   ├── schemas/        # handover_schema.py (stage definitions, permissions)
│   │   │   │   └── services/       # payload_builder, permission, conversation_state, etc.
│   │   │   ├── api/routes/         # HTTP route handlers (chat.py, upload.py)
│   │   │   ├── core/               # Config, logging, security, Redis, injection guard
│   │   │   ├── db/                 # ORM models, async session, repositories
│   │   │   ├── observability/      # Trace manager, decorators, redaction, API routes
│   │   │   ├── services/           # Chat orchestration service
│   │   │   ├── types/              # Shared Pydantic types
│   │   │   └── main.py             # FastAPI app factory
│   │   ├── alembic/                # Database migrations
│   │   ├── tests/
│   │   │   ├── unit/               # ~37 files — isolated, mocked DB/LLM/APIs
│   │   │   ├── integration/        # 8 files — compiled graph with mocked LLM and APIs
│   │   │   ├── e2e/                # 1 file — full ASGI stack, all external mocked
│   │   │   └── eval/               # Live HTTP scenario runner (not pytest)
│   │   ├── pyproject.toml          # Python dependencies
│   │   └── .env.example            # Environment variable template
│   ├── frontend/                   # Next.js 15 app
│   │   ├── app/                    # App Router pages
│   │   ├── components/chatbot/     # Chat UI + stage-aware components
│   │   ├── lib/api/                # chat-client.ts, upload-client.ts
│   │   ├── lib/types/              # chat.ts — shared TypeScript contracts
│   │   └── package.json
│   ├── docs/                       # 21 documentation files
│   │   ├── plans/                  # Sprint plans (plan-01 through plan-04 + jira-sprint-1)
│   │   ├── architecture.md
│   │   ├── agent-architecture.md   # Sprint 1 graph, role matrix, evolution roadmap
│   │   ├── agent-design.md         # Node inventory, routing, stage data contracts
│   │   ├── handover-workflow.md    # Stage field list, validation, payload shapes
│   │   └── ...                     # See Key Documentation Files below
│   ├── results/                    # Test result reports
│   ├── docker-compose.yml          # Postgres + Redis
│   └── README.md
├── rdd_life_cycle/                 # Business and API reference docs
│   ├── handover-business-flow.md   # Business journey, expected handover date rule
│   └── handover-service-request (1).md  # Full platform API spec by stage
└── gaps_and_pc/                    # Postman collection + gap analysis docs
    ├── Handover SR — FIT_OUT_AND_HANDOVER - HANDOVER.postman_collection.json
    ├── chatbot_postman_gap_implementation_plan.md
    └── handover_chatbot_gap_closure_implementation.md
```

### Key documentation files (read these first)

| File | What it covers |
|------|---------------|
| `service-request-chatbot/docs/architecture.md` | Full-stack design, LangGraph flow, DB schema, integration diagram |
| `service-request-chatbot/docs/agent-architecture.md` | Sprint 1 graph design, LLM vs code responsibility matrix, evolution roadmap (Sprint 2–4) |
| `service-request-chatbot/docs/agent-design.md` | Node inventory, routing mermaid, stage-to-stage data contracts, confirmation gates |
| `service-request-chatbot/docs/handover-workflow.md` | CREATE_SR / FM_REVIEW / RDD_REVIEW stages, field list, validation, payload shapes |
| `service-request-chatbot/docs/security-guardrails.md` | Injection guard, confirmation gates, backend field protection, permissions |
| `service-request-chatbot/docs/local-development.md` | Step-by-step setup, env vars, Alembic migrations |
| `service-request-chatbot/docs/api-reference.md` | Complete REST API contract |
| `service-request-chatbot/docs/observability.md` | Trace hierarchy, admin UI, redaction |
| `service-request-chatbot/docs/extensibility-guide.md` | How to add new service request types / agents |
| `service-request-chatbot/docs/debugging-guide.md` | SQL queries, trace inspection, common debugging patterns |
| `service-request-chatbot/docs/plans/plan-01-role-auth-foundation.md` | Role propagation, permission service, auth context plan |
| `service-request-chatbot/docs/plans/plan-02-backend-lifecycle-completion.md` | FM/RDD lifecycle, two-step RDD, document bridge implementation plan |
| `service-request-chatbot/docs/plans/plan-03-frontend-stage-ui.md` | Stage-aware UI: role selector, stepper, stage actions, upload panel plan |
| `service-request-chatbot/docs/plans/plan-04-extensible-agent-system.md` | Generic workflow engine roadmap (Sprint 2+) |
| `rdd_life_cycle/handover-business-flow.md` | Business journey: PMS activation → MM create → FM inspect → RDD approval; expected handover date rule |
| `rdd_life_cycle/handover-service-request (1).md` | Full platform API spec: POST create, PUT files, PATCH FM save/approve, POST RDD submit, PATCH RDD final approve |
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
User message + user_role (browser)
        ↓
Next.js frontend (POST /api/chat/service-request)
        ↓
ChatOrchestrationService
  ├── Injection scan (injection_guard.py)
  ├── Load or create ChatSession from DB
  ├── Restore graph state (ConversationStateService)
  ├── Build AuthContext from user_role
  ├── Invoke LangGraph (service_request_graph.py)
  └── Persist state + trace
        ↓
LangGraph Nodes (26 nodes, stateless per turn)
  ├── load_session → sr_status_sync* → supervisor*
  │     (* proactive routing: if sr_id exists and role matches stage,
  │        sr_status_sync routes directly to the correct stage entry node,
  │        bypassing the supervisor)
  ├── supervisor → registry → [handover_entry | fm_review_entry | rdd_review_entry]
  ├── field_extraction → merge_state → lease_lookup* → validation
  │     (merge_state also auto-computes expected_handover_date = unit_readiness_date + 7 days
  │      during FM_REVIEW — this field is never asked of the user)
  ├── missing_field (loop) or [confirmation | fm_confirmation | rdd_confirmation]
  ├── document_upload (bridges uploaded docs from state into backend_refs)
  ├── [payload_builder | fm_payload_builder | rdd_payload_builder]
  ├── [api_submission | fm_api_submission | rdd_api_submission]
  │     (rdd_api_submission branches on rdd_action:
  │      "submit"       → POST /service-requests (REPORT_SUBMITTED)
  │      "final_approve" → PATCH /service-requests/{id} (APPROVED) → SR_COMPLETED)
  └── response_generation → save_state
        ↓
Cenomi Platform APIs (or mocks)
  ├── POST /service-requests           (CREATE_SR)
  ├── PATCH /service-requests/{id}     (FM save progress — IN_PROCESS)
  ├── PATCH /service-requests/{id}     (FM approve — APPROVED)
  ├── POST  /service-requests          (RDD report submit — REPORT_SUBMITTED)
  ├── PATCH /service-requests/{id}     (RDD final approve — APPROVED → SR_COMPLETED)
  └── PUT   /files                     (document upload)
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

### Maximum LLM calls per turn

Up to 3 per chat turn: **supervisor** (intent classification) + **field_extraction** or **missing_field** (if applicable) + **response_generation** (always). All other logic is deterministic Python.

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

**`POST /api/chat/service-request` — request field update:**
The `message` field now accepts an empty string when `action` is provided. A `model_validator` enforces that at least one of `message` (non-empty) or `action` must be present. This enables action-only turns from the frontend (e.g. `approve_fm_review`, `approve_rdd_final`, `submit_rdd_report`) without requiring a dummy text message.

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

#### Graph nodes (26 total)

| Node | File | Purpose |
|------|------|---------|
| `load_session` | `load_session_node.py` | Load session + draft from DB |
| `sr_status_sync` | `sr_status_sync_node.py` | Sync SR status from platform (if sr_id exists); sets `rdd_status` and proactively routes to stage entry |
| `supervisor` | `supervisor_node.py` | LLM classifies user intent → routes; bypassed when proactive routing applies |
| `preview` | `preview_node.py` | Draft SR preview for user |
| `registry` | `registry_node.py` | Select correct agent from registry |
| `handover_entry` | `handover_entry_node.py` | Entry for CREATE_SR stage (role: MALL_MANAGER) |
| `fm_review_entry` | `fm_review_entry_node.py` | Entry for FM_REVIEW stage (roles: FM_MANAGER, OPERATIONS); dispatches `fm_action` |
| `rdd_review_entry` | `rdd_review_entry_node.py` | Entry for RDD_REVIEW stage (role: DD_ENGINEER); dispatches `rdd_action` (submit / final_approve) |
| `field_extraction` | `field_extraction_node.py` | LLM extracts fields from user message; skipped when action override is set |
| `merge_state` | `merge_state_node.py` | Merges extracted fields; protects backend fields; auto-computes `expected_handover_date` (+7 days) during FM_REVIEW |
| `lease_lookup` | `lease_lookup_node.py` | Fetches/resolves lease details; populates backend-derived fields |
| `validation` | `validation_node.py` | Deterministic field validation |
| `missing_field` | `missing_field_node.py` | Generates follow-up question for first missing required field |
| `confirmation` | `confirmation_node.py` | Confirmation gate for CREATE_SR before platform call |
| `fm_confirmation` | `confirmation_node.py` | Confirmation gate for FM_REVIEW before PATCH call |
| `rdd_confirmation` | `confirmation_node.py` | Confirmation gate for RDD_REVIEW before POST/PATCH call |
| `document_upload` | `document_upload_node.py` | **State bridge** — partitions docs from `state.documents` into `backend_refs` slots (FM docs / RDD report); no API call |
| `payload_builder` | `payload_builder_node.py` | Builds CREATE SR payload |
| `fm_payload_builder` | `fm_payload_builder_node.py` | Builds FM save-progress or FM approve payload |
| `rdd_payload_builder` | `rdd_payload_builder_node.py` | Builds RDD report submit or RDD final-approve payload |
| `api_submission` | `api_submission_node.py` | Calls platform `POST /service-requests` (CREATE_SR) |
| `fm_api_submission` | `fm_api_submission_node.py` | Calls platform `PATCH /service-requests/{id}` (FM save `IN_PROCESS` or approve `APPROVED`) |
| `rdd_api_submission` | `rdd_api_submission_node.py` | Branches on `rdd_action`: `submit` → `POST` (`REPORT_SUBMITTED`); `final_approve` → `PATCH` (`APPROVED`) → `SR_COMPLETED` |
| `response_generation` | `response_generation_node.py` | LLM generates natural language response; persona is role+stage aware |
| `save_state` | `save_state_node.py` | Persists updated draft to DB |

#### Graph state type

`ServiceRequestGraphState` (alias `ServiceRequestState`) in `app/agents/graph/state.py` — a TypedDict containing:

- `session_id`, `user_id`, `user_message`, `action_override`
- `user_role` — role string injected per HTTP turn (e.g. `"FM_MANAGER"`)
- `auth` — `AuthContext` object built from `user_role`; not checkpointed
- `intent`, `active_agent`, `workflow_stage`
- `collected_data` — all fields gathered so far
- `missing_fields`, `validation_errors`
- `response_text`, `ui_components`
- `backend_refs` — grows across the lifecycle:
  - CREATE_SR: `sr_id`, `create_payload`, `tenant_profile_id`, `property_id`, `user_role`
  - FM_REVIEW: + `uploaded_documents[]`, `fm_payload`, `fm_status`, `sr_operations`
  - RDD_REVIEW: + `rdd_document_id`, `rdd_action`, `rdd_payload`, `rdd_status`, `rdd_submitted_sr_id`
- `documents` — uploaded document metadata (bridged into `backend_refs` by `document_upload_node`)
- `platform_sr_status`, `sr_operations` — synced from platform each turn
- `rdd_status` — `REPORT_SUBMITTED` | `APPROVED` (drives frontend Submit vs Final Approve button)
- `corrected_fields` — UI field corrections; max-confidence, bypass LLM threshold
- `conversation_history` — recent turns for LLM context
- Runtime services: `trace_manager`, `conversation_state_service`

#### Supervisor intents

`SupervisorDecision` in `supervisor_schema.py`:
- `CREATE_HANDOVER_SERVICE_REQUEST` — MALL_MANAGER creating new SR
- `UPDATE_HANDOVER_SERVICE_REQUEST` — field updates mid-flow
- `APPROVE_HANDOVER_SERVICE_REQUEST` — FM/RDD approval actions
- `CHECK_SERVICE_REQUEST_STATUS` — status enquiry
- `PREVIEW_SERVICE_REQUEST` — draft preview
- `UNKNOWN` — low-confidence; returns clarification prompt

**Note:** When `active_agent` is already set and the user has not cancelled or requested a preview, the supervisor is bypassed entirely (session continuity). When `sr_id` exists and role+stage match, `sr_status_sync` routes directly to the stage entry node without calling the supervisor.

#### Agent registry

`SERVICE_REQUEST_AGENT_REGISTRY` in `agents/registries/service_request_registry.py`

Currently one entry: `("FIT_OUT_AND_HANDOVER", "HANDOVER")` → `handover_service_request_agent`

#### `handover_schema.py` — stage configuration source of truth

`app/agents/schemas/handover_schema.py` defines required fields, required documents, and role permissions per stage. All nodes query this schema rather than hard-coding stage config:

| Stage | Required role(s) | Required fields | Required document types |
|-------|-----------------|-----------------|------------------------|
| `CREATE_SR` | `MALL_MANAGER` | lease IDs, title, description, dates, `inspection_done_by`, comments | — |
| `FM_REVIEW` | `FM_MANAGER`, `OPERATIONS` | `unit_readiness_date` only (`expected_handover_date` is auto-computed) | `SR_HANDOVER_CHECKLIST`, `SR_HANDOVER_SITE_SURVEY`, `SR_COP_CHECKLIST_OTHER` |
| `RDD_REVIEW` | `DD_ENGINEER` | `guideLineLink`, `actual_handover_date`, `fitout_start_date`, `fitout_end_date`, `trading_date` | `DR_SR_HANDOVER_REPORT` |

**Key constants in `handover_schema.py`:**
- `BACKEND_COMPUTED_FIELDS` — `expected_handover_date` (auto-computed, never extracted from user)
- `BACKEND_DERIVED_FIELDS` — all lease lookup fields (immutable once set)
- `OPTIONAL_FIELDS` — `description`, `comments`, `notes` (empty string = answered)
- `PERMISSION_MAP` — role → allowed stages
- `HandoverExtractedFields` — Pydantic model that strips forbidden/backend-only keys before merging

#### Eval-driven robustness fixes (applied post-Sprint 1)

During the eval run, several multi-turn edge cases were discovered and fixed. All changes are in the nodes listed below — no graph topology or routing logic was changed.

| Node | Fix |
|------|-----|
| `supervisor_node` | Session-continuity shortcut (`active_agent` already set → skip LLM) now bypassed when `workflow_stage ∈ {SR_CREATED, SR_COMPLETED}`. After an SR is submitted, the next user message always goes through LLM classification so a new CREATE intent is recognized rather than silently continuing the old session. |
| `handover_entry_node` | When `intent == CREATE_HANDOVER_SERVICE_REQUEST` arrives while the session is in a terminal stage, ALL draft state is reset (`collected_data = {}`, `backend_refs` cleared except `user_role`, `confirmation_status = None`, `workflow_stage = CREATE_SR`). This enables multiple SRs to be raised in the same chat session. |
| `missing_field_node` | When asking for a field, embeds `_last_asked_field = <field_name>` into `collected_data` (which is persisted to DB). `merge_state_node` reads this on the next turn as a fallback hint. `response_ui` is not persisted between turns, making this the reliable channel. |
| `merge_state_node` | Three fallbacks for LLM under-extraction + `inspection_done_by` in-loop guard (see below). |
| `lease_lookup_node` | `raw_lease_code` is now split on the first non-alphanumeric character before lookup. Multi-field extraction can produce values like `"t0105712 – description: Pre-opening check"` — the split extracts just `"t0105712"`. The mock and real API both do exact matching, so extra characters caused zero-match failures. |

**`merge_state_node` — LLM under-extraction fallbacks:**

The LLM field extraction sometimes returns confidence < 0.6 for short acknowledgment answers to optional fields. Three fallbacks catch this deterministically:

- **Fallback A** — `_last_asked_field ∈ {comments, notes}` AND `collected[field] is None` AND user message is non-empty and not a structural command → store raw user message as the field value directly.
- **Fallback B** — ALL still-missing required fields are in `{comments, notes}` AND `_last_asked_field` matches the only remaining optional field → same direct store.
- **Fallback C** — `_last_asked_field == "inspection_done_by"` AND `collected["inspection_done_by"] is None` → parse user message for "FM Manager"/"Operations" variants and map to `"FM_MANAGER"`/`"OPERATIONS"`. Example: user types "FM Manager" in response to the inspector question; LLM returns 0.5 confidence → Fallback C sets `"FM_MANAGER"` directly.

**`merge_state_node` — `inspection_done_by` in-loop guard:**

Inside the LLM extraction merge loop, `inspection_done_by` is specially handled:
- Canonical variants (`"FM Manager"`, `"fm"`, `"Operations"`, `"ops"`, etc.) are normalized to `"FM_MANAGER"` or `"OPERATIONS"`.
- Any value that doesn't match a known variant (e.g. a date string `"2026-09-15"` hallucinated by the LLM) is rejected with `continue` — the existing valid value in `collected_data` is preserved unchanged.

This prevents the validation service's `validate_inspection_done_by()` (which does an exact set check against `{"FM_MANAGER", "OPERATIONS"}`) from producing a blocking error on an otherwise-valid conversation turn.

### 6.5 Services layer

> **Critical bug fix (eval-discovered):** `app/observability/decorators.py` — `"auth"` added to `_RUNTIME_KEYS`. The `AuthContext` object is injected into graph state per HTTP turn but is not JSON-serializable. When the trace manager tried to persist the state as JSONB in `agent_runs.input`, a `TypeError: Object of type AuthContext is not JSON serializable` crashed every chat turn with HTTP 500. The fix excludes `auth` from all state snapshots alongside the other non-serializable runtime objects.

| Service | File | Purpose |
|---------|------|---------|
| `ChatOrchestrationService` | `services/chat_orchestration_service.py` | Per-turn orchestration — 12-step pipeline: session load, trace, injection scan, state build, graph invoke, persist, return |
| `ConversationStateService` | `agents/services/conversation_state_service.py` | State ↔ DB persistence |
| `LLMGateway` | `agents/llm/gateway.py` | OpenAI JSON-mode completions |
| `FieldExtractionService` | `agents/services/field_extraction_service.py` | LLM field extraction |
| `ValidationService` | `agents/services/validation_service.py` | Deterministic field validation |
| `PayloadBuilderService` | `agents/services/payload_builder_service.py` | Deterministic payload construction for all 5 platform API calls |
| `LeaseLookupService` | `agents/services/lease_lookup_service.py` | HTTP / mock lease lookup; populates all backend-derived fields |
| `ServiceRequestAPIService` | `agents/services/service_request_api_service.py` | Platform SR API calls |
| `ServiceRequestPlatformClient` | `agents/services/platform_api_client.py` | Unified platform HTTP client (login, create, get, patch, submit, upload) |
| `PermissionService` | `agents/services/permission_service.py` | Role-based access checks — **fail-closed**: unknown actions raise `PermissionDeniedError` |

### 6.6 Platform API client

`app/agents/services/platform_api_client.py` → `ServiceRequestPlatformClient`

Handles authentication (login + bearer token) and all platform HTTP calls. When `SERVICE_REQUEST_API_BASE_URL` is empty, it falls back to mock responses.

---

## 7. Frontend — Detailed Walkthrough

### 7.1 Pages

| Route | Component | Description |
|-------|-----------|-------------|
| `/` | Redirect | Redirects to `/service-request-chat` |
| `/service-request-chat` | `page.tsx` → `RoleSelector` / `ServiceRequestChat` | Gated: shows role selector until role chosen; role persisted in `localStorage` (`sr_chat_user_role`) |
| `/admin/agent-observability` | Trace list | Admin trace/metrics view |
| `/admin/agent-observability/traces/[traceId]` | Trace detail | Per-trace run tree + replay |

### 7.2 Chat components

`components/chatbot/`:

| Component | Purpose |
|-----------|---------|
| `ServiceRequestChat.tsx` | Main orchestrator — 2-column layout; manages messages, session, `workflowStage`, `rddStatus`, `collectedData`, `srId`, `uploadedDocuments` |
| `RoleSelector.tsx` | **POC auth gate** — 4-role card grid (MALL_MANAGER, FM_MANAGER, OPERATIONS, DD_ENGINEER); persists to `localStorage` |
| `LifecycleStepper.tsx` | Horizontal 4-stage progress indicator (CREATE_SR → FM_REVIEW → RDD_REVIEW → SR_COMPLETED); shown when `srId` exists |
| `StageActions.tsx` | Role + stage + `rddStatus` driven action buttons below the chat input; wired to backend `action_override` |
| `DocumentUploadPanel.tsx` | Role-scoped file upload during FM/RDD review; FM roles see 3 doc types; DD_ENGINEER sees RDD report type |
| `StageContextPanel.tsx` | Collapsible prior-stage context panel for FM/RDD reviewers; shows collected fields from CREATE_SR (and FM dates at RDD stage) |
| `MessageBubble.tsx` | Renders text chat messages |
| `ChatInput.tsx` | User text input |
| `LeaseSelectionCard.tsx` | Multi-lease disambiguation UI |
| `ServiceRequestSummaryCard.tsx` | Confirmation card before SR creation |
| `FieldCorrectionPanel.tsx` | Inline field editing |
| `WorkflowProgressCard.tsx` | Step-by-step workflow progress indicator |
| `SRPreviewCard.tsx` | Draft SR preview (shown on every turn via `draft_preview`) |
| `DocumentRequirementCard.tsx` | FM/RDD document upload requirements |
| `FileUploadButton.tsx` | File picker |
| `AttachmentPreview.tsx` | Preview of uploaded files |

### 7.3 Stage-aware UI behavior

#### Role selector and auth gate

`app/service-request-chat/page.tsx` reads `localStorage` key `sr_chat_user_role` on mount. If not set, it renders `RoleSelector`. On role selection the key is written and `ServiceRequestChat` mounts. Clearing the role (`onClearRole`) removes the key and unmounts the chat (session state resets on remount).

#### 2-column layout

`ServiceRequestChat` uses a 2/3 + 1/3 grid:
- **Chat column (2/3):** role badge header, `StageContextPanel` (FM/RDD only), message thread, inline confirmation/preview/validation cards, `StageActions`, `ChatInput`
- **Sidebar (1/3):** `LifecycleStepper`, `WorkflowProgressCard`, `DocumentUploadPanel`, persistent `SRPreviewCard`, debug session ID

#### Stage action buttons

`StageActions.tsx` is a pure derived component — `getButtons()` evaluates role + stage + `rddStatus` and returns 0–2 buttons:

| `userRole` | `workflowStage` | `rddStatus` | Buttons shown | `action` sent |
|------------|-----------------|-------------|---------------|--------------|
| `FM_MANAGER` / `OPERATIONS` | `FM_REVIEW` | any | Save Progress, Approve Review | `save_fm_progress`, `approve_fm_review` |
| `DD_ENGINEER` | `RDD_REVIEW` | not `REPORT_SUBMITTED` | Submit Report | `submit_rdd_report` |
| `DD_ENGINEER` | `RDD_REVIEW` | `REPORT_SUBMITTED` | Final Approve | `approve_rdd_final` |
| `MALL_MANAGER` | `CREATE_SR` | any | (none — uses confirm/cancel cards) | — |
| any | `SR_COMPLETED` | any | (none) | — |

Button clicks send the `action` with **no user chat bubble** (`suppressUserBubble: true`).

#### Document upload panel

`DocumentUploadPanel.tsx` is visible when: `workflowStage ∈ {FM_REVIEW, RDD_REVIEW}` AND `srId !== null` AND the current role has doc types:

| Role | Allowed document types |
|------|----------------------|
| `FM_MANAGER`, `OPERATIONS` | `SR_HANDOVER_CHECKLIST`, `SR_HANDOVER_SITE_SURVEY`, `SR_COP_CHECKLIST_OTHER` |
| `DD_ENGINEER` | `DR_SR_HANDOVER_REPORT` |
| `MALL_MANAGER` | (panel hidden) |

Uploads go directly to `POST /api/upload` (separate from chat). On success the uploaded doc appears in the panel list with a checkmark. The backend bridges uploaded docs into the graph state on the next chat turn via `document_upload_node`.

### 7.4 API clients

`lib/api/`:

| Client | File | Endpoint |
|--------|------|----------|
| Chat | `chat-client.ts` → `postServiceRequestChat()` | `POST {API_BASE_URL}/api/chat/service-request` |
| Observability | `observability-client.ts` | `/api/observability/...`, `/api/v1/observability/metrics/summary` |
| Upload | `upload-client.ts` → `uploadDocument()` | `POST {API_BASE_URL}/api/upload` |

#### Chat request fields (updated)

```typescript
{
  session_id?: string,
  user_id: "demo_user",       // POC — hardcoded until real auth
  message: string,
  attachments?: ...,
  action?: string,            // e.g. "save_fm_progress", "approve_rdd_final"
  selected_lease_id?: string,
  corrected_fields?: object,
  user_role?: string          // e.g. "FM_MANAGER" — sent on every turn
}
```

#### Chat response state fields (updated)

| Backend field | Frontend field | Used by |
|---|---|---|
| `data.state.workflow_stage` | `workflowStage` | `StageActions`, `StageContextPanel`, `DocumentUploadPanel`, `LifecycleStepper` |
| `data.state.rdd_status` | `rddStatus` | `StageActions` (Submit vs Final Approve) |
| `data.state.collected_data` | `collectedData` | `StageContextPanel` |
| `data.draft_preview?.srId` | `srId` | `LifecycleStepper` visibility, `DocumentUploadPanel` |
| `data.draft_preview` | `draftPreview` | `SRPreviewCard` |

### 7.5 TypeScript types (`lib/types/chat.ts`)

Key additions in Sprint 1:
- `UserRole` — `"MALL_MANAGER" | "FM_MANAGER" | "OPERATIONS" | "DD_ENGINEER"`
- `ChatServiceResponse` — extends with `workflowStage`, `rddStatus`, `collectedData`, `srId`
- `UploadedDoc` — `{ documentId, documentType, fileName, signedUrl, uploadedAt }`
- `ResponseUI` — discriminated union covering `message`, `lease_selection`, `confirmation_card`, `validation_error`, `workflow_progress`, `document_requirement`, `sr_preview_card`

### 7.6 Known frontend limitations

- `chat-client.ts` **hardcodes** `user_id: "demo_user"` — needs real auth
- `uploadedDocuments` is session-local only — not rehydrated from backend on page reload
- No `SR_COMPLETED` completion banner in the stepper or action area
- Role switch clears role from `localStorage` but does not explicitly clear the backend session (relies on component unmount/remount resetting state)

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
| `CREATE_SR` | Collecting fields for initial SR creation (role: MALL_MANAGER) |
| `SR_CREATED` | SR created, awaiting platform status update (transient) |
| `FM_REVIEW` | FM Manager uploading documents, setting readiness date, saving/approving |
| `RDD_REVIEW` | DD Engineer uploading report, entering contractual dates, submitting report, final approve |
| `SR_COMPLETED` | Full workflow complete |

#### RDD substates (`backend_refs.rdd_status`)

The `RDD_REVIEW` stage has two distinct phases tracked by `rdd_status`:

| `workflow_stage` | `rdd_status` | Meaning | Frontend button |
|-----------------|-------------|---------|----------------|
| `RDD_REVIEW` | (unset) | DD Engineer collecting dates and guidelines | Submit Report |
| `RDD_REVIEW` | `REPORT_SUBMITTED` | Phase 3a complete; awaiting final approval | Final Approve |
| `RDD_REVIEW` | `APPROVED` | Final approval submitted; transitioning | (none) |
| `SR_COMPLETED` | `APPROVED` | Full lifecycle complete | (none) |

**Phase 3a — Submit report:** `submit_rdd_report` action → `POST /service-requests` with `status: REPORT_SUBMITTED` — the SR stays in `RDD_REVIEW`, `rdd_status` becomes `REPORT_SUBMITTED`.

**Phase 3b — Final approve:** `approve_rdd_final` action → `PATCH /service-requests/{id}` with `status: APPROVED` → `workflow_stage` advances to `SR_COMPLETED`.

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

`app/agents/services/permission_service.py` → `PermissionService` — checks user role against required permissions for each action. Role→permission sets are:

| Role | Key permissions |
|------|----------------|
| `MALL_MANAGER` | `CAN_RAISE_HANDOVER_SR`, `VIEW_FIT_OUT_HANDOVER` |
| `FM_MANAGER` / `OPERATIONS` | `CAN_FM_REVIEW_HANDOVER_SR`, `CAN_APPROVE_FM_HANDOVER_SR`, view |
| `DD_ENGINEER` | `CAN_RDD_REVIEW_HANDOVER_SR`, view |

**Fail-closed:** Unknown or unrecognised action names raise `PermissionDeniedError(required_role="UNKNOWN_ACTION")`. This was a known gap in prior versions — it is now resolved.

### Auth status

Auth is POC-level: `user_id` is passed in the request body from the frontend, and `user_role` is also passed per request and stored in `backend_refs`. `HTTPBearer` is optional and defaults to anonymous. A proper JWT/session integration is needed before production use.

---

## 11. Testing Strategy

### Test layers

```
backend/tests/
├── unit/           # ~37 files — isolated, mocked DB/LLM/APIs
├── integration/    # 8 files — compiled graph with mocked LLM and APIs
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

#### Sprint 1 — new unit tests

| Test file | What it validates |
|-----------|------------------|
| `unit/test_document_upload_node.py` | FM/RDD doc partitioning into `backend_refs`, dedup, merge with existing IDs, edge cases |
| `unit/test_expected_handover_date.py` | `_add_days` helper, `expected_handover_date` not in required fields, `merge_state` auto-calc (+7 days, FM_REVIEW stage only) |
| `unit/test_rdd_final_approve.py` | Full Phase 3b path: `rdd_review_entry` action dispatch, `rdd_payload_builder` branching (approve vs submit), `rdd_api_submission` PATCH vs POST, `APPROVE_RDD_FINAL` permission, `sr_status_sync` `rdd_status` field |
| `unit/test_role_permission_map.py` | 4-role permission sets, cross-role denials, `_build_auth_context`, fail-closed on unknown action |

#### Sprint 1 — new integration tests

| Test file | What it validates |
|-----------|------------------|
| `integration/test_fm_review_e2e.py` | FM pipeline end-to-end: doc bridge → merge auto-compute → payload build (IN_PROCESS / APPROVED) → PATCH call; wrong role blocked at entry |
| `integration/test_rdd_review_e2e.py` | Phase 3a (submit: DD/MM/YYYY date format, stays in RDD_REVIEW) + Phase 3b (final approve → SR_COMPLETED) + chained 3a→3b |
| `integration/test_handover_lifecycle.py` | Full CREATE_SR → status sync (FM/RDD stage detection) → FM save/approve → RDD submit; unauthorized roles blocked at entry nodes |

#### Eval — updated during Sprint 1 eval run

| File | What changed |
|------|-------------|
| `eval/scenarios.py` | Expanded from 9 to 36 scenarios; S36 disabled (requires real platform); S35 hard assertion softened; S27 dates updated to future; S28 Turn 2 message updated to avoid accidental confirmation trigger |

### Running eval against live backend

```bash
# Start backend first, then:
cd service-request-chatbot/backend

# Run all enabled scenarios
python -m tests.eval.run_eval

# With verbose turn-by-turn output
python -m tests.eval.run_eval --verbose

# Filter by scenario ID or tag
python -m tests.eval.run_eval --scenarios 1,2,6
python -m tests.eval.run_eval --tags happy-path,core
```

The eval suite (`tests/eval/`) covers **36 scenarios** across the full Handover SR lifecycle:

```
eval/
├── run_eval.py     # Runner with --scenarios, --tags, --verbose, --base-url flags
└── scenarios.py    # 36 scenarios (35 enabled); S36 disabled — requires real platform API
```

**Scenario categories:**

| Category | Scenarios |
|----------|----------|
| Happy path / basic flow | S1–S4 |
| Correction, cancel, restart | S5, S7, S14 |
| Error handling (invalid lease, date errors, garbage inputs) | S6, S10, S11 |
| Ambiguous / off-topic / injection | S8, S15, S33 |
| Natural language dates | S9 |
| API-driven (`corrected_fields`, `selected_lease_id`) | S16–S19, S22 |
| Title auto-generation, boundary inputs | S20, S21 |
| Multi-field extraction in one message | S23–S31 |
| Multi-SR in same session | S32 |
| FM/RDD lifecycle (role-aware) | S34, S35, S36 |

**Current pass rate: 34/35 (97%)** in mock mode (as of Sprint 1 eval). Notes:
- **S36** (`DD Engineer Final Approve`) — disabled (`enabled=False`). Requires a pre-seeded session with `sr_id` in `RDD_REVIEW` stage; cannot work standalone in mock mode.
- **S35** (`DD Engineer Submit Report`) — lifecycle hard assertion removed; validates bot language and routing only (real `rdd_status=REPORT_SUBMITTED` requires a real platform SR).
- **S14** (`Restart After Confirmation Card`) — intermittently fails due to LLM non-determinism on multi-turn state after cancel/restart; passes in the majority of runs.

#### Eval scenario fixes applied during Sprint 1

| Fix | Reason |
|-----|--------|
| S27 dates updated from June 10–12 to August 10–12 2026 | June dates became past dates relative to eval run date (June 17, 2026); validation correctly rejected them |
| S28 Turn 2 message changed from "Tenant access **confirmed** for August 1" to "Tenant gets access from August 1" | The word "confirmed" accidentally triggered the confirmation gate when the LLM also extracted `comments=""` in Turn 1 |

---

## 12. Current Implementation State

### What is fully implemented and working

| Feature | Status |
|---------|--------|
| FastAPI backend skeleton | ✅ Complete |
| Next.js frontend with chat UI | ✅ Complete |
| LangGraph graph with 26 nodes | ✅ Complete |
| Supervisor intent classification (LLM) | ✅ Complete |
| Field extraction (LLM, per-stage schemas) | ✅ Complete |
| Backend field protection in merge_state | ✅ Complete |
| `expected_handover_date` auto-computed (+7 days) — never asked of user | ✅ Complete |
| Lease lookup (HTTP + mock) | ✅ Complete |
| Deterministic validation for CREATE_SR | ✅ Complete |
| Confirmation gate (keyword + action_override) for all 3 stages | ✅ Complete |
| CREATE_SR payload builder | ✅ Complete (verify exact Postman shape — see Gap 1) |
| FM payload builders (save progress + approve) | ✅ Complete |
| RDD payload builders (submit report + final approve) | ✅ Complete |
| Platform SR creation API call | ✅ Complete |
| FM review API calls (PATCH IN_PROCESS + PATCH APPROVED) | ✅ Complete |
| RDD review API calls (POST REPORT_SUBMITTED + PATCH APPROVED) | ✅ Complete |
| Two-step RDD flow (Phase 3a submit + Phase 3b final approve) | ✅ Complete |
| SR status sync with proactive stage routing | ✅ Complete |
| `rdd_status` tracking and frontend button switching | ✅ Complete |
| Document upload node (state bridge for FM/RDD docs) | ✅ Complete |
| Role-based permission service (fail-closed) | ✅ Complete |
| Role propagation: `user_role` HTTP → `AuthContext` → entry node guards | ✅ Complete |
| Structured UI actions (save_fm_progress, approve_fm_review, submit_rdd_report, approve_rdd_final) | ✅ Complete |
| Stage-aware frontend: RoleSelector, LifecycleStepper, StageActions, DocumentUploadPanel, StageContextPanel | ✅ Complete |
| Conversation state persistence (PostgreSQL) | ✅ Complete |
| Per-turn tracing and observability | ✅ Complete |
| Admin observability UI | ✅ Complete |
| Prompt injection guard | ✅ Complete |
| Alembic migrations | ✅ Complete |
| Unit test suite (~37 files) | ✅ Complete |
| Integration test suite (8 files) | ✅ Complete |
| E2E test suite (10 scenarios) | ✅ Complete |
| Docker Compose infrastructure | ✅ Complete |
| Mock mode for all external APIs | ✅ Complete |
| `AuthContext` serialization crash in observability decorators | ✅ Fixed (eval-discovered) |
| Action-only turns — `message=""` + `action` field supported | ✅ Fixed (eval-discovered) |
| Multi-turn optional field fallbacks (comments / notes / inspection_done_by) | ✅ Complete |
| `inspection_done_by` in-loop normalization and garbage-rejection guard | ✅ Complete |
| Multiple SRs in same session (new SR after submission in same chat) | ✅ Complete |
| Lease code extraction from multi-field messages (first-token normalization) | ✅ Complete |
| Eval suite: 34/35 scenarios passing in mock mode (97%) | ✅ Verified |

### What is partially implemented

| Feature | Status | Gap |
|---------|--------|-----|
| File upload route | ⚠️ Partial stub | Backend `POST /api/upload` validates MIME type and stores metadata but does **not** call `PUT /files` on the platform yet |
| CREATE_SR payload | ⚠️ Working | Exact Postman field names/shape needs verification (see Gap 1) |
| Platform status sync field mapping | ⚠️ Complete in logic | Full `service_request_operations` → `workflow_stage` mapping should be verified against live platform |
| Frontend auth | ⚠️ Demo only | `user_id` hardcoded as `"demo_user"`; needs real JWT/session |

### What is not implemented

| Feature | Status |
|---------|--------|
| Real file upload through platform `PUT /files` | ❌ Not done |
| Token re-authentication on expiry | ❌ Not done |
| Webhook/polling for platform status changes | ❌ Not done |
| `SR_COMPLETED` completion banner in frontend | ❌ Not done |
| Uploaded documents rehydrated from backend on page reload | ❌ Not done |
| Application Docker images | ❌ Not done |
| CI/CD pipeline | ❌ Not done |
| Redis usage beyond health check | ❌ Not done |

---

## 13. Known Gaps & Issues

These are documented in full in `gaps_and_pc/chatbot_postman_gap_implementation_plan.md`.

### ~~Critical: AuthContext serialization crash~~ ✅ Resolved (eval-discovered)

`AuthContext` was not in `_RUNTIME_KEYS` in `app/observability/decorators.py`. The trace manager tried to store the full graph state (including `auth`) as JSONB in `agent_runs.input`, crashing every chat turn with HTTP 500: `TypeError: Object of type AuthContext is not JSON serializable`. Fixed by adding `"auth"` to `_RUNTIME_KEYS` alongside `conversation_state_service` and `trace_manager`.

### ~~Action-only turns required non-empty message~~ ✅ Resolved (eval-discovered)

The `message` field in `ServiceRequestChatRequest` had `min_length=1`, causing HTTP 422 for action-only turns (e.g. `approve_rdd_final` with no text). Fixed by allowing empty `message` when `action` is set, enforced via `model_validator`.

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

`POST /api/upload` validates MIME type and stores document metadata in the draft, but does not call the platform `PUT /files` endpoint. The full upload flow must be:

```
Frontend → POST /api/upload
Backend → validate MIME + document type
Backend → call platform PUT /files?query=SERVICE_REQUEST&...
Platform → returns document_id
Backend → store document_id in draft; document_upload_node bridges into backend_refs on next turn
```

### Gap 4 — FM_REVIEW: ✅ Logic complete — needs real file upload (Gap 3)

FM_REVIEW is fully wired (collect `unit_readiness_date`, auto-compute `expected_handover_date`, PATCH IN_PROCESS + PATCH APPROVED). The only remaining dependency is Gap 3 — until `PUT /files` is wired, FM document IDs in `backend_refs.uploaded_documents` will be stubs from the mock upload path.

### Gap 5 — RDD_REVIEW: ✅ Logic complete — needs real file upload (Gap 3)

RDD_REVIEW is fully wired (two-step: Phase 3a POST REPORT_SUBMITTED + Phase 3b PATCH APPROVED). Date ordering `actual_handover_date ≤ fitout_start_date ≤ fitout_end_date ≤ trading_date` is enforced. The only remaining dependency is Gap 3 for the `DR_SR_HANDOVER_REPORT` document ID.

### Gap 6 — Platform status sync field mapping needs live verification

`sr_status_sync_node` maps `service_request_operations` role/status to chatbot `workflow_stage`. The logic is implemented and tested with mocks, but the exact field names from the live platform response should be verified when connecting to a real environment.

### ~~Gap 7 — Permissions fail-open~~ ✅ Resolved

`PermissionService` now raises `PermissionDeniedError` for unknown action names (fail-closed). No longer an open gap.

### ~~Gap 8 — Structured UI actions~~ ✅ Resolved

All stage-specific action overrides are implemented: `save_fm_progress`, `approve_fm_review`, `submit_rdd_report`, `approve_rdd_final`, `upload_document`, `cancel_update`. Frontend `StageActions` component wires them to backend `action` field.

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

### 14.3 Role → action mapping (implemented in PermissionService)

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
| `APPROVE_RDD_FINAL` | `DD_ENGINEER` |
| Any unknown action | **DENY** (fail-closed — raises `PermissionDeniedError`) |

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

4. **Wire file upload** — update `app/api/routes/upload.py` to call `ServiceRequestPlatformClient.upload_file()` and store the returned `document_id` in the session draft. The `document_upload_node` will bridge that ID into `backend_refs` on the next chat turn.

5. **Verify status sync** — `sr_status_sync_node` is implemented. Confirm `service_request_operations` field names in the live platform response match the implemented mapping. Proactive routing to stage entry nodes is already wired.

6. **FM_REVIEW is fully wired** — `fm_payload_builder_node` and `fm_api_submission_node` are complete. Test by setting `SERVICE_REQUEST_API_BASE_URL` and sending `save_fm_progress` / `approve_fm_review` actions with a valid `sr_id`.

7. **RDD_REVIEW is fully wired** — `rdd_payload_builder_node` and `rdd_api_submission_node` handle both phases. Test with `submit_rdd_report` (POST) and `approve_rdd_final` (PATCH).

8. **Permissions are fail-closed** — `PermissionService` raises `PermissionDeniedError` on unknown actions. No further changes needed.

9. **Structured UI actions are implemented** — frontend `StageActions` sends `save_fm_progress`, `approve_fm_review`, `submit_rdd_report`, `approve_rdd_final`. No further changes needed.

---

### 14.6 Two-step RDD flow

The RDD review is split into two separate platform calls to match the Cenomi Handover SR business process:

**Phase 3a — Submit report** (`action: "submit_rdd_report"`)
- `rdd_review_entry_node` sets `rdd_action = "submit"`
- `rdd_payload_builder_node` calls `build_rdd_report_payload()` — includes `guideLineLink`, the 4 contractual dates (formatted `DD/MM/YYYY`), and all document IDs
- `rdd_api_submission_node` calls `POST /service-requests` with `status: REPORT_SUBMITTED`
- SR stays in `RDD_REVIEW`; `backend_refs.rdd_status` set to `REPORT_SUBMITTED`
- Frontend switches the RDD button from "Submit Report" to "Final Approve"

**Phase 3b — Final approve** (`action: "approve_rdd_final"`)
- `rdd_review_entry_node` sets `rdd_action = "final_approve"`
- `rdd_payload_builder_node` calls `build_rdd_approve_payload()` — minimal payload with existing `sr_id`
- `rdd_api_submission_node` calls `PATCH /service-requests/{sr_id}` with `status: APPROVED`
- `workflow_stage` advances to `SR_COMPLETED`

**Date ordering constraint (enforced in validation):**
```
actual_handover_date ≤ fitout_start_date ≤ fitout_end_date ≤ trading_date
```

---

### 14.7 FM auto-computed field: `expected_handover_date`

`expected_handover_date` is **never collected from the user or extracted by the LLM**. It is listed in `BACKEND_COMPUTED_FIELDS` in `handover_schema.py` and auto-computed in `merge_state_node`:

```
expected_handover_date = unit_readiness_date + 7 days
```

This computation runs only when `workflow_stage == "FM_REVIEW"` and `unit_readiness_date` is present. The FM Manager only needs to provide `unit_readiness_date` — the system calculates the rest.

The field is included in both the FM save-progress and FM approve payloads, and is surfaced in `StageContextPanel` for the DD Engineer during RDD review.

---

## 15. Recommended Implementation Order

Sprint 1 items are marked with their completion status. Remaining open items are the priority.

| # | Task | Status |
|---|------|--------|
| 1 | Align CREATE_SR payload exactly with Postman | ⚠️ Verify against live platform |
| 2 | Verify lease lookup resolves all backend-derived fields | ⚠️ Verify against live platform |
| 3 | Fix any frontend/backend route mismatches | ✅ Done |
| 4 | Implement real file upload: frontend → backend → platform `PUT /files` | ❌ Open (Gap 3) |
| 5 | Store uploaded document metadata in draft state | ✅ Done (stub path works; needs real `document_id` from platform) |
| 6 | Add status sync: `GET /service-requests/{sr_id}` before every turn | ✅ Done |
| 7 | Implement FM_REVIEW routing, entry node, payload builders, PATCH endpoints | ✅ Done |
| 8 | Implement RDD_REVIEW routing, entry node, two-step payload builders, POST + PATCH | ✅ Done |
| 9 | Harden permission service: unknown actions fail-closed | ✅ Done |
| 10 | Add structured UI actions for all platform-changing actions | ✅ Done |
| 11 | Add role selector and stage-aware frontend (stepper, context panel, upload panel) | ✅ Done |
| 12 | Fix `AuthContext` serialization crash in observability decorators | ✅ Done (eval-discovered) |
| 13 | Enable action-only turns (empty `message` when `action` is set) | ✅ Done (eval-discovered) |
| 14 | Multi-turn optional field fallbacks + `inspection_done_by` normalization | ✅ Done (eval-discovered) |
| 15 | Multiple SRs in same session + new-SR-after-submission routing | ✅ Done (eval-discovered) |
| 16 | Lease code first-token normalization for multi-field extraction | ✅ Done (eval-discovered) |
| 17 | Add platform API error recovery and retry handling | ❌ Open |
| 18 | Token re-authentication on expiry | ❌ Open |
| 19 | Add `SR_COMPLETED` completion banner in frontend | ❌ Open |
| 20 | Rehydrate uploaded documents from backend on page reload | ❌ Open |
| 21 | Add E2E tests mirroring the full Postman collection sequence | ❌ Open |
| 22 | Refactor into generic registries: workflow definition, payload builder, extraction (Plan 04) | ❌ Future |
| 23 | Add application Dockerfiles | ❌ Open |
| 24 | Add CI/CD pipeline | ❌ Open |
| 25 | Replace POC role selector with real JWT/session auth | ❌ Open |

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
