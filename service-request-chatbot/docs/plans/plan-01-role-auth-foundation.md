# Plan 01 — Role & Auth Foundation

**Scope:** Wire the user's role through the entire stack so that permission guards, proactive routing, LLM context, and response personas all work correctly.  
**Depends on:** Nothing — this is the foundational plan that all other plans build on.  
**Blocks:** Plan 02 (FM/RDD permission enforcement), Plan 03 (frontend role selector sends `user_role`).

---

## Why This Plan Exists

Every permission check in the FM and RDD nodes is currently **silently bypassed** because `user_role` is never passed from the frontend and `auth.roles` is always empty. The chatbot gives the same generic response regardless of who is talking to it.

Current broken chain:
```
Frontend (no user_role field)
  → chat.py (no user_role in request model)
    → ChatOrchestrationService (never sets user_role in graph state)
      → GraphState (no user_role field)
        → fm_review_entry_node (reads backend_refs["user_role"] → always None → guard bypassed)
        → fm_api_submission_node (reads state["auth"] → always None → permission check bypassed)
        → response_generation_node (no role context → generic response)
```

---

## Task 1.1 — Add `user_role` to Request Model

**File:** `backend/app/api/routes/chat.py`

Add to `ServiceRequestChatRequest`:
```python
user_role: str | None = Field(
    default=None,
    description="Caller's workflow role. Valid: MALL_MANAGER | FM_MANAGER | OPERATIONS | DD_ENGINEER",
    examples=["FM_MANAGER", "DD_ENGINEER"],
)
```

Pass it through to `service.process_turn(... user_role=body.user_role)`.

---

## Task 1.2 — Add `user_role` and `auth` to Graph State

**File:** `backend/app/agents/graph/state.py`

Add two new fields to `ServiceRequestGraphState`:
```python
user_role: Optional[str]   # MALL_MANAGER | FM_MANAGER | OPERATIONS | DD_ENGINEER
auth: Any                  # AuthContext instance — injected by orchestration layer
```

These are runtime-injected (like `trace_manager`) and survive across graph nodes within a turn.

---

## Task 1.3 — Add `ROLE_PERMISSION_MAP` to PermissionService

**File:** `backend/app/agents/services/permission_service.py`

Add a role → permission set mapping used to derive `AuthContext.roles`:
```python
ROLE_PERMISSION_MAP: dict[str, frozenset[str]] = {
    "MALL_MANAGER": frozenset({
        "CAN_RAISE_HANDOVER_SR",
        "VIEW_FIT_OUT_HANDOVER",
    }),
    "FM_MANAGER": frozenset({
        "CAN_FM_REVIEW_HANDOVER_SR",
        "CAN_APPROVE_FM_HANDOVER_SR",
        "VIEW_FIT_OUT_HANDOVER",
        "VIEW_FIT_OUT_HANDOVER_INSPECTION",
    }),
    "OPERATIONS": frozenset({
        "CAN_FM_REVIEW_HANDOVER_SR",
        "CAN_APPROVE_FM_HANDOVER_SR",
        "VIEW_FIT_OUT_HANDOVER",
        "VIEW_FIT_OUT_HANDOVER_INSPECTION",
    }),
    "DD_ENGINEER": frozenset({
        "CAN_RDD_REVIEW_HANDOVER_SR",
        "VIEW_FIT_OUT_HANDOVER",
        "VIEW_FIT_OUT_HANDOVER_INSPECTION",
    }),
}
```

Also add the missing RDD final approval action:
```python
"APPROVE_RDD_FINAL": "CAN_RDD_REVIEW_HANDOVER_SR",
```

---

## Task 1.4 — Inject Role into Graph State via ChatOrchestrationService

**File:** `backend/app/services/chat_orchestration_service.py`

When building `initial_state` for the graph, derive `AuthContext` from `user_role` using `ROLE_PERMISSION_MAP`:

```python
from app.agents.services.permission_service import ROLE_PERMISSION_MAP
from app.types.chat import AuthContext

def _build_auth_context(user_role: str | None) -> AuthContext:
    roles = ROLE_PERMISSION_MAP.get(user_role or "", frozenset())
    return AuthContext(subject_id="chat_user", tenant_id=None, roles=roles)

# In process_turn / build initial_state:
auth_ctx = _build_auth_context(user_role)
initial_state["user_role"] = user_role
initial_state["auth"] = auth_ctx
# Also write to backend_refs so stage entry nodes can read it
# (they already read backend_refs["user_role"] — see fm_review_entry_node.py)
initial_state.setdefault("backend_refs", {})["user_role"] = user_role
```

`user_role` in `backend_refs` is already persisted to `service_request_drafts` via `ConversationStateService`, so the role survives across turns.

---

## Task 1.5 — Role-Aware Supervisor Context

**File:** `backend/app/agents/prompts/supervisor_prompt.py`

Add a role guidance section to `SUPERVISOR_SYSTEM_PROMPT`:

```
════════════════════════════════════════════════════════════
CALLER ROLE GUIDANCE
════════════════════════════════════════════════════════════

When "Current user role" is provided, use it to sharpen classification:

  MALL_MANAGER
    Primary intent: CREATE_HANDOVER_SERVICE_REQUEST
    They raise new SRs when a lease is activated.

  FM_MANAGER | OPERATIONS
    Primary intent: APPROVE_HANDOVER_SERVICE_REQUEST (FM stage)
    "approve", "save progress", "inspection done", "submit documents"
    → APPROVE_HANDOVER_SERVICE_REQUEST

  DD_ENGINEER
    Primary intent: APPROVE_HANDOVER_SERVICE_REQUEST (RDD stage)
    "submit report", "final approve", "handover meeting done"
    → APPROVE_HANDOVER_SERVICE_REQUEST
```

