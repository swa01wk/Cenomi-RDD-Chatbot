# Sprint 1 — JIRA Tickets
**Sprint Goal:** Complete the full RDD Handover lifecycle (all 4 phases) with role-aware agent, FM_REVIEW E2E, RDD_REVIEW E2E, and frontend stage-aware UI.  
**Start:** June 16, 2026 | **End:** June 19, 2026  
**Total:** 10 tickets · 51 story points

---

## Daily Plan

```
June 16 (Tue)  RDD-001 + RDD-002   Role & Auth pipeline + Supervisor personas
June 17 (Wed)  RDD-003 + RDD-004 + RDD-005   Backend lifecycle completion
June 18 (Thurs)  RDD-006 + RDD-007 + RDD-008   Backend tests + Frontend UI
June 19 (Fri)  RDD-009 + RDD-010   QA + WorkflowDefinition foundation
```

---

## Tickets

---

### RDD-001 · Role & Auth Pipeline

**Type:** Story | **Priority:** Critical | **SP:** 5 | **Due:** June 16

**Summary:** Wire `user_role` through the entire backend stack so that FM and RDD permission guards — currently silently bypassed — start working correctly.

**Context:**  
Today `security.py` always returns `roles=frozenset()`, `user_role` is never passed from the frontend, and `state.get("auth")` is always `None` in graph nodes. Every permission check in `fm_api_submission_node` and `rdd_api_submission_node` is bypassed.

**Files:**
- `backend/app/api/routes/chat.py`
- `backend/app/agents/graph/state.py`
- `backend/app/agents/services/permission_service.py`
- `backend/app/services/chat_orchestration_service.py`

**What to build:**
1. Add `user_role: str | None` to `ServiceRequestChatRequest` in `chat.py`; pass to `process_turn()`
2. Add `user_role: Optional[str]` and `auth: Any` fields to `ServiceRequestGraphState`
3. Add `ROLE_PERMISSION_MAP` to `permission_service.py` mapping each role to its permission frozenset; add `APPROVE_RDD_FINAL` to `ACTION_PERMISSION_MAP`
4. In `ChatOrchestrationService.process_turn()`, call `_build_auth_context(user_role)` using `ROLE_PERMISSION_MAP` to derive `AuthContext.roles`; inject `user_role`, `auth`, and `backend_refs["user_role"]` into `initial_state`

```python
# permission_service.py additions
ROLE_PERMISSION_MAP: dict[str, frozenset[str]] = {
    "MALL_MANAGER":  frozenset({"CAN_RAISE_HANDOVER_SR", "VIEW_FIT_OUT_HANDOVER"}),
    "FM_MANAGER":    frozenset({"CAN_FM_REVIEW_HANDOVER_SR", "CAN_APPROVE_FM_HANDOVER_SR",
                                "VIEW_FIT_OUT_HANDOVER", "VIEW_FIT_OUT_HANDOVER_INSPECTION"}),
    "OPERATIONS":    frozenset({"CAN_FM_REVIEW_HANDOVER_SR", "CAN_APPROVE_FM_HANDOVER_SR",
                                "VIEW_FIT_OUT_HANDOVER", "VIEW_FIT_OUT_HANDOVER_INSPECTION"}),
    "DD_ENGINEER":   frozenset({"CAN_RDD_REVIEW_HANDOVER_SR", "VIEW_FIT_OUT_HANDOVER",
                                "VIEW_FIT_OUT_HANDOVER_INSPECTION"}),
}
"APPROVE_RDD_FINAL": "CAN_RDD_REVIEW_HANDOVER_SR"   # add to ACTION_PERMISSION_MAP
```

**Acceptance Criteria:**
- `POST /api/chat/service-request` accepts optional `user_role` field
- `FM_MANAGER` role → `auth.roles` contains `CAN_FM_REVIEW_HANDOVER_SR` and `CAN_APPROVE_FM_HANDOVER_SR`
- `fm_api_submission_node` and `rdd_api_submission_node` permission checks now fire (not bypassed)
- Wrong role attempting FM action → returns `status=FAILED` with "Permission denied" message
- `user_role` persists across turns (stored in `backend_refs`, survives DB load)
- All existing CREATE_SR tests pass

