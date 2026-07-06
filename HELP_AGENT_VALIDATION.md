# Help Agent — Validation & MSP Integration Reference

> **Purpose:** Validate the help agent in `Cenomi-RDD-Chatbot/service-request-chatbot`
> against the API contract that the MSP Platform frontend (`cenomi-ai-backend`) expects,
> so that the RDD-Chatbot help agent can be integrated into the MSP Platform.
>
> Read **§A** (MSP contract) and **§B** (RDD-Chatbot contract) independently,
> then use **§C** (alignment gap table) to know exactly what must change.

---

## §A — MSP Platform API Contract (`cenomi-ai-backend`)

This is the contract the MSP Platform frontend is written against.
All frontend widgets, TypeScript types, and SSE parsers are built for this shape.

### A.1 Endpoints

| Route | Method | Protocol | Purpose |
|-------|--------|----------|---------|
| `/api/v1/chat` | POST | JSON | Direct help agent — sync response |
| `/api/v1/chat/stream` | POST | SSE | Direct help agent — streaming (**primary for frontend**) |
| `/api/v1/assistant/chat` | POST | JSON | Unified router (help / rdd / tenant\_ops / service\_request) — sync |
| `/api/v1/assistant/chat/stream` | POST | SSE | Unified router — streaming |

Source: `cenomi-ai-backend/app/main.py` (router mounts) and
`cenomi-ai-backend/app/api/routes/go_compat_routes.py` /
`cenomi-ai-backend/app/api/routes/assistant_compat.py`.

---

### A.2 Authentication Headers

Both headers are required on every request:

```http
x-internal-api-token: <service-uuid>        # from REACT_APP_AI_API_KEY env var
Authorization: Bearer <ai_token>            # short-lived JWT from cenomi-api-2
```

Obtain `ai_token` before the first chat turn:

```http
POST /api/v1/auth/ai-session-token          # on cenomi-api-2, with session cookie
→ { "ai_token": "eyJ...", "expires_in": 3600 }
```

---

### A.3 Request Body

Applies to all four endpoints (direct + unified, sync + stream):

```typescript
// cenomi-ai-backend/app/api/routes/go_compat_routes.py  →  ChatRequest (Pydantic)
{
  "message":         string,          // required, 1–4000 chars
  "conversation_id": string,          // optional — Azure Foundry thread ID for multi-turn
  "language":        "en" | "ar",    // optional — auto-detected if omitted
  "context": {                        // optional — page-aware RAG grounding
    "current_url_pattern": string,    // e.g. "/servicerequest"
    "help_category":       string,    // e.g. "Service Requests"
    "help_subcategory":    string     // e.g. "How to Submit"
  }
}
```

Example:

```json
{
  "message": "How do I submit a service request?",
  "language": "en",
  "context": { "current_url_pattern": "/servicerequest" }
}
```

---

### A.4 Sync Response — `POST /api/v1/chat`

```python
# cenomi-ai-backend/app/agents/help/usecase.py  →  ChatResponse (dataclass)
{
  "conversation_id": string,    # Azure Foundry thread ID — reuse for multi-turn
  "message_id":      string,    # Azure Foundry message ID
  "message":         string,    # assistant reply text
  "sources":         Source[],  # RAG citations — see §A.6
  "language":        string     # "en" | "ar"
}
```

Example:

```json
{
  "conversation_id": "thread_abc123",
  "message_id":      "msg_xyz789",
  "message":         "To submit a service request, navigate to...",
  "sources": [
    { "source_type": "help_content", "title": "help_content_42_en_chunk0" }
  ],
  "language": "en"
}
```

---

### A.5 Sync Response — `POST /api/v1/assistant/chat` (unified router)

When routed to the help agent, wraps the above in `AssistantChatResponse`:

```python
# cenomi-ai-backend/app/api/routes/assistant_compat.py  →  AssistantChatResponse (Pydantic)
{
  "agent":           "help",
  "conversation_id": string,
  "message_id":      string,
  "message":         string,
  "language":        string,
  "sources":         Source[],  # same as §A.6
  "routing":         RoutingTrace | null,
  "session_id":      null,      # only set for service_request agent
  "trace_id":        null,
  "ui":              null,      # only set for service_request agent
  "state":           null,      # only set for service_request agent
  "draft":           null,      # only set for service_request agent
  "silent":          null
}
```

