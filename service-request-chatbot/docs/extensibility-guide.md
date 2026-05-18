# Agent Extensibility Guide

## Overview

This document captures the extensibility analysis of the current architecture for adding new agents similar to the Handover Service Request Agent — including the planned FM Review and RDD Review workflow stages.

---

## Current Architecture Extensibility Summary

| Layer | Extensibility | Notes |
|---|---|---|
| Agent Registry | Excellent | One dict entry per new agent |
| Schema / StageDefinition | Excellent | FM_REVIEW and RDD_REVIEW already defined |
| Validation | Good | Stage-driven; FM/RDD rules already implemented |
| Observability | Excellent | `@trace_node` decorator is fully generic |
| Database | Excellent | `collected_data` is JSONB; no new migrations needed |
| Supervisor intent routing | Moderate | Requires enum + prompt change |
| Graph topology | Moderate | Routing functions hardcode `handover_entry` |
| Field extraction | Moderate | Tied to `HandoverExtractedFields`; needs parameterization |
| Payload builder | Moderate | One builder per agent type needed |

---

## Green Zones — What Is Already Extensible

### 1. Agent Registry

**File:** `app/agents/registries/service_request_registry.py`

The registry maps `(service_category, sub_category)` pairs to an `AgentConfig`. Adding a new agent is a single dict entry:

```python
SERVICE_REQUEST_AGENT_REGISTRY = {
    "FIT_OUT_AND_HANDOVER": {
        "HANDOVER": {
            "agent_name": "handover_service_request_agent",
            "display_name": "Handover Service Request Agent",
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
    "CREATE_HANDOVER_SERVICE_REQUEST",
    "UPDATE_HANDOVER_SERVICE_REQUEST",
    "APPROVE_HANDOVER_SERVICE_REQUEST",
    "CHECK_SERVICE_REQUEST_STATUS",
    "UNKNOWN",
]
```

**Required change:** Add the new intent value to the `Literal` and update the supervisor system prompt in `app/agents/prompts/supervisor_prompt.py`.

### 2. Graph Routing Hardcodes `handover_entry`

**File:** `app/agents/graph/service_request_graph.py`

```python
def _route_after_load(state):
    return "handover_entry" if state.get("active_agent") else "supervisor"

def _route_after_registry(state):
    ...
    return "handover_entry"
```

**Required change:** Make routing dynamic, dispatching to the appropriate entry node based on `active_agent`:

```python
_AGENT_ENTRY_NODES = {
    "handover_service_request_agent": "handover_entry",
    "fm_review_agent": "fm_review_entry",
    # add new mappings here
}

def _route_after_load(state):
    agent = state.get("active_agent")
    return _AGENT_ENTRY_NODES.get(agent, "supervisor") if agent else "supervisor"
```

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
    elif schema_key == "fm_review_schema":
        from app.agents.schemas.fm_review_schema import get_missing_fields
    return get_missing_fields
```

### 4. `FieldExtractionService` Is Tied to `HandoverExtractedFields`

**File:** `app/agents/services/field_extraction_service.py`

The service hardcodes `HandoverExtractedFields` and `HANDOVER_EXTRACTION_SYSTEM_PROMPT`.

**Required change:** Either make the service accept the schema class and prompt as constructor parameters, or have `field_extraction_node` dispatch to a different service class based on `state["schema_key"]`.

### 5. `payload_builder_node` Is Handover-Specific

**File:** `app/agents/graph/nodes/payload_builder_node.py`

Calls `build_create_handover_payload` directly.

**Required change:** Add a payload builder registry or dispatch based on `active_agent`/`workflow_stage`.

---

## Extension Paths

### Path A — FM Review and RDD Review Stages (Same Handover Agent)

These are lifecycle stages of the same Handover SR, not new agent types. The schema, validation rules, and document types are already defined. Steps to complete:

1. **Add entry nodes** — `fm_review_entry_node.py` and `rdd_review_entry_node.py` (modelled on `handover_entry_node.py`).
2. **Add graph edges** — from `workflow_stage = "SR_CREATED"` to the FM review pipeline after `api_submission_node`. Extend `_route_after_load` to route `workflow_stage = "FM_REVIEW"` / `"RDD_REVIEW"` to the correct entry node.
3. **Add payload builders** — `build_fm_review_payload` and `build_rdd_review_payload` in `payload_builder_service.py`.
4. **Webhook / status-poll trigger** — mechanism to transition the session's `workflow_stage` from `"SR_CREATED"` to `"FM_REVIEW"` when the SR advances in the external system.
5. **Frontend components** — document upload UI for FM checklist / RDD report.

Effort estimate: **medium** — schema and validation are done; graph wiring + 2 entry nodes + 2 payload builders are the main work.

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