**Depends on:** Nothing  
**Blocks:** RDD-002, RDD-003, RDD-004, RDD-005

---

### RDD-002 · Role-Aware Supervisor, Routing & Response Personas

**Type:** Story | **Priority:** High | **SP:** 5 | **Due:** June 16

**Summary:** Make the supervisor and response generator role-aware so FM Manager and DD Engineer get guided directly to their workflow stage without the LLM misclassifying their intent.

**Files:**
- `backend/app/agents/prompts/supervisor_prompt.py`
- `backend/app/agents/graph/nodes/supervisor_node.py`
- `backend/app/agents/graph/service_request_graph.py`
- `backend/app/agents/prompts/response_generation_prompt.py`
- `backend/app/agents/graph/nodes/response_generation_node.py`

**What to build:**
1. **Supervisor prompt**: Add `CALLER ROLE GUIDANCE` section explaining role→intent mapping (FM Manager "approve" = `APPROVE_HANDOVER_SERVICE_REQUEST`; DD Engineer "submit report" = same)
2. **Supervisor node**: Include `"Current user role: {user_role}"` in the LLM context string when `user_role` is set
3. **Proactive routing**: Extend `_route_after_sync` — when role matches stage, skip supervisor entirely:
   - `FM_MANAGER`/`OPERATIONS` + `FM_REVIEW` → `fm_review_entry` (bypass supervisor)
   - `DD_ENGINEER` + `RDD_REVIEW` → `rdd_review_entry` (bypass supervisor)
4. **Response personas**: Add `ROLE_PERSONA_CONTEXT` dict to response prompt; inject matching persona block (role+stage key) into the LLM context before generating response

```python
# Response persona examples
("FM_MANAGER", "FM_REVIEW"): "You are assisting an FM Manager with site inspection review.
  Use language around: inspection, unit readiness, checklist, survey, COP.
  Guide: upload 3 docs → set readiness date → save or approve.
  Expected handover date is auto-calculated (readiness + 7 days)."

("DD_ENGINEER", "RDD_REVIEW"): "You are assisting an RDD Project Manager with handover meeting review.
  Use language around: handover meeting, contractual dates, fit-out, trading date, guidelines.
  Guide: upload report → guidelines link → 4 dates → submit → final approve.
  Date order: actual_handover ≤ fitout_start ≤ fitout_end ≤ trading_date."
```

**Acceptance Criteria:**
- FM Manager session at FM_REVIEW: supervisor bypassed, goes directly to `fm_review_entry`
- DD Engineer session at RDD_REVIEW: supervisor bypassed, goes directly to `rdd_review_entry`
- FM Manager receives inspection/checklist language in bot responses
- DD Engineer receives handover meeting/contractual dates language
- Mall Manager CREATE_SR flow completely unchanged
- When `user_role=None`, no persona added (empty string fallback, no error)

**Depends on:** RDD-001  
**Blocks:** RDD-007 (frontend sends user_role to trigger these paths)

---

### RDD-003 · Document Upload Bridge (`document_upload_node`)

**Type:** Story | **Priority:** Critical | **SP:** 4 | **Due:** June 17

**Summary:** Implement the empty `document_upload_node` stub and wire it into the graph between confirmation gates and payload builders. This is the missing link that lets FM and RDD platform submissions include the uploaded document IDs.

**Context:**  
`POST /api/upload` already works and writes `document_id` entries to `draft.documents`. `load_session_node` already loads these into `state["documents"]`. The `fm_payload_builder` already reads `backend_refs["uploaded_documents"]` — it's just always empty today because nothing bridges `state["documents"]` → `backend_refs`.

**Files:**
- `backend/app/agents/graph/nodes/document_upload_node.py`
- `backend/app/agents/graph/service_request_graph.py`

**What to build:**