`RoutingTrace` shape:

```python
{
  "agent":               string,   # "help"
  "method":              string,   # classifier method used
  "confidence":          float,
  "reason":              string,
  "rephrased_query":     string,
  "needs_confirmation":  bool,
  "url_agent":           string,
  "intent_agent":        string,
  "confirmation_prompt": string
}
```

---

### A.6 Source Object — MSP Contract

```python
# cenomi-ai-backend/app/integrations/azure/foundry.py  →  Source (dataclass)
{
  "source_type": string,   # "help_content" | "user_guide" | "mall_info" | "key_contact" | "event"
  "title":       string    # raw file_id from indexer, e.g. "help_content_42_en_chunk0"
}
```

> The `url_pattern` and `mall_name` fields exist on the dataclass but are **not populated** in
> responses today. Only `source_type` and `title` are serialised.

Source type → origin:

| `source_type` | Knowledge base table |
|---|---|
| `help_content` | Platform help pages (indexed per section per language) |
| `user_guide` | PDF user guides |
| `mall_info` | Mall-specific data (hours, facilities) |
| `key_contact` | Mall manager / department contacts |
| `event` | Announcements and events |

---

### A.7 SSE Stream — `POST /api/v1/chat/stream`

Response: `Content-Type: text/event-stream`. Each event:

```
event: <type>
data: <json>

```

| `event:` | `data:` JSON | Frontend action |
|----------|-------------|----------------|
| `token` | `{"text": "..."}` | Append to streaming message bubble |
| `source` | `{"source_type": "...", "title": "..."}` | Add citation chip below bubble |
| `citations_delta` | `{"add": N}` | Optional incremental citation count hint |
| `citations_count` | `{"total": N}` | Optional final citation count hint |
| `done` | `{"conversation_id": "...", "message_id": "..."}` | End stream; save thread ID |
| `error` | `{"message": "..."}` | Show error state |

`token` events arrive many times — concatenate in order to build the full message.
`source` events arrive after the `done` event (emitted from `thread.message.completed`).

Source: `cenomi-ai-backend/app/integrations/azure/foundry.py` `_handle_sse_event()`.

---

### A.8 Non-stream Errors (before SSE starts)

If the server rejects before streaming (auth failure, validation, 5xx), the response is
**JSON, not SSE**:

```json
{
  "success": false,
  "errors": [{ "code": 422, "message": "message is required" }]
}
```

Frontend must check `response.ok` before starting the SSE parser.

---

### A.9 MSP Frontend TypeScript Types (from `FRONTEND_CHAT_WIDGET.md`)

```typescript
// Request
interface ChatRequest {
  message:          string;
  conversation_id?: string;
  language?:        'en' | 'ar';
  context?: {
    current_url_pattern?: string;
    help_category?:        string;
    help_subcategory?:     string;
  };
}

// Source citation
export interface Source {
  source_type: 'help_content' | 'user_guide' | 'mall_info' | 'key_contact' | 'event';
  title:            string;
  url_pattern?:     string;
  help_content_id?: number;
  guide_id?:        number;
  document_id?:     string;
  property_id?:     number;
}

// In-memory message (useChat.ts)
export interface Message {
  id:        string;
  role:      'user' | 'assistant';
  content:   string;     // built token by token from SSE
  sources:   Source[];   // populated from SSE 'source' events
  streaming: boolean;
  error:     boolean;
}
```

---

## §B — RDD-Chatbot Help Agent Contract (`service-request-chatbot`)

This is the contract currently implemented in the RDD-Chatbot codebase.

### B.1 Endpoint

```
POST /api/chat/service-request
```

Single synchronous JSON endpoint — **no SSE streaming**.

Source: `backend/app/api/routes/chat.py` mounted via `app/main.py` at `/api`.

---

### B.2 Authentication

```http
Authorization: Bearer <jwt>    # from the chatbot's own auth system
```

