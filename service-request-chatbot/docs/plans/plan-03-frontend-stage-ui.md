# Plan 03 — Frontend Stage-Aware UI

**Scope:** Add role selector (POC auth), stage-specific action buttons, document upload panel, and lifecycle progress stepper to the frontend.  
**Depends on:** Plan 01 (`user_role` accepted in chat request); Plan 02 (backend `action_override` values exist and work).  
**Blocks:** Nothing — this is the final user-facing layer.

---

## Context

The current frontend:
- Hardcodes `user_id: "demo_user"` — no role identity
- Has no FM/RDD-specific action buttons
- Has no file upload UI scoped to FM/RDD stages
- Has no stage progress indicator

The backend already accepts `action` and `user_role` in the request body. The upload API already exists at `POST /api/upload`. All that's missing is the frontend that uses them.

---

## New Components Overview

```
frontend/components/chatbot/
├── RoleSelector.tsx          ← Task 3.1: POC role picker (first screen)
├── StageActions.tsx          ← Task 3.2: Role+stage action buttons
├── DocumentUploadPanel.tsx   ← Task 3.3: Role-scoped file upload
└── LifecycleStepper.tsx      ← Task 3.4: CREATE_SR → FM_REVIEW → RDD_REVIEW → DONE

frontend/lib/api/
└── upload-client.ts          ← Task 3.3: Upload API client helper (if not existing)
```

---

## Task 3.1 — Role Selector (POC Auth)

Since real JWT auth is not wired, add a role selector as the first screen the user sees before starting a chat session.

**File:** `frontend/components/chatbot/RoleSelector.tsx`

```tsx
// Role cards — user picks their role before entering the chat
const ROLES = [
  {
    id: "MALL_MANAGER",
    label: "Mall Manager",
    description: "Create handover service requests when a lease is activated",
    icon: "🏢",
  },
  {
    id: "FM_MANAGER",
    label: "FM Manager",
    description: "Conduct site inspection, upload documents, set readiness dates",
    icon: "🔧",
  },
  {
    id: "OPERATIONS",
    label: "Operations",
    description: "Conduct site inspection and approve FM review",
    icon: "⚙️",
  },
  {
    id: "DD_ENGINEER",
    label: "RDD Project Manager",
    description: "Chair handover meeting, submit report, enter contractual dates",
    icon: "📋",
  },
];
```

- Show role cards before the chat area loads
- On selection: store `userRole` in React state + `localStorage` (persists on refresh)
- Show selected role name in the chat header
- Allow role switching via a small settings button (clears session and localStorage)

**File:** `frontend/app/service-request-chat/page.tsx`

- Read `userRole` from `localStorage` on mount
- If no role selected, show `<RoleSelector />` instead of chat
- Pass `userRole` down to `ServiceRequestChat` component

---

## Task 3.2 — Stage-Specific Action Buttons

**File:** `frontend/components/chatbot/StageActions.tsx`

Render role+stage-appropriate action buttons below the chat input. Each button sends an `action` value in the next chat request instead of a text message.

```tsx
interface StageActionsProps {
  workflowStage: string | null;
  userRole: string | null;
  rddStatus?: string | null;    // "REPORT_SUBMITTED" triggers different RDD buttons
  onAction: (action: string) => void;
  disabled?: boolean;
}
```

**Button matrix:**

| `userRole` | `workflowStage` | `rddStatus` | Buttons shown |
|---|---|---|---|
| `FM_MANAGER` / `OPERATIONS` | `FM_REVIEW` | any | "Save Progress" + "Approve Review" |
| `DD_ENGINEER` | `RDD_REVIEW` | `null` / `IN_PROCESS` | "Submit Report" |
| `DD_ENGINEER` | `RDD_REVIEW` | `REPORT_SUBMITTED` | "Final Approve" |
| Any | `SR_COMPLETED` | any | (no buttons — show completion banner) |
| `MALL_MANAGER` | `CREATE_SR` | any | (no buttons — uses confirm/cancel from bot) |

Button → `action` value mapping:
```
"Save Progress"   → action: "save_fm_progress"
"Approve Review"  → action: "approve_fm_review"
"Submit Report"   → action: "submit_rdd_report"
"Final Approve"   → action: "approve_rdd_final"
```

**Styling:**
- "Approve" and "Final Approve" buttons: green/primary
- "Save Progress": secondary/outline
- "Submit Report": blue/primary
- All buttons disabled when `disabled=true` (while bot is responding)

**Integration in `ServiceRequestChat.tsx`:**

```tsx
// Read rdd_status from the latest response state or backend_refs
const rddStatus = latestState?.rdd_status ?? null;

<StageActions
  workflowStage={latestState?.workflow_stage}
  userRole={userRole}
  rddStatus={rddStatus}
  onAction={(action) => sendMessage("", action)}
  disabled={isLoading}
/>
```

