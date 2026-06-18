# Plan 04 — Extensible Agent System Design

**Scope:** Evolve the agent system from a hardcoded single-workflow implementation to a schema-driven, registry-backed architecture where new workflows (Operations Confirmation, Maintenance, Lease Renewal, etc.) are declared as data, not code.  
**Depends on:** Plans 01–03 completed (RDD lifecycle E2E working as baseline).  
**Target:** Sprint 2 — after the first new workflow is ready to be onboarded.

---

## The Problem This Plan Solves

After Plans 01–03, the system works end-to-end for `FIT_OUT_AND_HANDOVER / HANDOVER`. But adding a second workflow today requires duplicating:
- A new schema file (like `handover_schema.py`)
- New entry nodes (like `fm_review_entry_node.py`)
- New payload builders (like `fm_payload_builder_node.py`)
- New API submission nodes
- New supervisor intents
- New graph edges

This is unsustainable. The goal of Plan 04 is to make **adding a new workflow = one Python declaration**.

---

## The Four Dimensions of Any Workflow

Every workflow in the Cenomi platform — Handover, Operations Confirmation, Maintenance — can be fully described per stage by four dimensions:

```
1. DATA       required_fields, auto_computed_fields
2. ROLES      allowed_roles, required_permissions
3. APPROVALS  valid_actions (save_progress, approve, submit, final_approve)
4. API        api_method (POST/PATCH), api_status_on_submit
```

Once a stage declares these four dimensions, generic nodes can drive the entire conversation without per-workflow code.

---

## Task 4.1 — Enrich `StageDefinition` with All Four Dimensions

**File:** `backend/app/agents/schemas/handover_schema.py` → refactor to `workflow_schema.py`

```python
@dataclass(frozen=True)
class StageDefinition:
    stage: str

    # Dimension 1: Data
    required_fields: tuple[str, ...]
    required_documents: tuple[str, ...] = ()
    auto_computed_fields: tuple[str, ...] = ()   # derived by code, never asked from user

    # Dimension 2: Roles
    allowed_roles: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()

    # Dimension 3: Approvals
    valid_actions: tuple[str, ...] = ()          # action_override values

    # Dimension 4: API
    api_method: str = "POST"                      # POST | PATCH
    api_status_on_submit: str = ""               # e.g. APPROVED, REPORT_SUBMITTED
    api_status_on_secondary: str = ""            # for stages with 2 API calls (e.g. APPROVED after REPORT_SUBMITTED)
```

**RDD Handover as a `WorkflowDefinition`:**

```python
@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    service_category: str
    sub_category: str
    display_name: str
    description: str
    agent_name: str
    entry_stage: str
    stages: tuple[StageDefinition, ...]
    stakeholders: tuple[str, ...]           # all roles across all stages

    def get_stage(self, stage_name: str) -> StageDefinition | None:
        return next((s for s in self.stages if s.stage == stage_name), None)

    def stage_for_role(self, role: str) -> StageDefinition | None:
        return next((s for s in self.stages if role in s.allowed_roles), None)


HANDOVER_WORKFLOW = WorkflowDefinition(
    workflow_id="handover_service_request",
    service_category="FIT_OUT_AND_HANDOVER",
    sub_category="HANDOVER",
    display_name="Handover Service Request",
    description="Unit handover from landlord to tenant after lease activation",
    agent_name="handover_service_request_agent",
    entry_stage="CREATE_SR",
    stakeholders=("MALL_MANAGER", "FM_MANAGER", "OPERATIONS", "DD_ENGINEER"),
    stages=(
        StageDefinition(
            stage="CREATE_SR",
            allowed_roles=("MALL_MANAGER",),
            required_permissions=("CAN_RAISE_HANDOVER_SR",),
            required_fields=("description", "startDate", "endDate", "inspection_done_by", "comments"),
            valid_actions=("confirm", "cancel"),
            api_method="POST",
            api_status_on_submit="IN_PROCESS",
        ),
        StageDefinition(
            stage="FM_REVIEW",
            allowed_roles=("FM_MANAGER", "OPERATIONS"),
            required_permissions=("CAN_FM_REVIEW_HANDOVER_SR",),
            required_fields=("unit_readiness_date",),
            auto_computed_fields=("expected_handover_date",),
            required_documents=("SR_HANDOVER_CHECKLIST", "SR_HANDOVER_SITE_SURVEY", "SR_COP_CHECKLIST_OTHER"),
            valid_actions=("save_fm_progress", "approve_fm_review"),
            api_method="PATCH",
            api_status_on_submit="APPROVED",
        ),
        StageDefinition(
            stage="RDD_REVIEW",
            allowed_roles=("DD_ENGINEER",),
            required_permissions=("CAN_RDD_REVIEW_HANDOVER_SR",),
            required_fields=("guideLineLink", "actual_handover_date", "fitout_start_date", "fitout_end_date", "trading_date"),
            required_documents=("DR_SR_HANDOVER_REPORT",),
            valid_actions=("submit_rdd_report", "approve_rdd_final"),
            api_method="POST",
            api_status_on_submit="REPORT_SUBMITTED",
            api_status_on_secondary="APPROVED",
        ),
    ),
)
```

