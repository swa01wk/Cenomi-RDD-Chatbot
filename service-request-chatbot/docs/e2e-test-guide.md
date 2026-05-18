# End-to-End Test Guide — Handover Service Request

> **Environment:** Both `LEASE_TENANT_API_BASE_URL` and `SERVICE_REQUEST_API_BASE_URL` are empty in `.env`,
> so the **mock adapters** are active. No external APIs are required.
>
> **Frontend:** http://localhost:3000/service-request-chat  
> **Backend API docs:** http://localhost:8000/docs  
> **Observability dashboard:** http://localhost:3000/admin/agent-observability

---

## What Changed Since the Previous Guide

| Area | Old behaviour | Current behaviour |
|------|--------------|-------------------|
| **Title field** | Bot asked user for a title (Turn 3 in old happy path) | Title is **auto-generated** — `handover-{lease_code}-{description_slug}`. The bot never asks for it; the LLM is explicitly forbidden from extracting it. |
| **Multi-field extraction** | Bot collected exactly one field per turn | Bot now extracts **all fields mentioned in a single message** — e.g. start date + end date + inspector in one reply. |
| **Confirmation card placement** | Card appeared only in the right sidebar | Card now renders **inline in the chat stream** beneath the bot's message; sidebar still mirrors it. Previous cards become read-only once a new turn is sent. |
| **Confirm / Cancel buttons** | Triggered plain text messages only | Buttons send `action: "confirm"` / `action: "cancel"` — these bypass LLM text parsing and are acted on unconditionally. |
| **Inline field edits** | Corrections required a new chat message | The confirmation card lets users edit any editable field in-place. Edits are sent as `corrected_fields` — applied before validation, never going through the LLM. |
| **"No comments" handling** | Empty string was treated as missing → bot re-asked | `description`, `comments`, `notes` are optional — an empty-string answer (`""`) is accepted and never blocks submission. |
| **Cancel vs Restart** | "cancel" cleared all state | Two distinct behaviours: **"cancel"** (or Cancel button) during a pending card → sets status to REJECTED and asks what to change. **"start over" / "restart" / "new request"** → clears `active_agent` and truly restarts from scratch. |
| **`inspection_done_by` values** | Stored as display text | LLM normalises any natural-language phrasing to `FM_MANAGER` or `OPERATIONS` (uppercase enum). That is what the confirmation card and API payload contain. |
| **Date validation** | Not enforced server-side | `startDate` **must be strictly before** `endDate`. Equal dates are rejected with a blocking validation error. |

---

## Mock Data Reference

| Lease Code | Brand | Mall | City | Unit(s) | Area (sqm) |
|---|---|---|---|---|---|
| `t0105712` | Brand Under Armour | Jawharat Jeddah | Jeddah | FF050 | 420 |
| `t0208831` | Nike | Riyadh Park | Riyadh | GF101, GF102 | 680 |
| `t0301144` | Nike | Mall of Arabia | Jeddah | LG220 | 510 |
| `t0419977` | Zara | Dubai Festival City | Dubai | UF301 | 900 |

---

## Fields Collected During the Conversation

Backend-derived fields (IDs, area, city, unit codes) are resolved automatically from the lease lookup — you never need to type them. **Title is also system-generated** — you never type it.

| Field | Provided by | Accepted formats |
|---|---|---|
| Lease identifier | You | Lease code (`t0105712`), brand name, mall name, or combination |
| ~~Title~~ | **System** | Auto-generated: `handover-{lease_code}-{first 5 words of description}` |
| Description | You | Any text — e.g. `Standard fit-out inspection for new tenant unit` |
| Start date | You | `YYYY-MM-DD`, `June 1`, `1st June 2026` |
| End date | You | Same formats as start date; must be **after** start date |
| Inspection done by | You | "FM Manager", "FM team", "Operations", "ops team" — all normalised to `FM_MANAGER` / `OPERATIONS` |
| Comments | You | Any text, or say `No comments` / `No additional comments` to leave blank |

---

## The API Payload That Gets Constructed

When you confirm, the system assembles this payload and POSTs it to the mock SR API.
The mock returns `HTTP 201` with a UUID SR reference and a correlation ID.