When `onAction` is called:
- Send a chat request with `action: action` and an empty message (or a context string like "User clicked: Approve FM Review")
- Do NOT send a user chat bubble for pure button actions (it's UI-initiated)

---

## Task 3.3 — Document Upload Panel

**File:** `frontend/components/chatbot/DocumentUploadPanel.tsx`

Show a scoped file upload area when the current stage requires documents and an `sr_id` exists.

```tsx
interface DocumentUploadPanelProps {
  sessionId: string;
  srId: string | null;
  workflowStage: string | null;
  userRole: string | null;
  uploadedDocuments: UploadedDoc[];
  onUploadComplete: (doc: UploadedDoc) => void;
}
```

**Document types per role:**

| Role | Stage | Allowed document types | Label |
|---|---|---|---|
| `FM_MANAGER` / `OPERATIONS` | `FM_REVIEW` | `SR_HANDOVER_CHECKLIST` | Handover Checklist |
| `FM_MANAGER` / `OPERATIONS` | `FM_REVIEW` | `SR_HANDOVER_SITE_SURVEY` | Site Survey |
| `FM_MANAGER` / `OPERATIONS` | `FM_REVIEW` | `SR_COP_CHECKLIST_OTHER` | COP Checklist |
| `DD_ENGINEER` | `RDD_REVIEW` | `DR_SR_HANDOVER_REPORT` | Handover Meeting Report |

**Upload flow:**
1. User selects file + document type from dropdown
2. Frontend calls `POST /api/upload` (multipart form):
   ```
   file: <binary>
   document_type: SR_HANDOVER_CHECKLIST
   session_id: <uuid>
   sr_id: <sr_id>
   ```
3. On success: show the document in the "Uploaded Documents" list with:
   - Filename
   - Document type label
   - Status badge: "Uploaded ✓"
   - Optional: link to signed_url if available
4. On failure: show error message with retry option

**Uploaded documents list:**
```tsx
<UploadedDocumentList documents={uploadedDocuments} />
// Shows: [📄 handover-checklist.pdf — Handover Checklist ✓]
//        [📄 site-survey.pdf — Site Survey ✓]
//        [📄 cop-checklist.pdf — COP Checklist ✓]
```

**Show/hide conditions:**
- Show when: `workflowStage ∈ {FM_REVIEW, RDD_REVIEW}` AND `srId !== null`
- Hide when: stage is `CREATE_SR`, `SR_COMPLETED`, or `null`

**Upload API client** (`frontend/lib/api/upload-client.ts`):
```typescript
export async function uploadDocument(
  file: File,
  documentType: string,
  sessionId: string,
  srId: string,
): Promise<{ document_id: string | null; signed_url: string | null; status: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("document_type", documentType);
  form.append("session_id", sessionId);
  form.append("sr_id", srId);

  const res = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`);
  return res.json();
}
```

---

## Task 3.4 — Lifecycle Stepper

**File:** `frontend/components/chatbot/LifecycleStepper.tsx`

A horizontal progress bar showing which stage the SR is at.

```tsx
const STAGES = [
  { id: "CREATE_SR",    label: "Create SR",   role: "Mall Manager" },
  { id: "FM_REVIEW",    label: "FM Review",   role: "FM Manager" },
  { id: "RDD_REVIEW",   label: "RDD Review",  role: "RDD PM" },
  { id: "SR_COMPLETED", label: "Complete",    role: "" },
];
```

Stage state:
- Past stages: green checkmark ✓
- Current stage: blue dot + bold label + role name
- Future stages: grey

Show this stepper only when `sr_id` is present (SR has been created). Keep it hidden during `CREATE_SR` collection (no SR yet).

**Integration in `ServiceRequestChat.tsx`:**
```tsx
{srId && (
  <LifecycleStepper currentStage={latestState?.workflow_stage} />
)}
```

---

## Task 3.5 — Wire `user_role` into Every Chat Request

**File:** `frontend/lib/api/chat-client.ts`

Extend `postServiceRequestChat` to include `user_role`:
```typescript
export async function postServiceRequestChat(params: {
  session_id?: string;
  user_id: string;
  user_role?: string;   // ← new
  message: string;
  action?: string;
  selected_lease_id?: string;
  corrected_fields?: Record<string, unknown>;
}) { ... }
```

**File:** `frontend/components/chatbot/ServiceRequestChat.tsx`

Pass `userRole` (from RoleSelector state / localStorage) into every `postServiceRequestChat` call.

---

## Task 3.6 — Surface `rdd_status` in Frontend State

The backend now returns `rdd_status` inside `backend_refs` (set by `sr_status_sync_node`). The frontend needs this to show "Final Approve" instead of "Submit Report".

**Option A:** Include `rdd_status` in the `ChatStatePayload` response model (cleanest).

**File:** `backend/app/api/routes/chat.py`
```python
class ChatStatePayload(BaseModel):
    ...
    rdd_status: str | None = None   # REPORT_SUBMITTED | APPROVED | None
