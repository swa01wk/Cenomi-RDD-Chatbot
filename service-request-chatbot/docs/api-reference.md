# API Reference

## Base URLs

| Environment | Backend Base URL |
|-------------|-----------------|
| Local | `http://localhost:8000` |
| Production | Configured via `SERVICE_REQUEST_CHATBOT_API_URL` |

All routes are prefixed as documented below. FastAPI auto-generates OpenAPI docs at `/docs` (Swagger UI) and `/redoc` when `ENVIRONMENT != production`.

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
| `user_id` | string | Yes | Tenant user identifier (UUID or arbitrary string; non-UUIDs are mapped via uuid5) |
| `message` | string | Yes | User's natural language message |
| `attachments` | array | No | List of file attachment metadata dicts |
| `action` | string \| null | No | Explicit UI action: `"confirm"` to submit, `"cancel"` to reject the confirmation card. Bypasses text-based intent parsing. |
| `selected_lease_id` | string \| null | No | Lease ID chosen from a `lease_selection` card. When set, the graph skips re-resolving the lease via text. |
| `corrected_fields` | object \| null | No | Inline field edits submitted from the confirmation card. Merged into `collected_data` before validation at maximum confidence, bypassing the LLM extraction step. |

**Defined in:** `app/api/routes/chat.py` → `ServiceRequestChatRequest`

**Response 200 OK**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "active_agent": "handover_service_request_agent",
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
    "intent": "CREATE_HANDOVER_SERVICE_REQUEST",
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
| `state` | object | Summary of current state (workflow_stage, intent, missing_fields, etc.) |
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

## Upload API (Placeholder)

### POST /api/v1/upload

Document upload endpoint. Currently validates the request but does not persist the file bytes.

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
- `document_type` must be a known document type.
- `PermissionService.ensure_can_create_request` is called — requires `MALL_MANAGER` role.

**Response 200 OK** (stub)

```json
{
  "document_id": "placeholder-uuid",
  "document_type": "FIT_OUT_COMPLETION_CERTIFICATE",
  "status": "uploaded"
}
```

**Not yet implemented:** File bytes are validated but not stored. The `FILE_UPLOAD_API_BASE_URL` integration is pending.

---

## Observability APIs

### GET /api/observability/traces

Returns a paginated list of agent traces.

**Request**

```http
GET /api/observability/traces?session_id=<uuid>&agent=<agent_name>&status=<status>&limit=20&offset=0
```

| Query Param | Type | Description |
|-------------|------|-------------|
| `session_id` | UUID | Filter by session |
| `agent` | string | Filter by `active_agent` name |
| `status` | string | `RUNNING` \| `COMPLETED` \| `FAILED` |
| `limit` | int | Page size (default 20) |
| `offset` | int | Pagination offset (default 0) |

> **Mismatch:** Frontend `observability-client.ts` may send `active_agent` — the backend parameter name is `agent`. Confirm against `app/api/routes/traces.py`.

**Response 200 OK**

```json
{
  "traces": [
    {
      "id": "trace-uuid-1",
      "session_id": "session-uuid-1",
      "status": "COMPLETED",
      "started_at": "2026-05-14T08:30:00Z",
      "finished_at": "2026-05-14T08:30:04Z",
      "metadata": {
        "user_id": "user-123",
        "intent": "CREATE_HANDOVER_SERVICE_REQUEST"
      }
    }
  ],
  "total": 142,
  "limit": 20,
  "offset": 0
}
```

---

### GET /api/observability/traces/{trace_id}

Returns full trace detail including the nested run tree with snapshots, diffs, LLM calls, and tool calls.

**Request**

```http
GET /api/observability/traces/{trace_id}
```

**Response 200 OK**

```json
{
  "id": "trace-uuid-1",
  "session_id": "session-uuid-1",
  "status": "COMPLETED",
  "started_at": "2026-05-14T08:30:00Z",
  "finished_at": "2026-05-14T08:30:04Z",
  "metadata": {},
  "runs": [
    {
      "id": "run-uuid-supervisor",
      "name": "supervisor",
      "run_type": "SUPERVISOR",
      "status": "COMPLETED",
      "latency_ms": 820,
      "output": {
        "intent": "CREATE_HANDOVER_SERVICE_REQUEST",
        "service_category": "FIT_OUT_AND_HANDOVER",
        "sub_category": "HANDOVER"
      },
      "snapshots": [
        {
          "snapshot_type": "BEFORE_NODE",
          "state": { "message": "I want to submit a handover request" }
        },
        {
          "snapshot_type": "AFTER_NODE",
          "state": {
            "message": "I want to submit a handover request",
            "intent": "CREATE_HANDOVER_SERVICE_REQUEST"
          }
        }
      ],
      "diffs": [
        {
          "diff": {
            "added": { "intent": "CREATE_HANDOVER_SERVICE_REQUEST" },
            "removed": {},
            "changed": {}
          }
        }
      ],
      "llm_calls": [
        {
          "request": { "model": "gpt-4o", "messages": [...] },
          "response": {
            "intent": "CREATE_HANDOVER_SERVICE_REQUEST",
            "confidence": 0.95
          },
          "latency_ms": 810
        }
      ],
      "tool_calls": [],
      "children": []
    }
  ]
}
```

**Response 404** — trace not found.

---

### GET /api/v1/observability/metrics/summary

Returns aggregate metrics across all traces.

**Response 200 OK**

```json
{
  "total_traces": 1420,
  "completed": 1398,
  "failed": 22,
  "avg_latency_ms": 1250,
  "intent_distribution": {
    "CREATE_HANDOVER_SERVICE_REQUEST": 1350,
    "UNKNOWN": 70
  }
}
```

---

## Health Check

### GET /api/v1/health

Simple liveness probe.

**Response 200 OK**

```json
{
  "status": "ok",
  "environment": "development"
}
```