```json
{
  "payload": {
    "mall": "Jawharat Jeddah",
    "brand": "Brand Under Armour",
    "lease": "t0105712",
    "title": "handover-t0105712-standard-fitout-inspection",
    "description": "Standard fit-out inspection for new tenant unit",
    "startDate": "2026-06-01",
    "endDate": "2026-06-03",
    "inspectionDoneBy": "FM_MANAGER",
    "inspection_done_by": "FM_MANAGER",
    "comments": "Hard opening date June 5 — please prioritise",
    "unit_codes": ["FF050"],
    "contracted_area": 420,
    "city": "Jeddah",
    "brand_id": 267,
    "tenant_profile_id": 116,
    "contract_id": 95404,
    "property_id": 3041,
    "lease_brand_mall": "t0105712 - Brand Under Armour - Jawharat Jeddah",
    "company_name": "116",
    "notes": "",
    "attachments": "",
    "documents_ids": [],
    "guideLineLink": "",
    "startDateLT": "",
    "endDateLT": "",
    "unit_readiness_date": "",
    "expected_handover_date": "",
    "tenant_contact": "",
    "user_action": null,
    "document_status_map": []
  },
  "title": "handover-t0105712-standard-fitout-inspection",
  "tenant_profile_id": 116,
  "property_id": 3041,
  "service_category": "FIT_OUT_AND_HANDOVER",
  "sub_category": "HANDOVER",
  "lease_code": "t0105712",
  "lease_id": 95404,
  "service_request_id": ""
}
```

> **Note:** `title` is now always auto-generated. It will never match the old pattern `Handover Inspection – UA FF050`.  
> `inspection_done_by` is always the uppercase enum value (`FM_MANAGER` / `OPERATIONS`), not the display text.

---

## Scenario 1 — Happy Path (Lease Code Known)

**Goal:** Full flow — intent → lease resolution → 5 field turns → confirmation card → submission.  
**Lease used:** `t0105712` (Under Armour, Jawharat Jeddah)  
**Total turns:** 8 (one fewer than the old guide — no title turn)

| Turn | Type this exactly |
|------|-------------------|
| 1 | `I want to create a handover service request` |
| 2 | `t0105712` |
| 3 | `Standard fit-out inspection for new tenant unit` |
| 4 | `2026-06-01` |
| 5 | `2026-06-03` |
| 6 | `FM Manager` |
| 7 | `Hard opening date June 5, please prioritise` |
| 8 | *(Click the **Confirm** button on the card, or type `Confirm`)* |

**What to expect at each step:**
- **Turn 1** → Bot asks for the lease code, brand, or mall
- **Turn 2** → Lease auto-resolved; bot asks for a description
- **Turn 3** → Description stored; title **auto-generated** as `handover-t0105712-standard-fitout-inspection`; bot asks for start date
- **Turns 4–7** → Bot collects one field per turn (start date → end date → inspection by → comments)
- **After Turn 7** → All fields collected; **confirmation card appears inline** in the chat with the auto-generated title visible; `state.workflow_stage = "CREATE_SR"`, `state.ready_to_submit = true`
- **Turn 8** → Bot replies with a success message containing a UUID SR reference number ✅

---

## Scenario 2 — Brand + Mall Search (No Lease Code)

**Goal:** Test free-text lease search and the multi-match selection card.  
**Lease used:** Nike (two matches — Riyadh Park and Mall of Arabia)

| Turn | Type this exactly |
|------|-------------------|
| 1 | `I need to raise a handover request for Nike` |
| 2 | *(A **lease selection card** appears in the sidebar — click **Nike – Riyadh Park**)* |
| 3 | `Inspection for Nike flagship unit at Riyadh Park mall` |
| 4 | `2026-07-10` |
| 5 | `2026-07-12` |
| 6 | `Operations` |
| 7 | `Tenant has requested early access from July 9` |
| 8 | *(Click **Confirm** on the card)* |

**What to expect:**
- **Turn 1** → Lease lookup finds 2 Nike leases; a **lease selection card** appears in the sidebar
- **Turn 2** → Clicking a lease sends `selected_lease_id` to the backend (no text needed); `lease_id`, `property_id`, `brand_id`, `unit_codes`, etc. all auto-filled. Bot asks for description.
- **Turns 3–7** → Normal field collection continues (no title turn)
- **Turn 8** → SR submitted successfully ✅

---

## Scenario 3 — Multi-Field Extraction (All in One Message)

**Goal:** Verify the LLM can extract **multiple fields** from a single message.  
**Lease used:** `t0419977` (Zara, Dubai Festival City)

| Turn | Type this exactly |
|------|-------------------|
| 1 | `Create a handover service request for lease t0419977 — description: New tenant fit-out handover for Zara flagship unit UF301. The inspection runs from June 10 to June 12 2026 and will be done by FM Manager. No additional comments.` |
| 2 | *(Confirmation card appears immediately — all fields extracted in one shot)* |
| 3 | *(Click **Confirm**)* |