`user_id` is also accepted in the request body as a POC fallback when no JWT is present.

---

### B.3 Request Body — `ServiceRequestChatRequest`

```python
# backend/app/api/routes/chat.py
{
  "session_id":         string | null,   # chatbot session UUID (not Azure Foundry thread ID)
  "user_id":            string,          # POC fallback; JWT subject overrides
  "message":            string,          # required unless sr_id present
  "attachments":        [],
  "action":             string | null,   # "confirm" | "cancel" | FM/RDD lifecycle actions
  "selected_lease_id":  string | null,
  "corrected_fields":   {} | null,
  "sr_id":              string | null    # opens existing SR (FM/DD flow)
}
```

**No `context`, `language`, `conversation_id`, or `current_url_pattern` fields.**

---

### B.4 Response — `ServiceRequestChatResponse`

```python
# backend/app/api/routes/chat.py
{
  "session_id":    string,                  # chatbot session UUID
  "active_agent":  string | null,           # null on FAQ turns
  "message":       string,                  # assistant reply text
  "ui":            { "type": "message" },   # discriminated union — see §9
  "draft_preview": null,                    # null on FAQ turns
  "faq_sources":   Source[],               # RAG citations — see §B.5
  "state": {
    "intent":          string | null,
    "workflow_stage":  string | null,
    "missing_fields":  string[],
    "ready_to_submit": bool
  },
  "trace_id": string | null
}
```

---

### B.5 Source Object — RDD-Chatbot

```python
# faq_node returns: {"source_type": str, "title": str}
# built from SearchResult in backend/app/integrations/search/base.py
{
  "source_type": string,   # "help_content" | "mall_info" | "key_contact" | "event"
  "title":       string
}
```

> `user_guide` is a valid `source_type` in the MSP contract but is **not present** in the
> RDD-Chatbot knowledge base. The other four types are shared.

Citations are also embedded inline in `message` as `[Source: title]` text markers
(up to 3 per turn) by `faq_node`.

---

### B.6 Protocol

**Synchronous JSON only.** No `EventSource`, `text/event-stream`, or async token streaming.
The frontend shows a loading bubble while awaiting the full response.

---

## §C — Alignment Gap Analysis

Side-by-side comparison of the two contracts. All deltas that must be resolved before
the RDD-Chatbot help agent can serve the MSP Platform frontend.

### C.1 Request Shape

| Field | MSP Platform (`cenomi-ai-backend`) | RDD-Chatbot | Gap |
|-------|------------------------------------|-------------|-----|
| User message | `message` | `message` | ✅ Aligned |
| Session/thread continuity | `conversation_id` (Azure Foundry thread) | `session_id` (chatbot DB session) | ❌ Different field name and semantics |
| Page-aware RAG | `context.current_url_pattern` | *(not present)* | ❌ Missing in RDD-Chatbot |
| Help category hint | `context.help_category` | *(not present)* | ❌ Missing in RDD-Chatbot |
| Language hint | `language` | *(not present)* | ❌ Missing in RDD-Chatbot |
| Auth — service key | `x-internal-api-token` header | *(not present)* | ❌ Different auth model |
| Auth — user JWT | `Authorization: Bearer <ai_token>` (from cenomi-api-2) | `Authorization: Bearer <jwt>` (own auth) | ❌ Different JWT issuer |
| SR lifecycle fields | *(not present)* | `action`, `selected_lease_id`, `corrected_fields`, `sr_id` | SR-only — irrelevant for help path |

---

### C.2 Response Shape (Help / FAQ path)