---

## Task 4.2 — `WorkflowDefinitionRegistry`

**File:** `backend/app/agents/registries/workflow_definition_registry.py` (new, replaces `service_request_registry.py`)

```python
WORKFLOW_DEFINITION_REGISTRY: dict[str, dict[str, WorkflowDefinition]] = {
    "FIT_OUT_AND_HANDOVER": {
        "HANDOVER": HANDOVER_WORKFLOW,
        # Future: "OPERATIONS_CONFIRMATION": OPERATIONS_CONFIRMATION_WORKFLOW,
    },
    # Future:
    # "MAINTENANCE": { "GENERAL": MAINTENANCE_WORKFLOW },
    # "LEASE": { "RENEWAL": LEASE_RENEWAL_WORKFLOW },
}

def lookup_workflow(service_category: str, sub_category: str) -> WorkflowDefinition | None:
    return (
        WORKFLOW_DEFINITION_REGISTRY
        .get(service_category, {})
        .get(sub_category)
    )

def all_workflows() -> list[WorkflowDefinition]:
    return [
        wf
        for sub in WORKFLOW_DEFINITION_REGISTRY.values()
        for wf in sub.values()
    ]
```

**Adding a new workflow = one `WorkflowDefinition` declaration + one registry entry.**

---

## Task 4.3 — Generic Stage Entry Node

**File:** `backend/app/agents/graph/nodes/generic_stage_entry_node.py` (new)

Replaces `fm_review_entry_node.py` and `rdd_review_entry_node.py`. Reads from `WorkflowDefinition` at runtime:

```python
async def generic_stage_entry_node(state) -> dict:
    """Universal stage entry node — driven by WorkflowDefinitionRegistry."""
    # Resolve workflow + stage definition
    service_category = state.get("service_category", "FIT_OUT_AND_HANDOVER")
    sub_category = state.get("sub_category", "HANDOVER")
    workflow_stage = state.get("workflow_stage", "")

    workflow_def = lookup_workflow(service_category, sub_category)
    stage_def = workflow_def.get_stage(workflow_stage) if workflow_def else None

    if not stage_def:
        return {"status": "WAITING_FOR_USER", "response_message": "Unknown workflow stage."}

    backend_refs = dict(state.get("backend_refs") or {})
    user_role = state.get("user_role") or backend_refs.get("user_role")
    action_override = state.get("action_override")

    # Generic role guard — reads allowed_roles from stage_def
    if user_role and user_role not in stage_def.allowed_roles:
        return {
            "status": "WAITING_FOR_USER",
            "response_message": f"This stage requires role: {', '.join(stage_def.allowed_roles)}.",
        }

    # Generic action dispatch — reads valid_actions from stage_def
    if action_override and action_override in stage_def.valid_actions:
        stage_key = workflow_stage.lower()
        backend_refs[f"{stage_key}_action"] = action_override
        return {"backend_refs": backend_refs}

    if action_override == "cancel_update":
        return {"status": "WAITING_FOR_USER", "response_message": "Update cancelled."}

    if action_override == "upload_document":
        return {"status": "WAITING_FOR_USER", "response_message": "Use the upload panel to attach documents."}

    # Fall through to field_extraction
    return {}
```

