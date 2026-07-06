# API Reference

## Base URLs

| Environment | Backend Base URL |
|-------------|-----------------|
| Local | `http://localhost:8000` |
| Production | Configured via `SERVICE_REQUEST_CHATBOT_API_URL` |

All routes are prefixed as documented below. FastAPI auto-generates OpenAPI docs at `/docs` (Swagger UI) and `/redoc` when `ENVIRONMENT != production`.

## API Version Matrix

All routes are available at both `/api/v1` (backward compat) and `/api/v2` (current). New integrations should target v2. The MSP Platform help endpoints are contractually pinned to v1 and are not duplicated at v2.

| Route group | v1 | v2 |
|---|---|---|
| Health / ready | `/api/v1/health` | `/api/v2/health` |
| Auth | `/api/auth/login` | `/api/v2/auth/login` |
| RDD chat | `/api/chat/service-request` | `/api/v2/chat/service-request` |
| Upload | `/api/v1/upload` | `/api/v2/upload` |
| Observability | `/api/observability/...` | `/api/v2/observability/...` |
| MSP help chat (sync) | `/api/v1/chat` | *(v1 only)* |
| MSP help chat (stream) | `/api/v1/chat/stream` | *(v1 only)* |

---

## MSP Platform Help Chat API

These endpoints match the `cenomi-ai-backend` API contract so the MSP Platform frontend can route help/FAQ traffic to this service.

### POST /api/v1/chat

Synchronous help agent response.

**Auth headers (both required in production):**
```http
x-internal-api-token: <MSP_SERVICE_TOKEN>
Authorization: Bearer <ai_token>
```

**Request**