**Part A — Implement the node:**
```python
@trace_node("document_upload", "CHAIN")
async def document_upload_node(state) -> dict:
    documents = state.get("documents") or []
    backend_refs = dict(state.get("backend_refs") or {})
    fm_doc_ids, rdd_doc_id = [], None

    for doc in documents:
        doc_id = doc.get("document_id")
        doc_type = doc.get("document_type_id", "")
        if not doc_id: continue
        if doc_type in FM_ALLOWED_DOCUMENTS:
            if doc_id not in fm_doc_ids: fm_doc_ids.append(doc_id)
        elif doc_type in RDD_REQUIRED_DOCUMENTS:
            rdd_doc_id = doc_id

    existing = backend_refs.get("uploaded_documents") or []
    backend_refs["uploaded_documents"] = list({*existing, *fm_doc_ids})
    if rdd_doc_id:
        backend_refs["rdd_document_id"] = rdd_doc_id
    return {"backend_refs": backend_refs}
```

**Part B — Wire into graph:**
```
Before: fm_confirmation  → [CONFIRMED] → fm_payload_builder
After:  fm_confirmation  → [CONFIRMED] → document_upload → fm_payload_builder

Before: rdd_confirmation → [CONFIRMED] → rdd_payload_builder
After:  rdd_confirmation → [CONFIRMED] → document_upload → rdd_payload_builder
```
Add `_route_after_doc_upload` routing function: `FM_REVIEW` → `fm_payload_builder`, `RDD_REVIEW` → `rdd_payload_builder`.

**Acceptance Criteria:**
- 3 FM docs in `state["documents"]` → `backend_refs["uploaded_documents"]` has 3 IDs after node runs
- 1 RDD report in `state["documents"]` → `backend_refs["rdd_document_id"]` set
- FM + RDD docs mixed → both partitions correctly populated
- Duplicate doc IDs deduplicated
- Pre-existing `backend_refs["uploaded_documents"]` merged (not replaced)
- `graph.get_graph().nodes` includes `"document_upload"`
- FM/RDD submission payloads now include document IDs (end-to-end)

**Depends on:** RDD-001  
**Blocks:** RDD-004, RDD-005

---

### RDD-004 · FM_REVIEW Completion (Date Auto-Calc + Schema Fix)

**Type:** Story | **Priority:** High | **SP:** 5 | **Due:** June 17

**Summary:** Fix the FM_REVIEW stage so (1) `expected_handover_date` is auto-calculated from `unit_readiness_date + 7 days` instead of being asked from the user, and (2) the FM payload correctly carries both dates.

**Context:**  
`expected_handover_date` is currently in `FM_REVIEW_STAGE.required_fields`, causing the bot to ask the user for it. The business rule is: this date is always readiness + 7 days (read-only, system-computed).

**Files:**
- `backend/app/agents/schemas/handover_schema.py`
- `backend/app/agents/graph/nodes/merge_state_node.py`

**What to build:**

**Part A — Schema fix:**
- Remove `"expected_handover_date"` from `FM_REVIEW_STAGE.required_fields`
- Add `BACKEND_COMPUTED_FIELDS: frozenset[str] = frozenset({"expected_handover_date"})`
- Remove from `EXTRACTABLE_FIELDS` (LLM should never try to extract it)

**Part B — Auto-calculation in `merge_state_node`:**
```python
# After merging collected_data, for FM_REVIEW stage:
if workflow_stage == "FM_REVIEW":
    readiness = collected.get("unit_readiness_date", "")
    if readiness and not collected.get("expected_handover_date"):
        collected["expected_handover_date"] = _add_days(readiness, 7)

def _add_days(date_str: str, days: int) -> str:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return (datetime.strptime(date_str, fmt) + timedelta(days=days)).strftime("%Y-%m-%d")
        except ValueError: continue
    return date_str
```

**Acceptance Criteria:**
- `get_missing_fields("FM_REVIEW", {"unit_readiness_date": "2026-06-18"})` returns `[]`
- Bot no longer asks "What is the expected handover date?"
- `unit_readiness_date="2026-06-18"` → `expected_handover_date="2026-06-25"` in `collected_data`
- Month boundary correct: `"2026-01-28"` → `"2026-02-04"`
- If `expected_handover_date` already set, not overwritten
- PATCH payload sent to platform includes `expected_handover_date: "2026-06-25"`
- CREATE_SR and RDD_REVIEW stages unaffected

