# Architecture

## High-Level Architecture

The Service Request Chatbot is a full-stack application that allows Cenomi mall tenants to submit handover service requests through a conversational interface. A LangGraph-based multi-agent backend orchestrates the conversation, collects required data, validates it, and submits it to the Cenomi Service Request API.

```mermaid
graph TB
    subgraph Browser
        FE[Next.js 15 App Router<br/>React 19 + Tailwind 3]
    end

    subgraph Backend["Backend (FastAPI + Python)"]
        API[API Layer<br/>FastAPI Routers]
        ORCH[ChatOrchestrationService]
        GUARD[Injection Guard]
        GRAPH[LangGraph Graph]
        OBS[TraceManager<br/>Observability]
    end

    subgraph Infra
        PG[(PostgreSQL 16<br/>Primary Store)]
        REDIS[(Redis 7<br/>Cache / Future)]
    end

    subgraph External
        LLM[OpenAI / LLM API]
        LEASE[Lease-Tenant API]
        SR[Service Request API]
        UPLOAD[File Upload API]
    end

    FE -->|POST /api/chat/service-request| API
    FE -->|GET /api/observability/traces| API
    API --> GUARD
    GUARD --> ORCH
    ORCH --> GRAPH
    GRAPH -->|LLM calls| LLM
    GRAPH -->|Lease lookup| LEASE
    GRAPH -->|Submit SR| SR
    ORCH --> OBS
    OBS --> PG
    ORCH --> PG
    GRAPH -.->|state reload| PG
```

**Key design decisions:**

- **No LangGraph interrupt/resume** — each HTTP turn runs the full graph from scratch; conversation state is reloaded from PostgreSQL at the start of every turn via `ConversationStateService.load`.
- **Stateless graph, stateful DB** — the LangGraph `ServiceRequestGraphState` is populated from the database at `load_session_node` and persisted at `save_state_node`.
- **Pre-graph injection guard** — prompt injection scanning happens before the user message is persisted or the graph is invoked.

---

## Frontend Architecture

```mermaid
graph TD
    Root["app/page.tsx<br/>(redirects → /service-request-chat)"]
    Chat["app/service-request-chat/page.tsx"]
    Admin["app/admin/agent-observability/page.tsx"]

    Root --> Chat
    Root --> Admin

    Chat --> SRC["ServiceRequestChat.tsx<br/>(main orchestrator)"]
    SRC --> MB["MessageBubble"]
    SRC --> CI["ChatInput"]
    SRC --> LC["LeaseCard"]
    SRC --> SUM["SummaryCard"]
    SRC --> DC["DocumentCard"]

    Admin --> TL["TraceList"]
    Admin --> TD["TraceDetail"]
    Admin --> RP["ReplayViewer"]
    Admin --> LV["LLMCallViewer"]
    Admin --> TV["ToolCallViewer"]
    Admin --> SD["StateDiffViewer"]
```

**Framework:** Next.js 15 App Router, React 19, TypeScript 5, Tailwind CSS 3.

**State management:** Local React `useState` / `useCallback` in `ServiceRequestChat`. No Redux or Zustand. State tracked per component: `messages`, `sessionId`, `latestUI`, `workflowSteps`.

**API clients:**

- `frontend/lib/api/chat-client.ts` — `postServiceRequestChat` sends `fetch` to `${NEXT_PUBLIC_API_BASE_URL}${NEXT_PUBLIC_API_V1_PREFIX}/chat/service-request` with fields: `session_id`, `message`, `attachment_ids`, `selected_lease_id`, `corrected_fields`, `action`.
- `frontend/lib/api/observability-client.ts` — `listTraces`, `getTrace` (at `/api/observability/...`), metrics at `/api/v1/observability/metrics/summary`.

**URL prefix mismatch:** The frontend default `NEXT_PUBLIC_API_V1_PREFIX=/api/v1` targets `/api/v1/chat/service-request`, but the backend mounts the chat route at `/api/chat/service-request` (no v1 prefix). Set `NEXT_PUBLIC_API_V1_PREFIX=""` or adjust to match the backend. E2E tests use `/api/chat/service-request`.

**Type definitions:** `frontend/lib/types/chat.ts`, `frontend/lib/types/observability.ts`.

---

## Backend Architecture