```json
{
  "message": "How do I submit a service request?",
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "language": "en",
  "context": {
    "current_url_pattern": "/servicerequest",
    "help_category": "Service Requests",
    "help_subcategory": "How to Submit"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | **Yes** | User's question (1–4000 chars) |
| `conversation_id` | UUID string | No | Omit on first turn; include for multi-turn context |
| `language` | `"en"` \| `"ar"` | No | Preferred language; auto-detected when omitted |
| `context` | object | No | Page-aware RAG grounding hint |
| `context.current_url_pattern` | string | No | Current page URL, e.g. `"/servicerequest"` |
| `context.help_category` | string | No | Top-level help category |
| `context.help_subcategory` | string | No | Help subcategory |

**Response 200 OK**

```json
{
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "message_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "message": "To submit a service request, navigate to the SR module...",
  "sources": [
    { "source_type": "help_content", "title": "Service Request Guide" },
    { "source_type": "user_guide",   "title": "Platform User Manual v2" }
  ],
  "language": "en"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `conversation_id` | UUID string | Session ID — reuse on the next turn |
| `message_id` | UUID string | Per-message ID for observability |
| `message` | string | Assistant reply text |
| `sources` | array | RAG citations (`source_type`, `title`) — empty when no KB results |
| `language` | string | Detected or requested language code |

**Response 401** — missing or incorrect `x-internal-api-token` (when `MSP_SERVICE_TOKEN` is configured).

**Response 422** — missing or empty `message` field.

---

### POST /api/v1/chat/stream

SSE streaming help agent response. The MSP Platform frontend uses this as the primary endpoint.

**Request** — same shape as `POST /api/v1/chat`.

**Response** — `Content-Type: text/event-stream`

SSE event sequence per turn:

```
event: token
data: {"text": "To submit a service request, navigate to the SR module..."}

event: source
data: {"source_type": "help_content", "title": "Service Request Guide"}

event: done
data: {"conversation_id": "550e8400-...", "message_id": "a1b2c3d4-...", "language": "en"}
```

On graph failure (stream already started — HTTP 200 returned, error inside SSE body):

```
event: error
data: {"message": "An error occurred while processing your request."}
```

| Event | `data` fields | When |
|-------|---------------|------|
| `token` | `{text: string}` | Once — full message (Phase 1 pseudo-streaming) |
| `source` | `{source_type: string, title: string}` | Once per RAG citation |
| `done` | `{conversation_id: string, message_id: string, language: string}` | End of stream |
| `error` | `{message: string}` | On any graph or infrastructure failure |

> **Phase 1 note:** The full message is emitted as a single `token` event after the graph completes. True incremental token streaming (many `token` events) requires LLM gateway changes and is planned for Phase 2.

---

---

## Chat API

### POST /api/chat/service-request

The primary endpoint for all user turns. Accepts a user message (and optional attachments / UI actions) and returns the agent's response.

> **Note:** The backend mounts this at `/api/chat/service-request` — no `/v1` prefix. The frontend `NEXT_PUBLIC_API_V1_PREFIX` must be set to `""` or this path adjusted to match.

**Request**

```http
POST /api/chat/service-request
Content-Type: application/json
Authorization: Bearer <token>   (optional)
```

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user-123",
  "message": "I want to submit a handover service request for my unit",
  "attachments": [],
  "action": null,
  "selected_lease_id": null,
  "corrected_fields": null
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | UUID string | No | Omit on first turn — backend creates a new session |
| `user_id` | string | Yes | Caller's user identifier (POC fallback; JWT `sub` takes precedence when a valid Bearer token is present) |
| `message` | string | No | User's natural language message. Required unless `sr_id` is provided. |
| `attachments` | array | No | List of file attachment metadata dicts |
| `action` | string \| null | No | Explicit UI action: `"confirm"` to submit, `"cancel"` to reject the confirmation card. Bypasses text-based intent parsing. |
| `selected_lease_id` | string \| null | No | Lease ID chosen from a `lease_selection` card. When set, the graph skips re-resolving the lease via text. |
| `corrected_fields` | object \| null | No | Inline field edits submitted from the confirmation card. Merged into `collected_data` before validation at maximum confidence, bypassing the LLM extraction step. |
| `sr_id` | string \| null | No | Platform SR ID — passed by the frontend when FM Manager or DD Engineer opens an existing SR from a notification. Triggers `sr_status_sync` to fetch live platform status before routing. |

**Defined in:** `app/api/routes/chat.py` → `ServiceRequestChatRequest`

**Response 200 OK**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "active_agent": "rdd_agent",
  "message": "I found 2 leases for your account. Please select the one you'd like to use:",
  "ui": {
    "type": "lease_selection",
    "leases": [
      {
        "lease_id": "uuid-lease-1",
        "lease_code": "LC-12345",
        "mall": "Riyadh Park",
        "brand": "Tenant Brand",
        "unit_codes": ["A-101"],
        "contracted_area": 250.0
      }
    ]
  },
  "state": {
    "workflow_stage": "CREATE_SR",
    "intent": "CREATE_RDD_SERVICE_REQUEST",
    "missing_fields": ["selected_lease"],
    "collected_data": {}
  },
  "trace_id": "trace-uuid-abc"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | UUID string | Session ID (use for all subsequent turns) |
| `active_agent` | string \| null | Currently active agent name |
| `message` | string | Text response to display to the user |
| `ui` | object \| null | Structured UI component data (see UI types below) |
| `state` | object | Summary of current state: `workflow_stage`, `intent`, `missing_fields`, `ready_to_submit` |
| `draft_preview` | object \| null | Current draft `collected_data` snapshot — returned alongside `state` for frontend preview rendering |
| `trace_id` | UUID string | Trace ID for this turn (use for observability lookup) |

**Defined in:** `app/api/routes/chat.py` → `ServiceRequestChatResponse`

**Response 400** — Injection detected or malformed request body.

```json
{
  "session_id": "...",
  "active_agent": null,
  "message": "I'm unable to process that request.",
  "ui": null,
  "state": {},
  "trace_id": "trace-uuid-abc"
}
```

**Response 422** — Pydantic validation error on request body.

### UI Component Types

The `ui` field in the response carries structured data for the frontend to render specialized components:

| `ui.type` | Component | When returned |
|-----------|-----------|--------------|
| `"lease_selection"` | `LeaseCard` | Multiple leases found — user must select one |
| `"confirmation_card"` | `SummaryCard` | All fields collected — user must confirm before submission |
| `"missing_field"` | `ChatInput` (default) | Prompting for a specific field |
| `null` | `MessageBubble` | Standard text response |

**`confirmation_card` shape:**

```json
{
  "type": "confirmation_card",
  "fields": {
    "title": "Handover request for Unit A-101",
    "description": "All fit-out work completed...",
    "startDate": "2026-06-01",
    "endDate": "2026-06-15",
    "mall": "Riyadh Park",
    "brand": "Tenant Brand",
    "unit_codes": ["A-101"],
    "inspection_done_by": "John Smith",
    "comments": "Per approved drawings."
  }
}
```

---

## Auth API

### POST /api/auth/login

Issues a signed JWT for a local user.

**Request**

```http
POST /api/auth/login
Content-Type: application/json
```

```json
{ "username": "aisha@cenomi.com", "password": "test1234" }
```

**Response 200 OK**

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user_id": "441bf99f-...",
  "role": "MALL_MANAGER",
  "mall_names": ["Jawharat Jeddah"],
  "expires_in": 3600
}
```

**Response 400** — incorrect credentials.

---

### GET /api/auth/me

Returns the current user from the JWT.

**Request** — requires `Authorization: Bearer <token>`

**Response 200 OK** — `UserResponse` with `user_id`, `username`, `role`, `mall_names`, `unique_property_ids`, `is_global_admin`.

---

## Upload API

### POST /api/v1/upload

Document upload endpoint. Validates the file, enforces document-type RBAC, then forwards the bytes to the Cenomi platform `PUT /files` endpoint.

**Request**

```http
POST /api/v1/upload
Content-Type: multipart/form-data
Authorization: Bearer <token>
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | File | Yes | PDF, JPEG, or PNG only |
| `session_id` | string | Yes | Active session ID |
| `document_type` | string | Yes | Must be in `ALL_DOCUMENT_TYPES` |