**Depends on:** RDD-001, RDD-003  
**Blocks:** RDD-006 (test FM E2E)

---

### RDD-005 · RDD Final Approval Path (Phase 3b — PATCH APPROVED)

**Type:** Story | **Priority:** Critical | **SP:** 6 | **Due:** June 17

**Summary:** Implement the missing Phase 3b — after `REPORT_SUBMITTED`, the DD Engineer can give final approval via a PATCH APPROVED call that sets `workflow_stage = SR_COMPLETED`.

**Context:**  
Currently `rdd_api_submission_node` only handles POST `REPORT_SUBMITTED`. There is no path for the PATCH APPROVED that completes the SR. `rdd_review_entry_node` also has no `approve_rdd_final` action handler.

**Files:**
- `backend/app/agents/graph/nodes/rdd_review_entry_node.py`
- `backend/app/agents/services/payload_builder_service.py`
- `backend/app/agents/graph/nodes/rdd_payload_builder_node.py`
- `backend/app/agents/graph/nodes/rdd_api_submission_node.py`
- `backend/app/agents/graph/nodes/sr_status_sync_node.py`
- `backend/app/api/routes/chat.py` (add `rdd_status` to response)

**What to build:**

**1. `rdd_review_entry_node.py`** — add action handler:
```python
if action_override == "approve_rdd_final":
    backend_refs["rdd_action"] = "final_approve"
    return {"backend_refs": backend_refs}
```

**2. `payload_builder_service.py`** — add helper:
```python
def build_rdd_approve_payload(backend_refs: dict, comment: str = "") -> dict:
    sr_id = backend_refs.get("sr_id", "")
    return {
        "payload": {"current_sr_status": "APPROVED", "user_action": None,
                    "sr_id": sr_id, "comment": comment},
        "status": "APPROVED",
        "service_request_id": sr_id,
        "service_category": "FIT_OUT_AND_HANDOVER",
        "sub_category": "HANDOVER",
        "tenant_profile_id": backend_refs.get("tenant_profile_id"),
        "property_id": backend_refs.get("property_id"),
    }
```

**3. `rdd_payload_builder_node.py`** — branch on `rdd_action`:
- `"final_approve"` → `build_rdd_approve_payload()`
- `"submit"` (default) → existing `build_rdd_report_payload()`

**4. `rdd_api_submission_node.py`** — branch on `rdd_action`:
- `"final_approve"` → `svc.patch_service_request(sr_id, payload)` + permission check `APPROVE_RDD_FINAL` + on success: `workflow_stage="SR_COMPLETED"`, `backend_refs["rdd_status"]="APPROVED"`, audit log `sr.rdd.final_approved`
- `"submit"` → existing POST path unchanged

**5. `sr_status_sync_node.py`** — store rdd_status:
```python
if platform_status == "REPORT_SUBMITTED":
    backend_refs["rdd_status"] = "REPORT_SUBMITTED"
elif platform_status == "APPROVED":
    backend_refs["rdd_status"] = "APPROVED"
```

**6. `chat.py`** — add to `ChatStatePayload`:
```python
rdd_status: str | None = None       # "REPORT_SUBMITTED" | "APPROVED" | None
collected_data: dict | None = None  # full collected_data dict for frontend context panel
```
Extract from `result.state.backend_refs.get("rdd_status")` and `result.state.get("collected_data")` before returning response.

**Acceptance Criteria:**
- `action_override="approve_rdd_final"` with `DD_ENGINEER` role → PATCH `/service-requests/{sr_id}` called
- PATCH succeeds → `workflow_stage="SR_COMPLETED"`, `status="SUBMITTED"` in graph state
- PATCH fails → `status="FAILED"` with descriptive error
- `DD_ENGINEER` wrong role trying `approve_rdd_final` → Permission denied
- `sr_status_sync_node` sets `backend_refs["rdd_status"]="REPORT_SUBMITTED"` when platform SR is at that status
- `ChatStatePayload` in API response includes `rdd_status`
- `ChatStatePayload` in API response includes `collected_data` (non-null once SR is created)
- Existing POST REPORT_SUBMITTED path completely unchanged
- Audit log entry `sr.rdd.final_approved` written on success