```mermaid
graph TD
    HTTP["HTTP Request<br/>POST /api/chat/service-request"]
    ROUTER["chat.py router<br/>ServiceRequestChatRequest"]
    GUARD["injection_guard.scan_message()"]
    ORCH["ChatOrchestrationService"]
    SESS["ChatSessionRepository"]
    TM["TraceManager.start_trace()"]
    MSG["ChatMessageRepository.create()"]
    CSS["ConversationStateService.load()"]
    GRAPH["get_compiled_graph().ainvoke()"]
    SAVE["ConversationStateService.save_checkpoint()"]
    RESP["ServiceRequestChatResponse"]

    HTTP --> ROUTER
    ROUTER --> GUARD
    GUARD -->|injection detected| RESP
    GUARD -->|clean| ORCH
    ORCH --> SESS
    ORCH --> TM
    ORCH --> MSG
    ORCH --> CSS
    ORCH --> GRAPH
    GRAPH --> SAVE
    ORCH -->|TraceManager.finish_trace| TM
    ORCH --> RESP
```

**Application factory** (`app/main.py`):

- `CORSMiddleware` from `settings.cors_origins_list`.
- Route mounts:
  - `GET {api_v1_prefix}/health`
  - `POST /api/chat/service-request` (no v1 prefix)
  - `POST /api/v1/chat/turn` (deprecated stub)
  - `POST /api/v1/upload`
  - `GET /api/observability/...`
  - `GET /api/v1/observability/metrics/...`

**`ChatOrchestrationService`** (`app/services/chat_orchestration_service.py`) is the central coordinator:

1. Load or create `ChatSession` via `ChatSessionRepository`.
2. `TraceManager.start_trace` — creates `AgentTrace` row.
3. Audit `turn.started` via `AuditLogRepository`.
4. `scan_message` — short-circuits to refusal response on high-risk injection.
5. `ChatMessageRepository.create` — persist user message.
6. Build initial `ServiceRequestGraphState` with session fields (`active_agent`, `intent`, `workflow_stage`) from `ConversationStateService.load`.
7. `get_compiled_graph().ainvoke(initial_state)`.
8. `TraceManager.finish_trace` with `final_state`.
9. Persist assistant message, `_sync_session` updates `ChatSession`, audit `turn.completed`.

**Config** (`app/core/config.py`): `Settings` reads from `.env` / `.env.local`. Key fields: `database_url`, `redis_url`, `openai_api_key`, `llm_model`, `service_request_api_base_url`, `lease_tenant_api_base_url`, `file_upload_api_base_url`, `jwt_secret_key`, `llm_confidence_threshold` (default `0.6`).

---

## LangGraph Architecture

The graph is defined in `app/agents/graph/service_request_graph.py` and compiled once as a singleton (`get_compiled_graph()`).

```mermaid
flowchart TD
    START([START]) --> load_session
    load_session -->|active_agent set| handover_entry
    load_session -->|no active_agent| supervisor

    supervisor -->|WAITING_FOR_USER| response_generation
    supervisor -->|intent classified| registry

    registry -->|WAITING_FOR_USER| response_generation
    registry -->|agent resolved| handover_entry

    handover_entry -->|workflow restart: active_agent cleared + WAITING_FOR_USER| response_generation
    handover_entry -->|action_override=cancel| merge_state
    handover_entry -->|normal turn| field_extraction

    field_extraction --> merge_state

    merge_state -->|selected_lease set or lease_id missing| lease_lookup
    merge_state -->|lease_id present| validation

    lease_lookup -->|WAITING_FOR_USER| response_generation
    lease_lookup -->|lease resolved| validation

    validation -->|blocking errors| missing_field
    validation -->|fields incomplete| missing_field
    validation -->|all valid + complete| confirmation

    confirmation -->|CONFIRMED| payload_builder
    confirmation -->|not CONFIRMED| response_generation

    payload_builder --> api_submission

    api_submission --> response_generation

    missing_field --> response_generation

    response_generation --> save_state

    save_state --> END([END])
```

**State type:** `ServiceRequestGraphState` (`TypedDict`, `total=False`) in `app/agents/graph/state.py`. Runtime-only keys `trace_manager` and `conversation_state_service` are injected by the orchestration layer and stripped before trace persistence.

**Node decorators:** `@trace_node(run_name, run_type)` wraps each node with `start_run`, before/after state snapshots, diff capture, and `finish_run`.

---

## Database Architecture