**Enforced constraints:**
- MIME type must be one of: `application/pdf`, `image/jpeg`, `image/png`.
- `document_type` must be a known type in `ALL_DOCUMENT_TYPES`.
- Document-type RBAC: FM documents only in FM_REVIEW stage; RDD documents only in RDD_REVIEW stage.
- When `sr_id` and backend refs are present, the request is forwarded to `ServiceRequestPlatformClient.upload_file()` → `PUT {SERVICE_REQUEST_API_BASE_URL}/files`.

**Response 200 OK**

```json
{
  "document_id": "real-uuid-from-platform",
  "document_type": "SR_HANDOVER_CHECKLIST",
  "file_path": "storage/path/to/file.pdf",
  "signed_url": "https://...",
  "status": "uploaded"
}
```

**Response 200 OK** (pre-submission — `sr_id` not yet available)

```json
{
  "document_id": null,
  "document_type": "SR_HANDOVER_CHECKLIST",
  "status": "received_pending_sr"
}
```

---

## Observability APIs

### GET /api/observability/traces

Returns a paginated list of agent traces.

**Request**

```http
GET /api/observability/traces?session_id=<uuid>&agent=<agent_name>&status=<status>&intent=<intent>&page=1&page_size=20
```

| Query Param | Type | Description |
|-------------|------|-------------|
| `session_id` | UUID | Filter by session |
| `agent` | string | Filter by `active_agent` name |
| `status` | string | `SUCCESS` \| `FAILED` |
| `intent` | string | Filter by classified intent |
| `user_id` | UUID | Filter by user |
| `from_date` / `to_date` | datetime | Date range filter |
| `has_error` | bool | Only traces with errors |
| `min_latency_ms` | int | Only traces above latency threshold |
| `page` | int | 1-based page number (default 1) |
| `page_size` | int | Page size (default 20) |

**Response 200 OK**

```json
{
  "items": [
    {
      "id": "trace-uuid-1",
      "session_id": "session-uuid-1",
      "status": "SUCCESS",
      "intent": "CREATE_RDD_SERVICE_REQUEST",
      "active_agent": "rdd_agent",
      "workflow_stage_before": "CREATE_SR",
      "workflow_stage_after": "SR_CREATED",
      "total_latency_ms": 4200,
      "total_token_count": 1840,
      "estimated_cost": 0.0012,
      "started_at": "2026-05-14T08:30:00Z",
      "completed_at": "2026-05-14T08:30:04Z"
    }
  ],
  "total": 142,
  "page": 1,
  "page_size": 20,
  "has_next": true
}
```

---

### GET /api/observability/traces/{trace_id}

Returns full trace detail. Arrays are flat (not nested); the run tree is a separate `run_tree` field.

**Response 200 OK**

```json
{
  "trace": {
    "id": "trace-uuid-1",
    "session_id": "session-uuid-1",
    "status": "SUCCESS",
    "intent": "CREATE_RDD_SERVICE_REQUEST",
    "active_agent": "rdd_agent",
    "total_latency_ms": 4200,
    "total_token_count": 1840,
    "started_at": "2026-05-14T08:30:00Z",
    "completed_at": "2026-05-14T08:30:04Z"
  },
  "runs": [
    { "id": "run-uuid-supervisor", "run_name": "supervisor", "run_type": "SUPERVISOR", "status": "SUCCESS", "latency_ms": 820 }
  ],
  "run_tree": { ... },
  "state_snapshots": [
    { "snapshot_type": "BEFORE_NODE", "node_name": "supervisor", "state": { ... } },
    { "snapshot_type": "AFTER_NODE",  "node_name": "supervisor", "state": { ... } }
  ],
  "state_diffs": [ { "node_name": "supervisor", "diff": { "added": { "intent": "..." } } } ],
  "llm_calls": [ { "model": "gpt-4o-mini", "latency_ms": 810, "total_tokens": 340, "structured_output": { ... } } ],
  "tool_calls": [ { "tool_name": "lease_tenant_api", "tool_type": "HTTP", "success": true, "latency_ms": 120 } ],
  "feedback": []
}
```

**Response 404** — trace not found.

---

### GET /api/observability/sessions/{session_id}/replay

Returns all traces for a session ordered oldest-first, each enriched with runs, snapshots, diffs, LLM/tool calls, and feedback. Useful for post-hoc session evaluation and trace replay in the admin UI.

**Response 200 OK**

```json
{
  "session_id": "session-uuid-1",
  "trace_count": 8,
  "traces": [ { "trace": { ... }, "runs": [...], "llm_calls": [...], "tool_calls": [...], ... } ]
}
```

**Response 404** — no traces found for session.

---

### GET /api/v1/observability/metrics/summary

Returns aggregate metrics across all traces.

**Response 200 OK**

```json
{
  "total_traces": 1420,
  "success_rate": 0.984,
  "failed_traces": 22,
  "avg_latency_ms": 1250,
  "total_tokens": 2840000,
  "total_cost": 1.89
}
```

---

## Health Check

### GET /api/v1/health

Simple liveness probe.

**Response 200 OK**

```json
{ "status": "ok" }
```

---

### GET /api/v1/ready

Readiness probe — checks DB and Redis connectivity.

**Response 200 OK** — `{ "status": "ready", "db": "ok", "redis": "ok" }`

**Response 503** — one or more dependencies unavailable.
