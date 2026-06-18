# Agent Design

## Overview

The backend agent system is built on [LangGraph](https://github.com/langchain-ai/langgraph). Each user turn compiles and runs a deterministic directed graph. There is **no LangGraph interrupt/resume** — every turn invokes `get_compiled_graph().ainvoke(initial_state)` from scratch, with the prior conversation state loaded from PostgreSQL.

---

## Frontend / Backend Contract

The frontend is a **generic conversational shell**. It does not select agents, does not identify intent, and does not control routing. The full pipeline — intent identification, agent routing, workflow continuation, validation, confirmation gating, payload construction, and API submission — belongs exclusively to the backend.

### What the frontend sends

Every chat turn carries only the following fields:

| Field | Type | Purpose |
|---|---|---|
| `session_id` | `str` | Identifies the conversation |
| `message` | `str` | Raw user text |
| `attachment_ids` | `list[str]` | Uploaded file references |
| `selected_lease_id` | `str \| None` | User selection from a lease disambiguation UI |
| `corrected_fields` | `dict \| None` | Inline field edits from a confirmation card |
| `action` | `str \| None` | UI interaction: `"confirm"`, `"cancel"`, or omitted |

### What the frontend must never send

The following fields are owned by the backend and **must not be accepted from, or controlled by, the frontend**:

- `active_agent` — resolved by the Agent Registry; persisted to the database and reloaded on the next turn.
- `intent` — classified by the Supervisor Agent.
- `service_category` / `sub_category` — extracted by the Supervisor; used deterministically by the registry for routing.
- `workflow_stage` — advanced by backend graph nodes only.

### How routing works (backend-owned)

```
User message
  → Chat API
  → Injection Guard
  → ChatOrchestrationService
  → Load Session State          ← routing fields loaded from DB, never from FE
  → Intent Identification       ← Supervisor Agent (LLM classification)
  → Agent Registry / Router     ← deterministic (service_category, sub_category) lookup
  → Service Request Agent       ← e.g. Handover / FM / RDD
  → Field Extraction / Validation / Confirmation / Payload Builder / API Submission
  → Response Generation
  → Save State                  ← active_agent, intent, workflow_stage persisted to DB
```

**Workflow continuation:** On subsequent turns where `active_agent` was already resolved and persisted by the backend, `load_session_node` routes directly to the agent's entry node, bypassing the Supervisor. This is backend-driven continuation — the frontend never instructs the backend to resume a specific agent.

**LLM hint vs. registry:** The Supervisor may set a `target_agent` hint in its `SupervisorDecision` output. This hint is advisory only. The `registry_node` always performs a deterministic `(service_category, sub_category)` lookup and its result wins.

**Extensibility:** The current product scope is Service Request / Handover. The Supervisor and Agent Registry are designed so that additional agents can be added in future by registering new `(service_category, sub_category)` entries — without any changes to the frontend contract.

---

## Supervisor Agent

**File:** `app/agents/graph/nodes/supervisor_node.py`  
**Schema:** `app/agents/schemas/supervisor_schema.py`

The Supervisor is the backend's entry point for **intent identification**. It runs at the beginning of every turn where no `active_agent` is set (i.e. the first turn of a new intent, or after a workflow restart). The frontend never identifies intent — it sends only the raw user message, and the Supervisor performs a single LLM call to classify intent and, optionally, extract an initial `service_category` / `sub_category`.

**`SupervisorDecision` schema:**

```python
class SupervisorDecision(BaseModel):
    intent: Literal[
        "CREATE_HANDOVER_SERVICE_REQUEST",
        "UPDATE_HANDOVER_SERVICE_REQUEST",
        "APPROVE_HANDOVER_SERVICE_REQUEST",
        "CHECK_SERVICE_REQUEST_STATUS",
        "PREVIEW_SERVICE_REQUEST",
        "UNKNOWN",
    ]
    service_category: str | None
    sub_category: str | None
    target_agent: str | None      # optional downstream agent hint
    confidence: float
    reasoning: str  # chain-of-thought, stripped before trace persistence
```

**Behaviour:**

- If confidence < `CONFIDENCE_THRESHOLD` (0.6) the supervisor sets `intent = "UNKNOWN"` and routes to `response_generation` with a clarification prompt.
- **Preview bypass:** If `_user_wants_preview(user_message)` is true, `_route_after_load` always sends the turn to `supervisor` — even when `active_agent` is already set — so the LLM can classify `PREVIEW_SERVICE_REQUEST` and route to the `preview` node.
- **SR status sync bypass:** When `backend_refs.sr_id` is already set (SR has been created), `_route_after_load` routes to `sr_status_sync` first to refresh the platform stage before deciding the next node.
- If neither of the above applies and `active_agent` is already set, `_route_after_load` skips the supervisor and routes directly to the entry node via `_AGENT_ENTRY_NODES`.
- The supervisor also handles session continuity: if the session has a saved `intent` and `service_category`, those are injected into the state before the LLM call so the model has context.

**Tracing:** Decorated with `@trace_node("supervisor", "SUPERVISOR")`. Opens a nested `LLM` run and calls `TraceManager.capture_llm_call`.

---

## Agent Registry

**File:** `app/agents/registries/service_request_registry.py`

The registry maps `(service_category, sub_category)` pairs to a concrete agent name and schema key.

```python
SERVICE_REQUEST_AGENT_REGISTRY = {
    ("FIT_OUT_AND_HANDOVER", "HANDOVER"): {
        "agent_name": "handover_service_request_agent",
        "schema_key": "handover_service_request_schema",
    },
    # Additional entries for future service categories
}
```

The registry is the **deterministic source of truth for agent routing**. The frontend never selects an agent — the registry resolves it from `(service_category, sub_category)` produced by the Supervisor. Any LLM-provided `target_agent` hint in `SupervisorDecision` is advisory only; the registry result always wins.

**`registry_node` logic:**

1. Calls `lookup_agent(service_category, sub_category)`.
2. If a registry entry is found, its result overrides any LLM-generated `target_agent` hint — the registry is the single source of truth for agent routing.
3. Sets `state["active_agent"]` and `state["schema_key"]`, which are then persisted to the database by `save_state_node` and reloaded on the next turn for workflow continuation.
4. If no match is found and no `active_agent` is set, routes to `response_generation` with an unsupported category message.

---

## Handover Agent

The handover agent is not a separate class — it is the collection of nodes that execute once `active_agent = "handover_service_request_agent"` is set. These nodes share the `HandoverExtractedFields` schema and the `CREATE_SR_STAGE` configuration.

**`handover_entry_node`** (`app/agents/graph/nodes/handover_entry_node.py`):

- **UI action override (priority 0):** If `action_override == "confirm"` (explicit button press), immediately sets `confirmation_status = "CONFIRMED"`. If `action_override == "cancel"`, sets `confirmation_status = "REJECTED"` and returns a correction prompt — routing continues to `merge_state`.
- **Workflow cancel / restart:** If the user message matches any phrase in `_CANCEL_WORKFLOW_PHRASES` (e.g. `"start over"`, `"restart"`, `"new request"`), clears all workflow state (`active_agent`, `intent`, `collected_data`, `confirmation_status`, lease data, etc.) and sets `status = "WAITING_FOR_USER"`. The routing function then sends the turn directly to `response_generation` (not back to `supervisor`).
- **Confirmation response parsing:** If `confirmation_status == "PENDING"`, checks the user message against `_CONFIRM_PHRASES` and `_REJECT_PHRASES` keyword sets using word-boundary regex matching.
  - Match in `_CONFIRM_PHRASES` → `confirmation_status = "CONFIRMED"`.
  - Match in `_REJECT_PHRASES` → `confirmation_status = "REJECTED"`, returns a correction prompt.
  - No match (ambiguous input) → returns a clarification prompt; does not change `confirmation_status`.
- This node runs **before** any LLM or field extraction — confirmation is resolved by keyword matching, not LLM judgment.

---

## Graph Nodes

| Node | File | Trace run_type | Description |
|------|------|---------------|-------------|
| `load_session_node` | `nodes/load_session_node.py` | — | `ConversationStateService.load` merges draft into state |
| `sr_status_sync_node` | `nodes/sr_status_sync_node.py` | `TOOL` | Calls `GET /service-requests/{sr_id}`; maps platform `service_request_operations` to `workflow_stage` |
| `supervisor_node` | `nodes/supervisor_node.py` | `SUPERVISOR` | LLM intent classification |
| `preview_node` | `nodes/preview_node.py` | `AGENT` | Fetches live SR or summarises draft `collected_data`; routes to `response_generation` |
| `registry_node` | `nodes/registry_node.py` | `AGENT` | Lookup agent by `(service_category, sub_category)` |
| `handover_entry_node` | `nodes/handover_entry_node.py` | `AGENT` | CREATE_SR stage boundary — cancel + confirmation parsing |
| `fm_review_entry_node` | `nodes/fm_review_entry_node.py` | `AGENT` | FM_REVIEW stage boundary — role check, upload handling, action dispatch |
| `rdd_review_entry_node` | `nodes/rdd_review_entry_node.py` | `AGENT` | RDD_REVIEW stage boundary — role check, upload handling, action dispatch |
| `field_extraction_node` | `nodes/field_extraction_node.py` | `AGENT` | LLM field extraction via `FieldExtractionService` |
| `merge_state_node` | `nodes/merge_state_node.py` | `CHAIN` | Merge extracted fields into `collected_data`; protect backend fields; auto-generate title |
| `lease_lookup_node` | `nodes/lease_lookup_node.py` | `TOOL` | Resolve tenant lease from Lease-Tenant API |
| `validation_node` | `nodes/validation_node.py` | `AGENT` | `ValidationService` — required fields, types, constraints |
| `missing_field_node` | `nodes/missing_field_node.py` | `AGENT` | Generate next clarifying question |
| `confirmation_node` | `nodes/confirmation_node.py` | `AGENT` | CREATE_SR — build `confirmation_card` UI, set `confirmation_status = PENDING` |
| `fm_confirmation` | `nodes/confirmation_node.py` (shared) | `AGENT` | FM_REVIEW — same node, routes to `fm_payload_builder` on CONFIRMED |
| `rdd_confirmation` | `nodes/confirmation_node.py` (shared) | `AGENT` | RDD_REVIEW — same node, routes to `rdd_payload_builder` on CONFIRMED |
| `payload_builder_node` | `nodes/payload_builder_node.py` | `AGENT` | `build_create_handover_payload` → `backend_refs.create_payload` |
| `fm_payload_builder_node` | `nodes/fm_payload_builder_node.py` | `AGENT` | `build_fm_review_payload` / `build_fm_approve_payload` → `backend_refs.fm_payload` |
| `rdd_payload_builder_node` | `nodes/rdd_payload_builder_node.py` | `AGENT` | `build_rdd_report_payload` → `backend_refs.rdd_payload` |
| `api_submission_node` | `nodes/api_submission_node.py` | `TOOL` | POST `/service-requests` — CREATE_SR |
| `fm_api_submission_node` | `nodes/fm_api_submission_node.py` | `TOOL` | PATCH `/service-requests/{sr_id}` — FM save-progress or approve |
| `rdd_api_submission_node` | `nodes/rdd_api_submission_node.py` | `TOOL` | POST `/service-requests` with `status=REPORT_SUBMITTED` — RDD submit |
| `response_generation_node` | `nodes/response_generation_node.py` | `AGENT` | LLM generates natural-language response; sets `WAITING_FOR_USER` |
| `save_state_node` | `nodes/save_state_node.py` | — | `ConversationStateService.save_checkpoint` |

---

## State Design

**Type:** `ServiceRequestGraphState(TypedDict, total=False)` in `app/agents/graph/state.py`.

All keys are optional (`total=False`) because state is incrementally populated across graph nodes.

```python
class ServiceRequestGraphState(TypedDict, total=False):
    # Session identity
    session_id: str
    user_id: str
    user_message: str             # current user message (field name is user_message, not message)
    attachments: list[dict]       # uploaded file attachment metadata
    trace_id: str                 # observability trace ID for this turn
    conversation_history: list[dict]  # recent chat history [{role, content}, ...]

    # Routing
    active_agent: str | None      # e.g. "handover_service_request_agent"
    intent: str | None            # e.g. "CREATE_HANDOVER_SERVICE_REQUEST"
    workflow_stage: str | None    # e.g. "CREATE_SR", "SR_CREATED"
    status: str | None            # "IN_PROGRESS" | "WAITING_FOR_USER" | "READY_TO_SUBMIT"
                                  # | "SUBMITTED" | "COMPLETED" | "FAILED"

    # Service classification
    service_category: str | None  # e.g. "FIT_OUT_AND_HANDOVER"
    sub_category: str | None      # e.g. "HANDOVER"

    # Data collection
    collected_data: dict          # validated, merged user-supplied + lease data
    extracted_fields: dict        # raw LLM extraction output {field: {value, confidence}}
    missing_fields: list[str]     # fields still required

    # Lease
    selected_lease: dict | None   # user-selected lease from disambiguation UI
    lease_matches: list[dict]     # all leases returned by API (for disambiguation)

    # Documents
    documents: list[dict]         # uploaded document metadata

    # Confirmation
    confirmation_required: bool
    confirmation_status: str | None  # None | "PENDING" | "CONFIRMED" | "REJECTED"

    # Submission
    backend_refs: dict            # {"create_payload": {...}, "sr_id": "..."}
    validation_errors: list[dict] # [{"field": str, "validation_type": str,
                                  #   "status": str, "message": str, "blocking": bool}]

    # Response
    response_message: str         # text to display to user
    response_ui: dict             # structured UI component data

    # UI-layer overrides (injected by API layer; not persisted to DB)
    action_override: str | None   # "confirm" | "cancel" | None
    corrected_fields: dict | None # inline field edits from the confirmation card

    # Runtime-only services (injected by orchestration layer; not serialized)
    trace_manager: Any            # TraceManager instance
    conversation_state_service: Any  # ConversationStateService instance
```

**Key invariants:**

- `collected_data` only contains fields that passed `merge_state_node` validation (backend-protected fields cannot be overwritten by LLM extraction).
- `extracted_fields` uses the rich shape `{field_name: {"value": str, "confidence": float}}` set by `field_extraction_node`; consumed and cleared by `merge_state_node`.
- `backend_refs.create_payload` is set only by `payload_builder_node` and is the authoritative payload POSTed to the SR API.
- `action_override` and `corrected_fields` are injected from the HTTP request body and intentionally not saved to the DB by `save_state_node`.
- `confirmation_status` uses `"REJECTED"` (not `"DENIED"`) for declined confirmations.

---

## Routing Rules

All routing is implemented as pure functions in `service_request_graph.py`. No LLM is involved in routing decisions.

**Entry-node dispatch table** (used by `_route_after_load` and `_route_after_registry`):

```python
_AGENT_ENTRY_NODES = {
    "handover_service_request_agent": "handover_entry",
    # FM/RDD are stage-routed by workflow_stage after sr_status_sync, not by active_agent key
}
```

```mermaid
flowchart TD
    START([START]) --> LS["load_session"]

    LS -->|"_user_wants_preview(msg)"| SV["supervisor"]
    LS -->|"backend_refs.sr_id exists"| SS["sr_status_sync"]
    LS -->|"active_agent set (no sr_id)"| HE["handover_entry"]
    LS -->|"no active_agent"| SV

    SS -->|"workflow_stage=FM_REVIEW"| FME["fm_review_entry"]
    SS -->|"workflow_stage=RDD_REVIEW"| RDE["rdd_review_entry"]
    SS -->|"workflow_stage=SR_CREATED/SR_COMPLETED"| SV
    SS -->|"CREATE_SR + active_agent"| HE

    SV -->|"intent=PREVIEW_SERVICE_REQUEST"| PV["preview"]
    SV -->|"WAITING_FOR_USER"| RG["response_generation"]
    SV -->|"intent classified"| REG["registry"]

    PV --> RG

    REG -->|"WAITING_FOR_USER"| RG
    REG -->|"agent resolved"| HE

    HE -->|"active_agent=None + WAITING_FOR_USER"| RG
    HE -->|"action_override=cancel"| MS["merge_state"]
    HE -->|"normal turn"| FE["field_extraction"]

    FME -->|"WAITING_FOR_USER"| RG
    FME -->|"fm_action set"| MS
    FME -->|"normal turn"| FE

    RDE -->|"WAITING_FOR_USER"| RG
    RDE -->|"rdd_action set"| MS
    RDE -->|"normal turn"| FE

    FE --> MS

    MS -->|"selected_lease set or lease_id missing"| LL["lease_lookup"]
    MS -->|"lease_id in collected_data"| VA["validation"]

    LL -->|"WAITING_FOR_USER"| RG
    LL -->|"lease resolved"| VA

    VA -->|"blocking errors"| MF["missing_field"]
    VA -->|"fields incomplete"| MF
    VA -->|"stage=FM_REVIEW + all valid"| FC["fm_confirmation"]
    VA -->|"stage=RDD_REVIEW + all valid"| RC["rdd_confirmation"]
    VA -->|"stage=CREATE_SR + all valid"| CN["confirmation"]
    VA -->|"terminal stage (SR_CREATED/SR_COMPLETED)"| RG

    MF --> RG

    CN -->|"CONFIRMED"| PB["payload_builder"]
    CN -->|"not CONFIRMED"| RG

    FC -->|"CONFIRMED"| FPB["fm_payload_builder"]
    FC -->|"not CONFIRMED"| RG

    RC -->|"CONFIRMED"| RPB["rdd_payload_builder"]
    RC -->|"not CONFIRMED"| RG

    PB --> AS["api_submission"]
    AS --> RG

    FPB --> FAS["fm_api_submission"]
    FAS --> RG

    RPB --> RAS["rdd_api_submission"]
    RAS --> RG

    RG --> SAVE["save_state"]
    SAVE --> END([END])
```

**`get_missing_fields(stage, collected_data)`** — utility that diffs `collected_data.keys()` against `stage.required_fields` and returns the list of absent keys. Used by `_route_after_validation` to decide whether all required fields are collected.

---

## Why LLM Extracts but Code Validates

This is a deliberate security and reliability boundary in the design.

**LLM responsibilities (flexible, natural language):**

- Understanding intent from free-form conversation.
- Extracting field values from user messages (dates, names, descriptions, unit codes, etc.).
- Generating natural clarifying questions when fields are missing.
- Generating confirmation and response text.

**Code responsibilities (deterministic, auditable):**

- **Validation** (`ValidationService`) — type checking, format constraints, business rules (e.g. `endDate > startDate`). These rules are too critical to delegate to an LLM that may hallucinate.
- **Routing** — all routing functions are pure Python; no LLM decides which node runs next.
- **Confirmation gating** (`handover_entry_node`) — yes/no confirmation is parsed by keyword matching (word-boundary regex against `_CONFIRM_PHRASES` / `_REJECT_PHRASES`), not LLM judgment. UI button actions (`action_override`) take priority over text parsing. This prevents a prompt-injection attack from bypassing the confirmation step.
- **Backend field protection** (`merge_state_node`) — `BACKEND_PROTECTED_FIELDS` are never overwriteable by LLM extraction output. `HandoverExtractedFields` Pydantic validator strips `BACKEND_ONLY_FIELDS` before they reach `merge_state_node`. Additionally, once `lease_id` is present (`lease_resolved = True`), the `_LEASE_CONFIRMED_FIELDS` (`lease_code`, `mall`, `brand`) become immutable.
- **Auto-generated fields** (`merge_state_node`) — `title` is auto-generated as `handover-{lease_code}-{description_slug}` once both `lease_code` and `description` are available. The bot never asks the user for `title` directly.
- **Payload construction** (`PayloadBuilderService`) — the API payload is assembled by code from `collected_data`, not generated by the LLM.
- **Submission gating** (`api_submission_node`) — hard-coded guards (`confirmation_status == "CONFIRMED"`, no blocking errors, `backend_refs.create_payload` present) run before any API call.

The pattern: **LLM provides; code decides.**