| Field | MSP Platform | RDD-Chatbot | Gap |
|-------|-------------|-------------|-----|
| Message text | `message` | `message` | ✅ Aligned |
| Source citations key | `sources` | `faq_sources` | ❌ **Field name differs** |
| Source item: `source_type` | `source_type` | `source_type` | ✅ Aligned |
| Source item: `title` | `title` | `title` | ✅ Aligned |
| Source type values | `help_content`, `user_guide`, `mall_info`, `key_contact`, `event` | `help_content`, `mall_info`, `key_contact`, `event` | ⚠️ `user_guide` missing from RDD-Chatbot KB |
| Thread/session ID | `conversation_id` (Azure Foundry thread) | `session_id` (DB UUID) | ❌ Different semantics |
| Message ID | `message_id` | *(not present)* | ❌ Missing in RDD-Chatbot |
| Language | `language` | *(not present)* | ❌ Missing in RDD-Chatbot |
| Agent identifier | `agent: "help"` | `active_agent: null` | ❌ Name and position differ |
| Routing trace | `routing: RoutingTrace` | *(not present)* | ❌ Missing in RDD-Chatbot |

---

### C.3 Protocol

| Aspect | MSP Platform | RDD-Chatbot | Gap |
|--------|-------------|-------------|-----|
| Streaming | SSE (`text/event-stream`) — **required by frontend** | Synchronous JSON | ❌ **RDD-Chatbot must implement SSE** |
| SSE: `token` event | `{"text": "..."}` | *(not implemented)* | ❌ Missing |
| SSE: `source` event | `{"source_type": "...", "title": "..."}` | *(not implemented)* | ❌ Missing |
| SSE: `done` event | `{"conversation_id": "...", "message_id": "..."}` | *(not implemented)* | ❌ Missing |
| SSE: `error` event | `{"message": "..."}` | *(not implemented)* | ❌ Missing |

---

### C.4 Summary of Required Changes

To align the RDD-Chatbot help agent with the MSP Platform contract:

1. **Rename `faq_sources` → `sources`** in `ServiceRequestChatResponse` (Python) and map it in `chat-client.ts` (TypeScript). This is the single highest-priority change for source citation display.

2. **Add `conversation_id` to request/response.** The MSP frontend sends `conversation_id` (Azure Foundry thread ID) and expects to receive it back. The RDD-Chatbot's `session_id` must be mapped to this field — or the help path must create and return an Azure Foundry thread ID directly.

3. **Add `context.current_url_pattern` support.** The MSP frontend sends the current URL for page-aware RAG grounding. `ServiceRequestChatRequest` needs a `context` field and `faq_node` needs to consume it for search filtering.

4. **Add `language` to request and response.** The MSP contract sends and returns `"en" | "ar"`.

5. **Add `message_id` to response.** MSP response includes a per-message ID for observability.

6. **Implement SSE streaming.** The MSP frontend's `useChat.ts` hook exclusively uses `POST /api/v1/chat/stream` (SSE). The RDD-Chatbot must expose a streaming endpoint emitting `token`, `source`, `done`, and `error` events.

7. **Switch auth to `x-internal-api-token` + cenomi-api-2 JWT.** The service-key model must match.

8. **Expose response at `/api/v1/chat` and `/api/v1/chat/stream`** (or `/api/v1/assistant/chat` / `/api/v1/assistant/chat/stream`) to match the MSP route prefix.

---

## §D — RDD-Chatbot Internal Validation

Use this section to validate the RDD-Chatbot implementation in isolation before any MSP integration work.

### D.1 Graph Entry Point

| Check | Expected | File |
|-------|----------|------|
| Graph is compiled once and reused | `get_compiled_help_graph()` singleton | `backend/app/agents/graph/help_agent_graph.py` |
| Orchestration calls the graph | `ChatOrchestrationService.process_turn()` → `get_compiled_help_graph().ainvoke()` | `backend/app/services/chat_orchestration_service.py` |
| FAQ intents | `_FAQ_INTENTS = frozenset({"ASK_HELP", "UNKNOWN"})` | `help_agent_graph.py` line 95 |

### Graph node order (FAQ turn)

```
START
  → load_session          resets faq_sources = []
  → supervisor_node       LLM → SupervisorDecision (intent = ASK_HELP)
  → faq_node              RAG search + LLM answer + faq_sources
  → save_state
  → END
```

> `faq_node` bypasses `response_generation_node` to preserve inline `[Source: ...]` markers.

---

### D.2 Intent Routing — `SupervisorDecision`

File: `backend/app/agents/schemas/supervisor_schema.py`