**Depends on:** RDD-001, RDD-003  
**Blocks:** RDD-006 (test RDD E2E), RDD-008 (frontend Final Approve button)

---

### RDD-006 · Backend Unit & Integration Tests

**Type:** Story | **Priority:** High | **SP:** 5 | **Due:** June 18

**Summary:** Write the essential unit tests for Plans 01+02 and two integration tests covering the full FM and RDD E2E flows.

**Files:** New/extended test files under `backend/tests/`

**Unit tests to write:**

| Test file | What to cover |
|---|---|
| `test_permission_service.py` | `ROLE_PERMISSION_MAP` all 4 roles; `APPROVE_RDD_FINAL` action; wrong role raises `PermissionDeniedError` |
| `test_document_upload_node.py` | FM docs partitioned; RDD doc ID set; deduplication; empty docs; `document_id=None` skipped |
| `test_merge_state_node.py` | `expected_handover_date` auto-calc from various input formats; not overwritten if present; non-FM stages unaffected |
| `test_rdd_final_approve.py` | `build_rdd_approve_payload` output shape; `rdd_payload_builder_node` branches correctly; `rdd_api_submission_node` PATCH path fires and sets `workflow_stage=SR_COMPLETED` |

**Integration tests to write:**

| Test | Scenario |
|---|---|
| `test_fm_review_e2e.py` | Session with `sr_id`, `FM_MANAGER` role, 3 docs in `state["documents"]`, `action_override="approve_fm_review"` → assert PATCH called with doc IDs + dates; `fm_status="APPROVED"` |
| `test_rdd_review_e2e.py` | (A) Submit: 1 RDD doc + 5 fields collected + `action_override="submit_rdd_report"` → POST REPORT_SUBMITTED with dates in DD/MM/YYYY. (B) Final approve: `rdd_status="REPORT_SUBMITTED"` + `action_override="approve_rdd_final"` → PATCH APPROVED + `workflow_stage=SR_COMPLETED` |

**Acceptance Criteria:**
- `pytest backend/tests/` passes with 0 failures
- All new test files have at least 5 test cases each
- Integration tests use `httpx.MockTransport` (or equivalent) for platform API calls — no real HTTP
- Coverage for all new/changed modules ≥ 80%

**Depends on:** RDD-001, RDD-002, RDD-003, RDD-004, RDD-005

---

### RDD-007 · Frontend Role Selector + API Contract

**Type:** Story | **Priority:** High | **SP:** 5 | **Due:** June 18

**Summary:** Add a role selection screen as the chatbot's entry point, pass `user_role` in every chat request, and surface `rdd_status` from the backend response to drive stage-specific button logic.

**Files:**
- `frontend/lib/api/chat-client.ts`
- `frontend/lib/types/chat.ts`
- `frontend/components/chatbot/RoleSelector.tsx` (new)
- `frontend/app/service-request-chat/page.tsx`

**What to build:**

**1. `chat-client.ts`** — add `user_role?: string` to request params; include in JSON body

**2. `chat.ts` types** — add `rdd_status: string | null` to `ChatStatePayload` type

**3. `RoleSelector.tsx`** — role card picker component:
- 4 cards: Mall Manager, FM Manager, Operations, RDD Project Manager
- Each card: role name + description + icon
- Selection stored to `localStorage["chatbot_user_role"]`
- Calls `onRoleSelected(role)` to parent

**4. `page.tsx`** — role-gated chat entry:
- On mount: read `localStorage["chatbot_user_role"]`
- If set → show chat (pass `userRole` down)
- If not set → show `<RoleSelector />`
- Chat header shows "Chatting as: FM Manager" with a "Change" button
- "Change" button clears `localStorage` and shows selector again

**Acceptance Criteria:**
- First visit → role selector shown (4 card options)
- Role selected → chat loads immediately, no reload
- Page refresh → role restored from `localStorage`, chat opens directly
- "Change role" → selector re-shown, session state preserved until new message sent
- Every chat request body includes `user_role: "FM_MANAGER"` (or whatever is selected)
- Response `state.rdd_status` accessible in frontend (`null`, `"REPORT_SUBMITTED"`, or `"APPROVED"`)
- TypeScript types for `user_role` and `rdd_status` — no `any`