---

## Task 4.4 — Generic Payload Builder Node

**File:** `backend/app/agents/graph/nodes/generic_payload_builder_node.py` (new)

Replaces `fm_payload_builder_node.py` and `rdd_payload_builder_node.py`:

```python
async def generic_payload_builder_node(state) -> dict:
    """Build submission payload from collected_data using stage definition."""
    workflow_stage = state.get("workflow_stage", "")
    stage_def = _resolve_stage_def(state)
    backend_refs = dict(state.get("backend_refs") or {})
    collected_data = state.get("collected_data") or {}

    stage_action_key = f"{workflow_stage.lower()}_action"
    action = backend_refs.get(stage_action_key, "")

    # Determine API method from stage_def
    if action == "final_approve" and stage_def.api_status_on_secondary:
        payload = build_stage_approve_payload(backend_refs, stage_def)
    elif stage_def.api_method == "PATCH":
        payload = build_stage_patch_payload(collected_data, backend_refs, stage_def, action)
    else:
        payload = build_stage_post_payload(collected_data, backend_refs, stage_def)

    payload_key = f"{workflow_stage.lower()}_payload"
    backend_refs[payload_key] = payload
    return {"backend_refs": backend_refs}
```

---

## Task 4.5 — Generic API Submission Node

**File:** `backend/app/agents/graph/nodes/generic_api_submission_node.py` (new)

```python
async def generic_api_submission_node(state) -> dict:
    """Submit to platform API using stage definition."""
    stage_def = _resolve_stage_def(state)
    backend_refs = dict(state.get("backend_refs") or {})
    workflow_stage = state.get("workflow_stage", "")
    payload_key = f"{workflow_stage.lower()}_payload"
    payload = backend_refs.get(payload_key)
    action = backend_refs.get(f"{workflow_stage.lower()}_action", "")

    svc = get_service_request_api_service()

    if action == "final_approve" and stage_def.api_status_on_secondary:
        result = await svc.patch_service_request(backend_refs["sr_id"], payload)
    elif stage_def.api_method == "PATCH":
        result = await svc.patch_service_request(backend_refs["sr_id"], payload)
    else:
        result = await svc.submit_report(payload) if stage_def.api_status_on_submit == "REPORT_SUBMITTED" \
               else await svc.create_service_request(payload)

    # Generic success/failure handling...
```

---

## Task 4.6 — Dynamic Supervisor Prompt

**File:** `backend/app/agents/prompts/supervisor_prompt.py`

Replace static `SUPERVISOR_SYSTEM_PROMPT` with a builder function:

```python
def build_supervisor_prompt() -> str:
    """Generate supervisor prompt dynamically from WorkflowDefinitionRegistry."""
    workflow_context = "\n".join([
        f"  - {wf.service_category}/{wf.sub_category}: {wf.display_name}\n"
        f"    Stages: {' → '.join(s.stage for s in wf.stages)}\n"
        f"    Stakeholders: {', '.join(wf.stakeholders)}"
        for wf in all_workflows()
    ])
    return SUPERVISOR_PROMPT_TEMPLATE.format(registered_workflows=workflow_context)
```

`SUPERVISOR_PROMPT_TEMPLATE` is the existing prompt with a `{registered_workflows}` placeholder added in the routing rules section. When a new workflow is registered, the supervisor automatically knows about it.

---

## Task 4.7 — Evolved Supervisor Decision Schema

**File:** `backend/app/agents/schemas/supervisor_schema.py`

Evolve `SupervisorDecision` to a generalised two-level classifier:

```python
class SupervisorDecision(BaseModel):
    # Level 1: workflow identification (resolved via registry)
    service_category: str | None       # already exists ✓
    sub_category: str | None           # already exists ✓

    # Level 2: generalised action (workflow-agnostic)
    action_intent: Literal[
        "CREATE",           # start a new SR (any workflow)
        "APPROVE",          # approve/submit at current stage (any workflow)
        "UPDATE",           # modify existing SR
        "CHECK_STATUS",
        "PREVIEW",
        "UNKNOWN",
    ]

    # Legacy compat — keep intent for backward compatibility during transition
    intent: str | None = None

    target_agent: str | None           # resolved from registry, not LLM-generated
    confidence: float
    reasoning: str
```