```python
class SupervisorDecision(BaseModel):
    intent: Literal[
        "ASK_HELP",
        "CREATE_RDD_SERVICE_REQUEST",
        "UPDATE_RDD_SERVICE_REQUEST",
        "APPROVE_RDD_SERVICE_REQUEST",
        "CHECK_SERVICE_REQUEST_STATUS",
        "PREVIEW_SERVICE_REQUEST",
        "UNKNOWN",
    ]
    confidence:       float        # [0.0, 1.0]
    service_category: str | None
    sub_category:     str | None
    target_agent:     str | None
    reasoning:        str
```

### Role → Permitted Intents

File: `backend/app/agents/schemas/help_agent_schema.py`

| Role | Permitted Action Intents (on top of read intents) |
|------|--------------------------------------------------|
| `MALL_MANAGER` | `CREATE_RDD_SERVICE_REQUEST`, `UPDATE_RDD_SERVICE_REQUEST`, `CREATE_WORK_PERMIT_SR` |
| `FM_MANAGER` | `APPROVE_RDD_SERVICE_REQUEST` |
| `OPERATIONS` | `APPROVE_RDD_SERVICE_REQUEST` |
| `DD_ENGINEER` | *(read intents only)* |
| `ADMIN` | All intents |

Read intents (every role): `ASK_HELP`, `CHECK_SERVICE_REQUEST_STATUS`, `PREVIEW_SERVICE_REQUEST`, `UNKNOWN`

---

### D.3 FAQ Node

File: `backend/app/agents/graph/nodes/faq/faq_node.py`

**LLM output shape expected:**
```json
{ "message": "<answer text>" }
```

**Inline citation format embedded in `response_message`** (up to 3 sources):
```
<answer text>

[Source: FM Review Checklist], [Source: Handover Process Guide]
```

**Fallback behaviour:**

| Condition | `rag_block` | `faq_sources` |
|-----------|-------------|---------------|
| No search credentials | `""` | `[]` |
| Search throws exception | `""` | `[]` |

**Node return value:**
```python
{
    "response_message": str,           # full answer with inline [Source: ...] markers
    "status":           "WAITING_FOR_USER",
    "faq_sources":      list[dict],    # [{source_type, title}, ...]
}
```

---

### D.4 `faq_sources` Item Schema

Wire shape (only these two fields are serialised):

```json
{ "source_type": "help_content", "title": "FM Review Checklist" }
```

Source dataclass (not serialised fully):
```python
# backend/app/integrations/search/base.py
@dataclass
class SearchResult:
    source_type: str    # "help_content" | "mall_info" | "key_contact" | "event"
    title:       str
    content:     str    # NOT in faq_sources
    url_pattern: str    # NOT in faq_sources
    mall_name:   str    # NOT in faq_sources
    language:    str    # NOT in faq_sources
```

---

### D.5 Graph State

File: `backend/app/agents/graph/state.py`

Relevant fields for FAQ path:

```python
class ServiceRequestGraphState(TypedDict, total=False):
    user_message:          str
    conversation_history:  list[dict]   # last N turns {"role", "content"}
    active_agent:          Optional[str]
    intent:                Optional[str]
    workflow_stage:        Optional[str]
    response_message:      str
    faq_sources:           list[dict]   # [{source_type, title}, ...]
    status:                Literal["IN_PROGRESS","WAITING_FOR_USER","READY_TO_SUBMIT",
                                   "SUBMITTED","COMPLETED","FAILED"]
    response_ui:           dict[str, Any]
```

---

### D.6 Orchestration Result

File: `backend/app/services/chat_orchestration_service.py`

```python
@dataclass(frozen=True, slots=True)
class ChatTurnResult:
    session_id:    UUID
    active_agent:  str | None
    message:       str
    ui:            dict[str, Any]
    state:         ChatTurnState
    trace_id:      UUID | None
    draft_preview: dict[str, Any] | None = None
    faq_sources:   list[dict] = field(default_factory=list)
```

---

### D.7 HTTP Response Model

File: `backend/app/api/routes/chat.py`