**Depends on:** RDD-005 (backend `rdd_status` in response)  
**Blocks:** RDD-008

---

### RDD-008 · Frontend Stage-Aware UI Components

**Type:** Story | **Priority:** High | **SP:** 8 | **Due:** June 18

**Summary:** Build four new UI components — `StageActions`, `DocumentUploadPanel`, `LifecycleStepper`, `StageContextPanel` — and wire them into `ServiceRequestChat`.

**Files:**
- `frontend/components/chatbot/StageActions.tsx` (new)
- `frontend/components/chatbot/DocumentUploadPanel.tsx` (new)
- `frontend/components/chatbot/LifecycleStepper.tsx` (new)
- `frontend/components/chatbot/StageContextPanel.tsx` (new)
- `frontend/lib/api/upload-client.ts` (new)
- `frontend/components/chatbot/ServiceRequestChat.tsx`

**What to build:**

**`StageActions.tsx`** — action buttons below the chat input:

| Role | Stage | `rdd_status` | Buttons |
|---|---|---|---|
| FM_MANAGER / OPERATIONS | FM_REVIEW | — | "Save Progress" + "Approve Review" |
| DD_ENGINEER | RDD_REVIEW | null | "Submit Report" |
| DD_ENGINEER | RDD_REVIEW | REPORT_SUBMITTED | "Final Approve" |
| Any | SR_COMPLETED | — | Completion banner only |

Button click → calls `onAction(action_value)` → parent sends chat request with `action: value`; no user chat bubble emitted for button actions.

**`DocumentUploadPanel.tsx`** — role-scoped upload area (shown when stage=FM_REVIEW or RDD_REVIEW and `sr_id` exists):
- FM role: 3 document type selectors (Checklist, Site Survey, COP)
- DD role: report upload + outcome picker (Approved / Approved with Changes / Disapproved)
- Upload calls `POST /api/upload` (multipart: `file`, `document_type`, `session_id`, `sr_id`)
- Uploaded documents shown in list: `📄 filename — Doc Type ✓`
- Error state with retry

**`upload-client.ts`** — `uploadDocument(file, documentType, sessionId, srId)` helper calling `POST /api/upload`

**`LifecycleStepper.tsx`** — horizontal stage progress bar (hidden when no `sr_id`):
- 4 steps: Create SR → FM Review → RDD Review → Complete
- Past: green ✓ | Active: blue + bold | Future: grey
- Role name shown under active step

**`StageContextPanel.tsx`** — collapsible prior-stage data panel (shown at top of chat when `workflowStage ∈ {FM_REVIEW, RDD_REVIEW}` and `srId` is set):
- FM_REVIEW: shows SR ID, Mall, Brand, Unit Code, Lease Code, Description (all from Stage 1 `collected_data`)
- RDD_REVIEW: all of the above + `unit_readiness_date` and `expected_handover_date` (set by FM in Stage 2)
- Collapsed by default; toggled by a chevron button
- Data sourced from `ChatStatePayload.collected_data` — no extra API call needed

**`ServiceRequestChat.tsx`** integration:
- `StageContextPanel` at the top of the chat area (above message list)
- `LifecycleStepper` below the context panel
- `DocumentUploadPanel` between messages and input
- `StageActions` below input
- `uploadedDocuments` state maintained per session
- `isLoading` disables `StageActions` during bot response

**Acceptance Criteria:**
- FM Manager in FM_REVIEW sees: checklist/survey/COP upload slots + "Save Progress" + "Approve Review"
- DD Engineer in RDD_REVIEW sees: report upload + "Submit Report"
- After submitting report: "Submit Report" replaced by "Final Approve"
- Uploading a file shows it in the uploaded docs list immediately
- Clicking "Approve Review" sends `action="approve_fm_review"` in the next request (no visible user message)
- Stage stepper correctly reflects current `workflow_stage`
- FM Manager at FM_REVIEW sees collapsed "SR Context" panel with Stage 1 data; expanding it shows SR ID, mall, brand, unit code, lease code, description
- DD Engineer at RDD_REVIEW sees SR Context panel with Stage 1 + Stage 2 data (including `unit_readiness_date` and `expected_handover_date`)
- No layout breakage on 1280px desktop viewport