`action_intent` replaces the hardcoded `CREATE_HANDOVER_SERVICE_REQUEST` strings. The supervisor now classifies **what workflow** (via `service_category/sub_category`) and **what action** (via `action_intent`) — not a workflow-specific intent string.

---

## Task 4.8 — Dynamic Graph Registration

For a fully generic system, the graph can register stage nodes dynamically from the registry instead of hardcoded `add_node` calls. This is a longer-term change:

```python
def build_service_request_graph():
    graph = StateGraph(ServiceRequestGraphState)

    # Register shared/generic nodes
    graph.add_node("load_session", load_session_node)
    graph.add_node("sr_status_sync", sr_status_sync_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("field_extraction", field_extraction_node)
    graph.add_node("merge_state", merge_state_node)
    graph.add_node("lease_lookup", lease_lookup_node)
    graph.add_node("validation", validation_node)
    graph.add_node("missing_field", missing_field_node)
    graph.add_node("confirmation", confirmation_node)
    graph.add_node("document_upload", document_upload_node)
    graph.add_node("generic_stage_entry", generic_stage_entry_node)
    graph.add_node("generic_payload_builder", generic_payload_builder_node)
    graph.add_node("generic_api_submission", generic_api_submission_node)
    graph.add_node("response_generation", response_generation_node)
    graph.add_node("save_state", save_state_node)

    # Routing is still pure Python — driven by workflow_stage + WorkflowDefinitionRegistry
    ...
```

---

## Sprint Roadmap

```
Sprint 1 (Plans 01–03): Complete RDD lifecycle E2E — hardcoded implementation
  Introduces: WorkflowDefinition data structure, ROLE_PERMISSION_MAP, document_upload_node

Sprint 2 (this plan, partial):
  - Enrich StageDefinition with all 4 dimensions (Task 4.1)
  - WorkflowDefinitionRegistry (Task 4.2)
  - generic_stage_entry_node (Task 4.3) — replaces fm_review_entry + rdd_review_entry
  - Dynamic supervisor prompt (Task 4.6) + evolved SupervisorDecision (Task 4.7)
  - Register second workflow (Operations Confirmation) — validates zero new node code

Sprint 3:
  - generic_payload_builder_node (Task 4.4)
  - generic_api_submission_node (Task 4.5)
  - Dynamic graph registration (Task 4.8)
  - Third workflow onboarding
```

---

## How Sprint 1 Already Lays the Foundation

Every Sprint 1 (Plans 01–03) change is designed as a step toward this generic architecture:

| Sprint 1 change | Foundation it lays |
|---|---|
| `ROLE_PERMISSION_MAP` in `PermissionService` | Central role → permission store used by `generic_stage_entry_node` |
| `user_role` in `GraphState` + `backend_refs` | Role context available generically to all nodes |
| `document_upload_node` shared by FM + RDD | First proof of one generic node serving multiple stages |
| `expected_handover_date` → `auto_computed_fields` pattern | Pattern for computed fields in `StageDefinition` |
| `approve_rdd_final` in `valid_actions` | Models the `valid_actions` tuple on `StageDefinition` |
| Dynamic supervisor prompt with role context | Foundation for registry-driven prompt generation |

---

## Done When (Sprint 2 Milestone)

- `HANDOVER_WORKFLOW` `WorkflowDefinition` declared and used as single source of truth
- `fm_review_entry_node.py` and `rdd_review_entry_node.py` replaced by `generic_stage_entry_node.py`
- A second workflow (`OPERATIONS_CONFIRMATION`) registered in `WORKFLOW_DEFINITION_REGISTRY` with zero new node files
- Supervisor prompt dynamically generated from registry — new workflow appears in supervisor context automatically
- All existing RDD lifecycle E2E tests still pass