**What to expect:**
- **Turn 1** → LLM extracts `lease_code`, `description`, `startDate`, `endDate`, `inspection_done_by`, and `comments` all at once; lease auto-resolved; title auto-generated as `handover-t0419977-new-tenant-fitout-handover-for`; all required fields are complete — **confirmation card appears on this very turn** ✅
- **Turn 3** → SR submitted ✅

> **Multi-field tip:** The bot intelligently captures every value you provide in a single message — even if it was only asking for one. You can skip multiple steps at once by volunteering information early.

---

## Scenario 4 — Partial Message Multi-Field

**Goal:** Test multi-field extraction mid-flow (user answers more than what was asked).  
**Lease used:** `t0208831` (Nike, Riyadh Park)

| Turn | Type this exactly |
|------|-------------------|
| 1 | `I want to raise a handover request` |
| 2 | `t0208831` |
| 3 | `Seasonal inspection for Nike Riyadh Park units, starts 2026-09-01, ends 2026-09-03, done by Operations` |
| 4 | `Units GF101 and GF102 both need inspection` |
| 5 | *(Confirmation card appears)* |
| 6 | *(Click **Confirm**)* |

**What to expect:**
- **Turn 3** → User provides description, start date, end date, AND inspector in one message — all four fields captured simultaneously
- **Turn 4** → Bot asks only for the remaining missing field (`comments`); user answers
- **After Turn 4** → Confirmation card appears ✅

---

## Scenario 5 — Mall Name Only (Partial Search)

**Goal:** Test that a mall-only search resolves to the right lease.  
**Lease used:** `t0105712` (Under Armour, resolved via mall name)

| Turn | Type this exactly |
|------|-------------------|
| 1 | `I want to open a handover request` |
| 2 | `Jawharat Jeddah mall` |
| 3 | `Initial fit-out handover inspection for new tenant space` |
| 4 | `2026-06-15` |
| 5 | `2026-06-17` |
| 6 | `FM Manager` |
| 7 | `Please schedule before the public opening` |
| 8 | `Yes, go ahead` |

**What to expect:**
- **Turn 2** → Mall name alone resolves to the single Under Armour lease at Jawharat Jeddah and auto-fills all backend fields ✅

---

## Scenario 6 — Inline Edit on Confirmation Card

**Goal:** Test updating a field by editing it directly on the confirmation card.

| Turn | Type this exactly |
|------|-------------------|
| 1 | `I want to create a handover service request` |
| 2 | `t0301144` |
| 3 | `Fit-out handover for Nike at Mall of Arabia, Jeddah` |
| 4 | `2026-08-01` |
| 5 | `2026-08-03` |
| 6 | `FM Manager` |
| 7 | `No additional comments` |
| 8 | *(Confirmation card appears — find the **End Date** row and edit it to `2026-08-05` in the card UI)* |
| 9 | *(Click **Confirm** on the card)* |

**What to expect:**
- **After Turn 7** → Confirmation card appears with `endDate: 2026-08-03`
- **Turn 8** → Edit `endDate` to `2026-08-05` inline on the card (no need to type in chat)
- **Turn 9** → SR submitted with `endDate: 2026-08-05` ✅

> **How inline edits work:** The corrected values are sent as `corrected_fields` alongside `action: "confirm"`. They are applied directly to `collected_data` before validation — the LLM is not involved in interpreting the correction.

---

## Scenario 7 — Text Correction After Confirmation Card

**Goal:** Test correcting a field by typing after the confirmation card appears.

| Turn | Type this exactly |
|------|-------------------|
| 1 | `I want to create a handover service request` |
| 2 | `t0301144` |
| 3 | `Fit-out handover for Nike at Mall of Arabia, Jeddah` |
| 4 | `2026-08-01` |
| 5 | `2026-08-03` |
| 6 | `FM Manager` |
| 7 | `No additional comments` |
| 8 | `Actually, change the end date to 2026-08-05` |
| 9 | *(Updated confirmation card shown)* |
| 10 | `Confirm` |

**What to expect:**
- **After Turn 7** → Confirmation card appears with `endDate: 2026-08-03`
- **Turn 8** → "change" is a `_REJECT_PHRASE`; status is set to `REJECTED`; field extraction captures `endDate: 2026-08-05`; a refreshed card appears with the corrected date
- **Turn 10** → SR submitted with the corrected date ✅

---