```

In `post_service_request_chat`:
```python
rdd_status = (result.state.backend_refs or {}).get("rdd_status")
state=ChatStatePayload(..., rdd_status=rdd_status),
```

**Frontend:** Read `response.state.rdd_status` and pass to `StageActions`.

---

## Task 3.7 — Stage Context Summary Panel

When a reviewer enters a review stage they need to see the data collected in the prior stage before verifying and approving. Show a collapsible "SR Context" panel at the top of the chat area whenever `workflowStage ∈ {FM_REVIEW, RDD_REVIEW}` and `srId !== null`.

**File:** `frontend/components/chatbot/StageContextPanel.tsx`

```tsx
interface StageContextPanelProps {
  workflowStage: string | null;
  collectedData: Record<string, string> | null;
  srId: string | null;
}
```

**FM_REVIEW — shows Stage 1 data (read-only):**

| Label | Field |
|---|---|
| SR ID | `srId` |
| Mall | `collected_data.mall` |
| Brand | `collected_data.brand` |
| Unit Code | `collected_data.unit_code` |
| Lease Code | `collected_data.lease_code` |
| Description | `collected_data.description` |

**RDD_REVIEW — shows Stage 1 + Stage 2 data (read-only):**

All FM_REVIEW fields above, plus:

| Label | Field |
|---|---|
| Unit Readiness Date | `collected_data.unit_readiness_date` |
| Expected Handover Date | `collected_data.expected_handover_date` |
| FM Documents | Uploaded FM docs (checklist, site survey, COP checklist) with ✓ status |

**Backend change — expose `collected_data` in `ChatStatePayload`:**

**File:** `backend/app/api/routes/chat.py`

```python
class ChatStatePayload(BaseModel):
    ...
    rdd_status: str | None = None
    collected_data: dict | None = None   # ← add this

# In post_service_request_chat:
state=ChatStatePayload(
    ...
    rdd_status=rdd_status,
    collected_data=result.state.get("collected_data"),
),
```

**Integration in `ServiceRequestChat.tsx`:**

```tsx
{(workflowStage === "FM_REVIEW" || workflowStage === "RDD_REVIEW") && srId && (
  <StageContextPanel
    workflowStage={workflowStage}
    collectedData={latestState?.collected_data ?? null}
    srId={srId}
  />
)}
```

The panel is collapsible (collapsed by default) so it does not crowd the chat area. Use a chevron toggle. Style with a light background border to visually distinguish it from chat messages.

---

## Files Changed

| File | Change |
|---|---|
| `frontend/components/chatbot/StageContextPanel.tsx` | New: collapsible prior-stage data panel |
| `frontend/components/chatbot/RoleSelector.tsx` | New: role card picker |
| `frontend/components/chatbot/StageActions.tsx` | New: role+stage action buttons |
| `frontend/components/chatbot/DocumentUploadPanel.tsx` | New: role-scoped upload panel |
| `frontend/components/chatbot/LifecycleStepper.tsx` | New: stage progress indicator |
| `frontend/lib/api/upload-client.ts` | New (or extend): `uploadDocument()` helper |
| `frontend/lib/api/chat-client.ts` | Add `user_role` to request params |
| `frontend/components/chatbot/ServiceRequestChat.tsx` | Wire in RoleSelector, StageActions, DocumentUploadPanel, LifecycleStepper, StageContextPanel |
| `frontend/app/service-request-chat/page.tsx` | Show RoleSelector if no role; pass `userRole` down |
| `backend/app/api/routes/chat.py` | Add `rdd_status` and `collected_data` to `ChatStatePayload` response model |

---

## Done When

- First-time user sees a role picker before the chat loads
- Selecting "FM Manager" and sending "I completed the inspection" shows FM-specific guidance
- FM Manager at FM_REVIEW stage sees "Save Progress" + "Approve Review" buttons below chat input
- Clicking "Approve Review" sends action without a visible user message bubble
- Document upload panel appears for FM stage showing 3 document type pickers
- Uploading a file shows it in the "Uploaded Documents" list with ✓
- DD Engineer at RDD_REVIEW sees "Submit Report" button; after submitting, sees "Final Approve"
- Stage stepper shows correct active stage with role name
- Role persists on page refresh (localStorage)
- FM Manager at FM_REVIEW sees a collapsed "SR Context" panel showing SR ID, mall, brand, unit code, lease code, and description from Stage 1
- DD Engineer at RDD_REVIEW sees the SR Context panel with Stage 1 data plus `unit_readiness_date` and `expected_handover_date` set by FM Manager in Stage 2
- Expanding the panel does not reload the page or trigger a new API call (data comes from `ChatStatePayload.collected_data`)
