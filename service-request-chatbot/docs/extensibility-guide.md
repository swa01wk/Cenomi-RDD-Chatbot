# Agent Extensibility Guide

## Overview

This document captures the extensibility analysis of the current architecture for adding new agents similar to the RDD Agent — including the planned FM Review and RDD Review workflow stages.

---

## Current Architecture Extensibility Summary

| Layer | Extensibility | Notes |
|---|---|---|
| Agent Registry | Excellent | One dict entry per new agent |
| Schema / StageDefinition | Excellent | FM_REVIEW and RDD_REVIEW already defined and wired |
| Validation | Good | Stage-driven; FM/RDD rules already implemented |
| Observability | Excellent | `@trace_node` decorator is fully generic |
| Database | Excellent | `collected_data` is JSONB; no new migrations needed |
| Supervisor intent routing | Moderate | Requires enum + prompt change for new intent |
| Graph topology | Good | `_AGENT_ENTRY_NODES` dispatch dict exists; add entry + wire nodes |
| Field extraction | Moderate | Tied to `HandoverExtractedFields`; needs parameterisation for new agent |
| Payload builder | Good | Pattern established (4 builders exist); add new function + node |

---

## Green Zones — What Is Already Extensible

### 1. Agent Registry

**File:** `app/agents/registries/service_request_registry.py`

The registry maps `(service_category, sub_category)` pairs to an `AgentConfig`. Adding a new agent is a single dict entry:

```python
SERVICE_REQUEST_AGENT_REGISTRY = {
    "FIT_OUT_AND_HANDOVER": {
        "HANDOVER": {
            "agent_name": "rdd_agent",
            "display_name": "RDD Agent",
            "schema_key": "handover_service_request_schema",
        },
        # Add new entries here, e.g.:
        # "FM_REVIEW": {
        #     "agent_name": "fm_review_agent",
        #     "display_name": "FM Review Agent",
        #     "schema_key": "fm_review_schema",
        # },
    },
}
```

### 2. StageDefinition / STAGE_REGISTRY Pattern

**File:** `app/agents/schemas/handover_schema.py`

`FM_REVIEW_STAGE` and `RDD_REVIEW_STAGE` are already fully defined. All stage-aware helpers (`get_missing_fields`, `get_required_fields`, `get_required_documents`) automatically work for any registered stage:

```python
STAGE_REGISTRY: dict[str, StageDefinition] = {
    "CREATE_SR":  CREATE_SR_STAGE,
    "FM_REVIEW":  FM_REVIEW_STAGE,   # schema complete; nodes not yet wired
    "RDD_REVIEW": RDD_REVIEW_STAGE,  # schema complete; nodes not yet wired
}
```

For a genuinely new agent domain, create a new schema module following the same `StageDefinition` + `STAGE_REGISTRY` pattern.

### 3. Database Schema

`service_request_drafts.collected_data` is `jsonb` — new agents store their domain data in this same column with no migration needed. `active_agent` and `workflow_stage` are free strings.

### 4. Observability Infrastructure

The `@trace_node(run_name, run_type)` decorator is fully generic. Any new node gets automatic `AgentRun` tracing, state snapshots, diffs, and LLM call records with zero extra code.

### 5. State Design

`ServiceRequestGraphState` uses `TypedDict, total=False` — all keys are optional. New agents use the existing `collected_data: dict` to store their form data without extending the state type.

---

## Friction Points — What Requires Code Changes

### 1. Supervisor Intent Is a Closed Literal Enum

**File:** `app/agents/schemas/supervisor_schema.py`

```python
intent: Literal[
    "CREATE_RDD_SERVICE_REQUEST",
    "UPDATE_RDD_SERVICE_REQUEST",
    "APPROVE_RDD_SERVICE_REQUEST",
    "CHECK_SERVICE_REQUEST_STATUS",
    "PREVIEW_SERVICE_REQUEST",
    "UNKNOWN",
]
```

**Required change:** Add the new intent value to the `Literal` and update the supervisor system prompt in `app/agents/prompts/supervisor_prompt.py`.

### 2. Graph Routing — `_AGENT_ENTRY_NODES` dispatch table ✅ Already implemented

**File:** `app/agents/graph/service_request_graph.py`

The dispatch dict exists in the codebase:

```python
_AGENT_ENTRY_NODES: dict[str, str] = {
    "rdd_agent": "handover_entry",
    # FM/RDD are stage-routed by workflow_stage after sr_status_sync
}
```

**Required change for new agent type:** Add a new entry to `_AGENT_ENTRY_NODES` and wire the entry node into the graph.

### 3. `_route_after_validation` Imports Directly from `handover_schema`

```python
from app.agents.schemas.handover_schema import get_missing_fields  # local import
stage = state.get("workflow_stage") or "CREATE_SR"
```

**Required change:** Replace the direct import with a schema resolver that dispatches to the correct `get_missing_fields` based on `state["schema_key"]` or `state["active_agent"]`:

```python
def _resolve_get_missing_fields(schema_key: str):
    if schema_key == "handover_service_request_schema":
        from app.agents.schemas.handover_schema import get_missing_fields
    elif schema_key == "new_agent_schema":
        from app.agents.schemas.new_agent_schema import get_missing_fields
    return get_missing_fields
```

### 4. `FieldExtractionService` Is Tied to `HandoverExtractedFields`