**File:** `backend/app/agents/graph/nodes/supervisor_node.py`

Extend the user content string injected into the LLM call to include `user_role`:
```python
user_role = state.get("user_role") or (state.get("backend_refs") or {}).get("user_role")
if user_role:
    context_parts.append(f"Current user role: {user_role}")
```

---

## Task 1.6 — Proactive Stage Routing (Skip Supervisor for FM/RDD)

**File:** `backend/app/agents/graph/service_request_graph.py`

Extend `_route_after_sync` to use role for proactive routing — when the role matches the current stage, skip the supervisor entirely:

```python
def _route_after_sync(state: dict[str, Any]) -> str:
    workflow_stage = state.get("workflow_stage") or "CREATE_SR"
    user_role = state.get("user_role") or (state.get("backend_refs") or {}).get("user_role")

    # Proactive routing: skip supervisor when role matches stage
    if workflow_stage == "FM_REVIEW" and user_role in ("FM_MANAGER", "OPERATIONS"):
        return "fm_review_entry"
    if workflow_stage == "RDD_REVIEW" and user_role == "DD_ENGINEER":
        return "rdd_review_entry"

    # Terminal stages and fallbacks (existing logic)
    if workflow_stage in ("SR_CREATED", "SR_COMPLETED"):
        return "supervisor"
    if workflow_stage == "FM_REVIEW":
        return "fm_review_entry"
    if workflow_stage == "RDD_REVIEW":
        return "rdd_review_entry"
    agent = state.get("active_agent")
    if agent:
        return _AGENT_ENTRY_NODES.get(agent, "handover_entry")
    return "supervisor"
```

---

## Task 1.7 — Role-Aware Response Generation

**File:** `backend/app/agents/prompts/response_generation_prompt.py`

Add a `ROLE_PERSONA_CONTEXT` dict and a helper that injects the right persona block based on `user_role` + `workflow_stage`:

```python
ROLE_PERSONA_CONTEXT = {
    ("MALL_MANAGER", "CREATE_SR"): """
You are assisting a Mall Manager to create a Handover Service Request.
Use language around: tenant, lease, unit, inspection period, FM assignment.
Guide them step-by-step: description → inspection dates → inspector choice.
""",
    ("FM_MANAGER", "FM_REVIEW"): """
You are assisting an FM Manager with the site inspection review.
Use language around: site inspection, unit readiness, checklist, survey, COP.
Guide them to: upload 3 documents → set unit readiness date → save or approve.
Mention the expected handover date is auto-calculated (readiness + 7 days).
""",
    ("OPERATIONS", "FM_REVIEW"): """  # same as FM_MANAGER """,
    ("DD_ENGINEER", "RDD_REVIEW"): """
You are assisting an RDD Project Manager with the handover meeting review.
Use language around: handover meeting, contractual dates, fit-out, trading date, guidelines.
Guide them to: upload report → provide guidelines link → enter 4 dates → submit → final approve.
Dates must be in order: actual_handover ≤ fitout_start ≤ fitout_end ≤ trading_date.
""",
}
```

**File:** `backend/app/agents/graph/nodes/response_generation_node.py`

Inject the persona context into the LLM prompt build:
```python
user_role = state.get("user_role") or (state.get("backend_refs") or {}).get("user_role")
workflow_stage = state.get("workflow_stage")
persona = ROLE_PERSONA_CONTEXT.get((user_role, workflow_stage), "")
# Prepend persona to system context
```

---

## Files Changed

| File | Change |
|---|---|
| `api/routes/chat.py` | Add `user_role: str | None` to `ServiceRequestChatRequest` |
| `agents/graph/state.py` | Add `user_role: Optional[str]` and `auth: Any` fields |
| `services/chat_orchestration_service.py` | Build `AuthContext` from `ROLE_PERMISSION_MAP`; inject `user_role` + `auth` into initial state and `backend_refs` |
| `agents/services/permission_service.py` | Add `ROLE_PERMISSION_MAP`; add `APPROVE_RDD_FINAL` action |
| `agents/prompts/supervisor_prompt.py` | Add caller role guidance section |
| `agents/graph/nodes/supervisor_node.py` | Include `user_role` in LLM input context |
| `agents/graph/service_request_graph.py` | Role-aware proactive routing in `_route_after_sync` |
| `agents/prompts/response_generation_prompt.py` | Add `ROLE_PERSONA_CONTEXT` dict |
| `agents/graph/nodes/response_generation_node.py` | Inject persona context into LLM prompt |

---

## Done When

- FM Manager can open a session and the bot greets them with FM-specific language (inspection, documents, readiness date)
- DD Engineer session shows RDD-specific language (handover meeting, contractual dates)
- Mall Manager still gets the existing CREATE_SR flow unchanged
- FM/RDD role guard logs a warning and returns "permission denied" when wrong role attempts to act
- `fm_api_submission_node` and `rdd_api_submission_node` permission checks now fire (not bypassed)
- All existing CREATE_SR unit tests still pass