**Depends on:** RDD-007  
**Blocks:** RDD-009

---

### RDD-009 · End-to-End QA — All Three Persona Flows

**Type:** Story | **Priority:** High | **SP:** 5 | **Due:** June 19

**Summary:** Manually execute the complete lifecycle for each of the three user personas against the running application to verify the full E2E integration.

**Setup:** Application running locally with Docker Compose (Postgres + Redis). Backend on `:8000`, frontend on `:3000`.

**Flow A — Mall Manager (CREATE_SR → SR_CREATED)**
1. Open chatbot → select "Mall Manager"
2. "I need to raise a handover request for Under Armour in Jawharat Jeddah"
3. Select lease from disambiguation card
4. Provide description, inspection dates, inspector choice, comments
5. Confirm SR creation
6. Assert: SR created in platform (check SR ID in response), stepper at "FM Review"

**Flow B — FM Manager (FM_REVIEW → FM Approved)**
*(use the SR created in Flow A, or a pre-existing SR in FM_REVIEW)*
1. Open chatbot → select "FM Manager" (same session as SR above, or link SR ID)
2. Bot greets with FM-specific guidance (no supervisor needed)
3. Assert: "SR Context" panel visible at top of chat (collapsed); expand it and confirm it shows SR ID, mall, brand, unit code, lease code, and description from Stage 1
4. Upload 3 PDF documents via upload panel (checklist, survey, COP)
5. Provide `unit_readiness_date`; bot shows `expected_handover_date` = readiness + 7 days (auto-calc)
6. Click "Approve Review" → confirm
7. Assert: PATCH `/service-requests/{id}` with `status=APPROVED` called, 3 doc IDs in payload, stepper at "RDD Review"

**Flow C — DD Engineer (RDD_REVIEW → SR_COMPLETED)**
*(continues from Flow B)*
1. Open chatbot → select "RDD Project Manager"
2. Bot greets with RDD-specific guidance (no supervisor)
3. Assert: "SR Context" panel shows Stage 1 data + `unit_readiness_date` and `expected_handover_date` set by FM Manager in Stage 2
4. Upload handover meeting report PDF
5. Provide guidelines URL and 4 contractual dates (actual handover, fit-out start/end, trading)
6. Click "Submit Report" → confirm
7. Assert: POST `/service-requests` with `status=REPORT_SUBMITTED`, dates in DD/MM/YYYY, "Final Approve" button appears
8. Click "Final Approve" → confirm
9. Assert: PATCH `/service-requests/{id}` with `status=APPROVED`, stepper at "Complete ✓"

**Acceptance Criteria:**
- All 3 flows complete without errors
- Bot language is role-appropriate at every turn (FM = inspection language, DD = contractual language)
- Document IDs present in FM and RDD payloads
- `expected_handover_date` auto-calculated (never asked from user)
- Final approval sets `workflow_stage=SR_COMPLETED`
- FM Manager SR Context panel shows correct Stage 1 data from Flow A
- DD Engineer SR Context panel shows Stage 1 data + FM dates set in Flow B
- No regression in CREATE_SR (Mall Manager flow unchanged from previous working state)

**Depends on:** RDD-001 through RDD-008

---

### RDD-010 · WorkflowDefinition Foundation (Sprint 2 Prep)

**Type:** Story | **Priority:** Medium | **SP:** 3 | **Due:** June 19 *(complete if capacity remains)*

**Summary:** Enrich `StageDefinition` with all four dimensions (roles, permissions, valid actions, API config) and declare `HANDOVER_WORKFLOW` as a `WorkflowDefinition` object. This lays the data structure foundation for the `WorkflowDefinitionRegistry` in Sprint 2 without changing any current behaviour.

**Files:**
- `backend/app/agents/schemas/handover_schema.py`