**File:** `app/agents/services/field_extraction_service.py`

The service hardcodes `HandoverExtractedFields` and `HANDOVER_EXTRACTION_SYSTEM_PROMPT`.

**Required change:** Either make the service accept the schema class and prompt as constructor parameters, or have `field_extraction_node` dispatch to a different service class based on `state["schema_key"]`.

### 5. `payload_builder_node` — Stage-specific builders already exist ✅ Already implemented

**File:** `app/agents/services/payload_builder_service.py`

Four builders now exist: `build_create_handover_payload`, `build_fm_review_payload`, `build_fm_approve_payload`, `build_rdd_report_payload`. Each has its own dedicated graph node (`payload_builder_node`, `fm_payload_builder_node`, `rdd_payload_builder_node`).

**Required change for new agent type:** Add a new `build_{new_agent}_payload` function and a corresponding dedicated node wired into the graph.

---

## Extension Paths

### Path A — FM Review and RDD Review Stages ✅ Already implemented

These lifecycle stages of the Handover SR are fully wired in the graph. The following are already complete:

1. ✅ **Entry nodes** — `fm_review_entry_node.py` and `rdd_review_entry_node.py`
2. ✅ **Graph routing** — `sr_status_sync_node` maps platform `service_request_operations` to `workflow_stage`; `_route_after_sync` dispatches to `fm_review_entry` / `rdd_review_entry`
3. ✅ **Payload builders** — `build_fm_review_payload`, `build_fm_approve_payload`, `build_rdd_report_payload` in `payload_builder_service.py`
4. ✅ **Stage-specific confirmation nodes** — `fm_confirmation`, `rdd_confirmation`
5. ✅ **Stage-specific submission nodes** — `fm_api_submission_node`, `rdd_api_submission_node`

**Still pending (what the incoming developer needs to complete):**
- Real file upload wired to platform `PUT /files` (upload route is still a stub)
- Status sync mapping needs validation against live platform `service_request_operations` shapes
- Frontend document upload UI for FM checklist / RDD report (`DocumentRequirementCard` exists but upload flow is partial)
- Structured UI actions beyond generic `confirm`/`cancel` (e.g. `save_fm_progress`, `approve_fm_review`, `submit_rdd_report`)

See `gaps_and_pc/chatbot_postman_gap_implementation_plan.md` for the full gap closure checklist.

### Path B — New Agent Type (Different Service Category)

For a truly new domain (e.g., `MAINTENANCE_REQUEST`, `LEASE_RENEWAL`):

1. **Registry** — add `(service_category, sub_category)` entry to `SERVICE_REQUEST_AGENT_REGISTRY`.
2. **Schema module** — create `app/agents/schemas/{new_agent}_schema.py` with a `StageDefinition`, `STAGE_REGISTRY`, `EXTRACTABLE_FIELDS`, `BACKEND_ONLY_FIELDS`, `get_missing_fields()`.
3. **Extraction schema + prompt** — create `{NewAgent}ExtractedFields` Pydantic model and a system prompt in `app/agents/prompts/`.
4. **Entry node** — create `{new_agent}_entry_node.py`.
5. **Supervisor intent** — add intent literal to `SupervisorDecision` and update supervisor prompt.
6. **Graph routing** — extend `_AGENT_ENTRY_NODES` dispatch dict and wire new nodes into the graph.
7. **Payload builder** — implement `build_{new_agent}_payload`.
8. **Validation rules** — add any domain-specific rules to `ValidationService`.

Effort estimate: **large** — but the infrastructure (observability, DB, state, injection guard, orchestration) requires zero changes.

---

## Design Principle: LLM Provides; Code Decides

All new agents must follow this boundary — it is the core security and reliability contract of the system:

| LLM Responsibility | Code Responsibility |
|---|---|
| Intent classification | Routing (pure functions, no LLM) |
| Field value extraction from free text | Validation — type, format, business rules |
| Natural clarifying questions | Confirmation gating — keyword matching + UI button override |
| Response and confirmation text | Backend field protection (`BACKEND_PROTECTED_FIELDS`) |
| | Payload construction (never LLM-generated) |
| | Submission gating (hard-coded guards before any API call) |

Deviating from this boundary — for example, letting the LLM make routing decisions or construct API payloads — introduces hallucination and prompt-injection risk into critical paths.

---

## Files to Touch When Adding a New Agent

| File | Change |
|---|---|
| `app/agents/registries/service_request_registry.py` | Add registry entry |
| `app/agents/schemas/supervisor_schema.py` | Add intent to `Literal` |
| `app/agents/prompts/supervisor_prompt.py` | Document new intent for LLM |
| `app/agents/schemas/{new_agent}_schema.py` | **New file** — StageDefinition, ExtractedFields |
| `app/agents/prompts/{new_agent}_extraction_prompt.py` | **New file** — extraction system prompt |
| `app/agents/graph/nodes/{new_agent}_entry_node.py` | **New file** — entry / confirmation node |
| `app/agents/services/payload_builder_service.py` | Add new payload builder function |
| `app/agents/services/validation_service.py` | Add domain-specific validation rules |
| `app/agents/graph/service_request_graph.py` | Add nodes, edges, routing dispatch |

Files that do **not** need changes: `state.py`, all observability/trace files, `ChatOrchestrationService`, `ConversationStateService`, `injection_guard`, all DB repositories, all frontend observability components.