## Scenario 8 — Invalid Lease Code, Then Correct

**Goal:** Verify error handling when the lease lookup returns no results.

| Turn | Type this exactly |
|------|-------------------|
| 1 | `I want to create a handover request` |
| 2 | `LC-TEST-999` |
| 3 | *(Bot says lease not found)* |
| 4 | `Sorry, the correct code is t0208831` |
| 5 | `Seasonal handover inspection for Nike Riyadh Park units` |
| 6 | `2026-09-01` |
| 7 | `2026-09-03` |
| 8 | `Operations` |
| 9 | `Units GF101 and GF102 both need inspection` |
| 10 | `Confirm` |

**What to expect:**
- **Turn 2** → Mock lookup returns 0 matches; bot apologises and asks to try again
- **Turn 4** → Correct lease code accepted; flow resumes ✅

---

## Scenario 9 — Cancel vs Restart

**Goal:** Verify that "cancel" during confirmation asks what to change, while "start over" truly resets the session.

### 9a — Cancel (change one field, re-confirm)

| Turn | Type this exactly |
|------|-------------------|
| 1 | `I want to create a handover request` |
| 2 | `t0208831` |
| 3 | `Summer inspection for Nike Riyadh Park` |
| 4 | `2026-07-01` |
| 5 | `2026-07-03` |
| 6 | `Operations` |
| 7 | `No comments` |
| 8 | *(Confirmation card appears — click the **Cancel** button)* |
| 9 | `Change the start date to 2026-07-05` |
| 10 | *(Refreshed card — verify startDate is now 2026-07-05 and endDate is still 2026-07-03)* |

> ⚠️ **Note:** After Turn 9, validation will fail because `startDate (2026-07-05) > endDate (2026-07-03)`. The bot will surface a date-range error. Correct the end date before confirming.

**What to expect:**
- **Turn 8 (Cancel)** → `confirmation_status` set to `REJECTED`; bot asks what to change — the workflow is **not** reset; all collected data preserved
- **Turn 9** → Field extraction captures `startDate: 2026-07-05`; merged; refreshed card shown

### 9b — Restart (new request entirely)

| Turn | Type this exactly |
|------|-------------------|
| 1 | `I want to create a handover request` |
| 2 | `t0208831` |
| 3 | `Actually, start over` |
| 4 | *(Bot acknowledges; active_agent cleared)* |
| 5 | `I need to raise a handover for Zara Dubai` |
| 6 | Continue from Scenario 1, Turn 3 onward |

**What to expect:**
- **Turn 3** → "start over" matches `_CANCEL_WORKFLOW_PHRASES`; `active_agent` is cleared; `confirmation_status` reset; all Nike context gone
- **Turn 5** → Completely fresh intent classification ✅

---

## Scenario 10 — Ambiguous / Off-Topic Opening

**Goal:** Test that the supervisor asks for clarification on unclear messages.