```python
class ServiceRequestChatResponse(BaseModel):
    session_id:    str
    active_agent:  str | None
    message:       str
    ui:            dict[str, Any]             # {"type": "message"} on FAQ turns
    draft_preview: dict[str, Any] | None      # null on FAQ turns
    faq_sources:   list[dict[str, Any]]       # [{source_type, title}, ...]
    state:         ChatStatePayload
    trace_id:      str | None

class ChatStatePayload(BaseModel):
    intent:          str | None   # "ASK_HELP"
    workflow_stage:  str | None   # null on FAQ turns
    missing_fields:  list[str]    # []
    ready_to_submit: bool         # False
```

**Example FAQ response:**

```json
{
  "session_id":   "550e8400-e29b-41d4-a716-446655440000",
  "active_agent": null,
  "message":      "For FM Review, three documents are required...\n\n[Source: FM Review Checklist], [Source: Handover Process Guide]",
  "ui":           { "type": "message" },
  "draft_preview": null,
  "faq_sources": [
    { "source_type": "help_content", "title": "FM Review Checklist" },
    { "source_type": "help_content", "title": "Handover Process Guide" }
  ],
  "state": {
    "intent": "ASK_HELP",
    "workflow_stage": null,
    "missing_fields": [],
    "ready_to_submit": false
  },
  "trace_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

---

### D.8 `ui` Discriminated Union

| `ui.type` | When | Component |
|-----------|------|-----------|
| `message` | FAQ answers, plain replies | `MessageBubble` |
| `lease_selection` | Multiple lease matches | `LeaseSelectionCard` |
| `confirmation_card` | SR pre-submit review | `ServiceRequestSummaryCard` |
| `validation_error` | Field validation failed | `FieldCorrectionPanel` |
| `workflow_progress` | Stage update | `WorkflowProgressCard` |
| `document_requirement` | FM/RDD doc upload | `DocumentRequirementCard` |
| `sr_preview_card` | SR status / draft | `SRPreviewCard` |

---

### D.9 Frontend TypeScript Contract

File: `frontend/lib/types/chat.ts`

```typescript
export type ChatServiceResponse = {
  sessionId:      string;
  traceId?:       string;
  responseUI:     ResponseUI;
  draftPreview?:  ResponseUISRPreviewCard;
  workflowStage?: string | null;
  srId?:          string | null;
  intent?:        string | null;
  missingFields?: string[];
  readyToSubmit?: boolean;
  // ⚠️ faqSources is MISSING — data.faq_sources is dropped in chat-client.ts
};
```

---

### D.10 Frontend API Client

File: `frontend/lib/api/chat-client.ts`

Wire → frontend field mapping:

| Backend JSON key | Frontend field | Notes |
|------------------|----------------|-------|
| `session_id` | `sessionId` | |
| `trace_id` | `traceId` | |
| `ui` + `message` | `responseUI` | Merged: `{...data.ui, message: data.ui?.message ?? data.message}` |
| `draft_preview` | `draftPreview` | `message` forced to `""` |
| `state.workflow_stage` | `workflowStage` | |
| `state.intent` | `intent` | |
| `state.missing_fields` | `missingFields` | |
| `state.ready_to_submit` | `readyToSubmit` | |
| `faq_sources` | *(dropped — not mapped)* | **Known gap** |

---

### D.11 Known Gap — `faq_sources` Not Consumed by Frontend

| Layer | Status |
|-------|--------|
| Backend returns `faq_sources` | ✅ |
| `ChatServiceResponse` has `faqSources` | ❌ |
| `chat-client.ts` maps `data.faq_sources` | ❌ |
| Citation chip component exists | ❌ |

Fix:
1. Add `faqSources?: Array<{ source_type: string; title: string }>` to `ChatServiceResponse`
2. Map `data.faq_sources` in `chat-client.ts`
3. Render citation chips below `MessageBubble` when `faqSources.length > 0`

---

## §E — End-to-End Validation Checklist

### E.1 RDD-Chatbot (internal)

- [ ] `POST /api/chat/service-request` returns HTTP 200 for a help question
- [ ] `faq_sources` array is present and non-null in the response
- [ ] Each `faq_sources` item has `source_type` and `title` fields
- [ ] `active_agent` is `null` on FAQ turns
- [ ] `ui.type` is `"message"` on FAQ turns
- [ ] `state.intent` is `"ASK_HELP"` for a help question
- [ ] `state.workflow_stage` is `null` on FAQ turns
- [ ] Message contains inline `[Source: ...]` markers when RAG finds results
- [ ] No `[Source: ...]` markers when RAG returns no results
- [ ] `faq_sources` resets to `[]` at the start of each new turn (verified via `load_session_node`)
- [ ] RBAC: any role can ask `ASK_HELP` questions
- [ ] RBAC: `MALL_MANAGER` can trigger `CREATE_RDD_SERVICE_REQUEST`
- [ ] RBAC: `FM_MANAGER` cannot trigger `CREATE_RDD_SERVICE_REQUEST`

### E.2 MSP Platform alignment

- [ ] Response has `sources` field (not `faq_sources`) — **rename required**
- [ ] Response has `conversation_id` field — **add required**
- [ ] Response has `message_id` field — **add required**
- [ ] Response has `language` field — **add required**
- [ ] Request accepts `context.current_url_pattern` and passes it to `faq_node` — **add required**
- [ ] Request accepts `language` — **add required**
- [ ] SSE streaming endpoint exists at `/api/v1/chat/stream` — **implement required**
- [ ] SSE emits `token`, `source`, `done`, `error` events in MSP format — **implement required**
- [ ] Auth accepts `x-internal-api-token` header — **implement required**

---

## §F — Key File Index

### RDD-Chatbot (`service-request-chatbot`)

| File | Purpose |
|------|---------|
| `backend/app/agents/graph/help_agent_graph.py` | LangGraph node wiring, routing functions |
| `backend/app/agents/graph/state.py` | `ServiceRequestGraphState` TypedDict (incl. `faq_sources`) |
| `backend/app/agents/graph/nodes/faq/faq_node.py` | FAQ RAG + LLM node |
| `backend/app/agents/graph/nodes/shared/load_session_node.py` | Resets `faq_sources = []` each turn |
| `backend/app/agents/schemas/supervisor_schema.py` | `SupervisorDecision` — live LLM routing output |
| `backend/app/agents/schemas/help_agent_schema.py` | RBAC `ROLE_PERMITTED_INTENTS`, `intents_for_roles()` |
| `backend/app/integrations/search/base.py` | `SearchResult` dataclass — RAG retrieval type |
| `backend/app/services/chat_orchestration_service.py` | `ChatTurnResult`, `ChatTurnState` |
| `backend/app/api/routes/chat.py` | `ServiceRequestChatRequest`, `ServiceRequestChatResponse`, `ChatStatePayload` |
| `backend/app/agents/prompts/faq_prompt.py` | `FAQ_SYSTEM_PROMPT` |
| `frontend/lib/types/chat.ts` | All frontend TypeScript types |
| `frontend/lib/api/chat-client.ts` | `postServiceRequestChat()` — API call + response mapping |
| `frontend/components/chatbot/MessageBubble.tsx` | Renders FAQ answer text |

### MSP Platform (`cenomi-ai-backend`)

| File | Purpose |
|------|---------|
| `app/api/routes/go_compat_routes.py` | `POST /api/v1/chat` and `/chat/stream` — direct help endpoints |
| `app/api/routes/assistant_compat.py` | `POST /api/v1/assistant/chat` and `/assistant/chat/stream` — unified router |
| `app/agents/help/usecase.py` | `ChatRequest`, `ChatResponse`, `ChatContext`, `HelpUsecase` |
| `app/integrations/azure/foundry.py` | `Source`, `StreamEvent`, `AgentResponse`, SSE event emission |
| `app/main.py` | Router mounts — all endpoint prefixes |
| `FRONTEND_CHAT_WIDGET.md` | Full widget spec: `useChat.ts`, `SourceChip.tsx`, all TypeScript types |
| `FRONTEND_STREAM_API_INTEGRATION.md` | SSE wiring guide — token/source/done/error parser |