**What to build:**
```python
@dataclass(frozen=True)
class StageDefinition:
    stage: str
    required_fields: tuple[str, ...]
    required_documents: tuple[str, ...] = ()
    auto_computed_fields: tuple[str, ...] = ()   # ← new
    allowed_roles: tuple[str, ...] = ()           # ← new
    required_permissions: tuple[str, ...] = ()   # ← new
    valid_actions: tuple[str, ...] = ()           # ← new
    api_method: str = "POST"                      # ← new
    api_status_on_submit: str = ""               # ← new
    api_status_on_secondary: str = ""            # ← new (for 2-step stages)

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
    stakeholders: tuple[str, ...]
    def get_stage(self, name: str) -> StageDefinition | None: ...
    def stage_for_role(self, role: str) -> StageDefinition | None: ...

HANDOVER_WORKFLOW = WorkflowDefinition(
    workflow_id="handover_service_request",
    service_category="FIT_OUT_AND_HANDOVER",
    sub_category="HANDOVER",
    stakeholders=("MALL_MANAGER", "FM_MANAGER", "OPERATIONS", "DD_ENGINEER"),
    stages=(CREATE_SR_STAGE, FM_REVIEW_STAGE, RDD_REVIEW_STAGE),
    ...
)
```

**Acceptance Criteria:**
- All existing `StageDefinition` usages still work (backward-compatible defaults)
- `HANDOVER_WORKFLOW.get_stage("RDD_REVIEW")` returns `RDD_REVIEW_STAGE` with correct `allowed_roles=("DD_ENGINEER",)`
- `HANDOVER_WORKFLOW.stage_for_role("FM_MANAGER")` returns `FM_REVIEW_STAGE`
- All existing tests pass (no behaviour change — data structure only)
- `WorkflowDefinition` is importable from `handover_schema.py`

**Depends on:** RDD-001 through RDD-009 complete  
**Blocks:** Plan 04 / Sprint 2 (WorkflowDefinitionRegistry)

---

## Ticket Summary

| ID | Title | SP | Due | Depends On |
|---|---|---|---|---|
| RDD-001 | Role & Auth Pipeline | 5 | June 16 | — |
| RDD-002 | Role-Aware Supervisor, Routing & Personas | 5 | June 16 | RDD-001 |
| RDD-003 | Document Upload Bridge | 4 | June 17 | RDD-001 |
| RDD-004 | FM_REVIEW Completion (Date Auto-Calc) | 5 | June 17 | RDD-001, 003 |
| RDD-005 | RDD Final Approval Path | 6 | June 17 | RDD-001, 003 |
| RDD-006 | Backend Unit & Integration Tests | 5 | June 18 | RDD-001–005 |
| RDD-007 | Frontend Role Selector + API Contract | 5 | June 18 | RDD-005 |
| RDD-008 | Frontend Stage-Aware UI Components | 8 | June 18 | RDD-007 |
| RDD-009 | End-to-End QA — All Three Persona Flows | 5 | June 19 | RDD-001–008 |
| RDD-010 | WorkflowDefinition Foundation (Sprint 2 Prep) | 3 | June 19 | RDD-009 |
| **Total** | | **51 SP** | | |

---

## Dependency Graph

```
RDD-001 (Role/Auth) ──────────────────────────────────────┐
    │                                                      │
    ├──► RDD-002 (Supervisor + Routing + Personas)         │
    │                                                      │
    ├──► RDD-003 (Document Upload Node)                    │
    │         │                                            │
    │         ├──► RDD-004 (FM_REVIEW completion)          │
    │         │                                            │
    │         └──► RDD-005 (RDD Final Approval)            │
    │                   │                                  │
    └───────────────────┴──► RDD-006 (Backend Tests)       │
                              │                            │
                              └──► RDD-007 (FE API)        │
                                        │                  │
                                        └──► RDD-008 (FE UI)
                                                  │
                                                  └──► RDD-009 (QA)
                                                            │
                                                            └──► RDD-010 (Foundation)
```

## Definition of Done

- Code written and self-reviewed
- Acceptance criteria all checked
- `pytest backend/tests/` passes clean
- No new linter or type errors
- Manually verified in running application
- Ticket status updated to Done