| Turn | Type this exactly |
|------|-------------------|
| 1 | `hello` |
| 2 | *(Bot asks what you'd like to do)* |
| 3 | `I need to do something about a lease` |
| 4 | *(Bot asks to clarify — create, update, approve, or check status?)* |
| 5 | `create a new handover` |
| 6 | Continue from Scenario 1, Turn 2 onward |

---

## Scenario 11 — Natural Language Dates

**Goal:** Verify that human-friendly date formats are correctly extracted by the LLM.

| Turn | Type this exactly |
|------|-------------------|
| 1 | `Create a handover service request for t0105712` |
| 2 | `End-of-year fit-out handover for FF050 unit` |
| 3 | `Start on the first of November` |
| 4 | `End on November 3rd` |
| 5 | `FM Manager` |
| 6 | `Please confirm availability with FM team before scheduling` |
| 7 | `Confirm` |

**What to expect:**
- **Turn 3** → LLM extracts `startDate` from "first of November" → `2026-11-01`
- **Turn 4** → LLM extracts `endDate` from "November 3rd" → `2026-11-03` ✅

---

## Quick API Test (No UI Required)

Drive the full flow from the terminal to verify payload construction directly.

```bash
# ── Turn 1: state intent ──────────────────────────────────────────────────
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d '{"user_id":"tester","message":"I want to create a handover service request"}' \
  | jq '.'

# Copy the session_id from the response, then reuse it for every subsequent turn:
SESSION="<paste-session-id-here>"

# ── Turn 2: provide lease code ────────────────────────────────────────────
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"t0105712\"}" \
  | jq '{message,ui_type: .ui.type}'

# ── Turn 3: description (NO title turn any more) ───────────────────────────
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"Standard fit-out inspection for new tenant unit\"}" \
  | jq '{message,ui_type: .ui.type}'

# ── Turn 4: start date ────────────────────────────────────────────────────
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"2026-06-01\"}" \
  | jq '{message,ui_type: .ui.type}'

# ── Turn 5: end date ──────────────────────────────────────────────────────
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"2026-06-03\"}" \
  | jq '{message,ui_type: .ui.type}'

# ── Turn 6: inspection done by ────────────────────────────────────────────
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"FM Manager\"}" \
  | jq '{message,ui_type: .ui.type}'

# ── Turn 7: comments (triggers confirmation card) ─────────────────────────
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"Hard opening date June 5 please prioritise\"}" \
  | jq '{message,ui_type: .ui.type, title: .ui.fields[6].value}'

# ── Turn 8: confirm via action field (most reliable) ─────────────────────
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"Confirmed. Please submit.\",\"action\":\"confirm\"}" \
  | jq '{message, status: .state.workflow_stage}'

# ── Alternative Turn 8: confirm via plain text ────────────────────────────
# (works but action field is more reliable)
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"Confirm\"}" \
  | jq '{message, status: .state.workflow_stage}'
```

**Turn 7 expected response — verify auto-generated title:**
```json
{
  "message": "...",
  "ui_type": "confirmation_card",
  "title": "handover-t0105712-standard-fitout-inspection-for-new"
}
```

**Turn 8 expected response shape:**
```json
{
  "message": "Your Handover Service Request has been successfully submitted. Your reference number is <UUID>. ...",
  "status": "SR_CREATED"
}
```

### Testing `corrected_fields` (inline card edits) via API

```bash
# ── After seeing the confirmation card, send corrected fields + action confirm ──
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{
    \"user_id\": \"tester\",
    \"session_id\": \"$SESSION\",
    \"message\": \"Confirmed. Please submit.\",
    \"action\": \"confirm\",
    \"corrected_fields\": {\"endDate\": \"2026-06-05\", \"comments\": \"Updated comment\"}
  }" \
  | jq '{message, status: .state.workflow_stage}'
```

### Testing lease selection via API

```bash
# ── After a lease_selection card, send the chosen lease ID ──────────────
# Note: message must be at least 1 character; use the lease code as the
# message body — it is ignored when selected_lease_id is present.
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{
    \"user_id\": \"tester\",
    \"session_id\": \"$SESSION\",
    \"message\": \"t0208831\",
    \"selected_lease_id\": \"t0208831\"
  }" \
  | jq '{message, ui_type: .ui.type}'
```

---

## Request Body Reference

| Field | Type | Description |
|---|---|---|
| `user_id` | `string` (required) | Caller identifier |
| `session_id` | `string \| null` | Omit to start a new session; include to continue |
| `message` | `string` (required, min 1 char) | User's natural-language input |
| `action` | `"confirm" \| "cancel" \| null` | Bypasses text parsing: `"confirm"` → immediate submission; `"cancel"` → REJECTED |
| `selected_lease_id` | `string \| null` | Lease code chosen from a `lease_selection` card |
| `corrected_fields` | `object \| null` | Inline field edits from the confirmation card; merged into `collected_data` before validation |
| `attachments` | `array` | Optional file attachment metadata |

---

## Verifying the Payload in the Observability Dashboard

After any successful submission:

1. Open http://localhost:3000/admin/agent-observability
2. Find the trace for the conversation (most recent at top); traces are grouped by `session_id`
3. Click the trace → expand the **`api_submission`** run span
4. The **Tool Call** tab shows the exact JSON payload sent and the mock API response including `sr_id` and `correlation_id`
5. Under **State Snapshots → PAYLOAD_BUILDER_OUTPUT** you can see the full payload as built just before submission

---

## Post-Submit Checklist

- [ ] Chat UI shows a success message with a UUID SR reference number
- [ ] `state.workflow_stage` in the API response is `SR_CREATED`
- [ ] Observability trace shows all nodes completed (no red spans)
- [ ] `api_submission` tool call: `status_code = 201`, `sr_id` is a non-null UUID
- [ ] `PAYLOAD_BUILDER_OUTPUT` snapshot contains all fields from the payload reference above
- [ ] `title` in the payload matches `handover-{lease_code}-{description_slug}` format
- [ ] `inspection_done_by` in the payload is `FM_MANAGER` or `OPERATIONS` (not display text)
- [ ] Audit log entry `service_request.created` is present in the trace timeline