```mermaid
erDiagram
    chat_sessions {
        uuid id PK
        string user_id
        string active_agent
        string intent
        string workflow_stage
        string status
        timestamp created_at
        timestamp updated_at
    }
    chat_messages {
        uuid id PK
        uuid session_id FK
        string role
        text content
        jsonb metadata
        timestamp created_at
    }
    service_request_drafts {
        uuid id PK
        uuid session_id FK
        string service_category
        string sub_category
        string workflow_stage
        jsonb collected_data
        jsonb missing_fields
        jsonb documents
        string sr_id
        string service_request_status
        boolean ready_to_submit
    }
    service_request_chat_audit_logs {
        uuid id PK
        uuid session_id FK
        string event_type
        jsonb metadata
        timestamp created_at
    }
    agent_traces {
        uuid id PK
        uuid session_id FK
        string status
        jsonb metadata
        timestamp started_at
        timestamp finished_at
    }
    agent_runs {
        uuid id PK
        uuid trace_id FK
        uuid parent_run_id FK
        string name
        string run_type
        string status
        jsonb output
        integer latency_ms
        timestamp started_at
        timestamp finished_at
    }
    agent_state_snapshots {
        uuid id PK
        uuid run_id FK
        string snapshot_type
        jsonb state
        timestamp created_at
    }
    agent_state_diffs {
        uuid id PK
        uuid run_id FK
        jsonb diff
        timestamp created_at
    }
    agent_llm_calls {
        uuid id PK
        uuid run_id FK
        jsonb request
        jsonb response
        integer latency_ms
        timestamp created_at
    }
    agent_tool_calls {
        uuid id PK
        uuid run_id FK
        string tool_name
        jsonb input
        jsonb output
        integer latency_ms
        timestamp created_at
    }

    chat_sessions ||--o{ chat_messages : "has"
    chat_sessions ||--o| service_request_drafts : "has"
    chat_sessions ||--o{ service_request_chat_audit_logs : "has"
    chat_sessions ||--o{ agent_traces : "has"
    agent_traces ||--o{ agent_runs : "contains"
    agent_runs ||--o{ agent_state_snapshots : "has"
    agent_runs ||--o{ agent_state_diffs : "has"
    agent_runs ||--o{ agent_llm_calls : "has"
    agent_runs ||--o{ agent_tool_calls : "has"
```

**Migrations:**

- `001_initial_schema.py` — domain tables: `chat_sessions`, `chat_messages`, `service_request_drafts`, `service_request_chat_audit_logs`, and legacy observability stubs.
- `002_agent_observability.py` — agent observability tables: `agent_traces`, `agent_runs`, `agent_state_snapshots`, `agent_state_diffs`, `agent_llm_calls`, `agent_tool_calls`, `agent_feedback`.

**ORM:** Async SQLAlchemy with asyncpg driver (`DATABASE_URL` must use `postgresql+asyncpg://...`).

---

## Integration Architecture

```mermaid
graph LR
    subgraph Cenomi Platform
        LEASE["Lease-Tenant API<br/>LEASE_TENANT_API_BASE_URL"]
        SR_API["Service Request API<br/>SERVICE_REQUEST_API_BASE_URL"]
        FILE["File Upload API<br/>FILE_UPLOAD_API_BASE_URL"]
    end

    subgraph Backend Services
        LL["LeaseLookupService<br/>(lease_lookup_node)"]
        SRA["ServiceRequestAPIService<br/>(api_submission_node)"]
        FU["UploadRoute<br/>(stub)"]
    end

    LL -->|GET tenant leases by user_id| LEASE
    SRA -->|POST create service request| SR_API
    FU -->|POST upload binary| FILE
```

**Lease lookup:** Called when `selected_lease` is set or `lease_id` is missing from `collected_data`. Resolves from the Cenomi Lease-Tenant API, handles multi-lease disambiguation by surfacing a `LeaseSelectionUI` component to the user.

**Service Request submission:** `ServiceRequestAPIService.create_service_request` posts the payload built by `PayloadBuilderService.build_create_handover_payload`. On success, sets `workflow_stage = "SR_CREATED"` and `status = SUBMITTED`.

**File Upload:** Route stub at `POST /api/v1/upload`. Enforces MIME allowlist (PDF/JPEG/PNG) and `PermissionService.ensure_can_create_request`. Does not yet persist bytes.

**Authentication:** `HTTPBearer` optional header. Default `AuthContext` is `"anonymous"` with empty roles. `PermissionService` maps actions to required role strings; unknown actions currently fail-open.
