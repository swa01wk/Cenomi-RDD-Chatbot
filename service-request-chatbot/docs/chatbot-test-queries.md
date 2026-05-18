# Chatbot Test Queries — Handover Service Request

> **Purpose:** Exhaustive catalogue of chat inputs to manually or programmatically test the chatbot across happy paths, edge cases, adversarial inputs, and broken/invalid combinations.  
> **Mock leases available:**
>
> | Code | Brand | Mall | City | Units | Area |
> |---|---|---|---|---|---|
> | `t0105712` | Brand Under Armour | Jawharat Jeddah | Jeddah | FF050 | 420 |
> | `t0208831` | Nike | Riyadh Park | Riyadh | GF101, GF102 | 680 |
> | `t0301144` | Nike | Mall of Arabia | Jeddah | LG220 | 510 |
> | `t0419977` | Zara | Dubai Festival City | Dubai | UF301 | 900 |

---

## 1. Intent Recognition

### 1A — Clear intents the bot should accept immediately

```
I want to create a handover service request
```
```
Please help me raise a handover SR
```
```
Create a handover for my tenant
```
```
I need to submit a handover inspection request
```
```
Can you open a new handover request for me?
```
```
New handover service request please
```
```
Handover SR
```

**Expected:** Bot routes to `CREATE_HANDOVER_SERVICE_REQUEST`, asks for lease identifier.

---

### 1B — Ambiguous openers (should ask for clarification)

```
hello
```
```
hi there
```
```
help
```
```
I need to do something about a lease
```
```
What can you do?
```
```
I want to do something with my unit
```
```
service request
```
```
I have an issue
```

**Expected:** Bot asks what the user wants to do (create / update / approve / check status).

---

### 1C — Off-topic or unsupported intents

```
What is the weather today?
```
```
Tell me a joke
```
```
I want to renew my lease
```
```
Can you approve my invoice?
```
```
Book a meeting room for me
```
```
Who is the CEO of Cenomi?
```

**Expected:** Bot politely declines or asks if the user wants to create a service request instead.

---

## 2. Lease Identification

### 2A — Exact lease code (single match)

```
t0105712
```
```
t0208831
```
```
t0301144
```
```
t0419977
```
```
The lease code is t0105712
```
```
My lease is t0419977
```

**Expected:** Lease auto-resolved, bot asks for description.

---

### 2B — Brand name search (single match)

```
Under Armour
```
```
Zara
```
```
Brand Under Armour
```
```
The brand is Zara
```

**Expected:** Single match found, bot auto-fills lease and continues.

---

### 2C — Brand name search (multiple matches — selection card)

```
Nike
```
```
The brand is Nike
```
```
Nike store
```

**Expected:** Two Nike leases found (`t0208831` Riyadh Park + `t0301144` Mall of Arabia); lease selection card shown with both options.

---

### 2D — Mall name only

```
Jawharat Jeddah
```
```
Jawharat Jeddah mall
```
```
Riyadh Park
```
```
Dubai Festival City
```
```
Mall of Arabia
```

**Expected:** Single lease at that mall resolved automatically.

---

### 2E — Brand + Mall combination

```
Nike at Riyadh Park
```
```
Under Armour Jawharat Jeddah
```
```
Zara in Dubai Festival City
```
```
Nike Mall of Arabia
```

**Expected:** Unambiguous match resolved directly (no selection card needed).

---

### 2F — Case / spacing variations

```
T0105712
```
```
t0 105712
```
```
under armour
```
```
ZARA
```
```
riyadh park
```
```
JAWHARAT JEDDAH
```

**Expected:** Bot should normalise and resolve correctly.

---

### 2G — Broken / invalid lease codes

```
LC-TEST-999
```
```
XYZ123
```
```
00000000
```
```
t01
```
```
123456789012345
```
```
@#$%^&
```
```
lease code is definitely correct trust me
```

**Expected:** Bot says no match found and asks to try again.

---

### 2H — Unknown brand / mall

```
H&M
```
```
Starbucks
```
```
City Walk Dubai
```
```
Al Nakheel Mall
```

**Expected:** No matches returned; bot asks to try again or provide lease code directly.

---

## 3. Description

### 3A — Valid descriptions

```
Standard fit-out inspection for new tenant unit
```
```
Annual inspection for Nike flagship store
```
```
Pre-opening handover check for all units
```
```
Final walkthrough before tenant moves in
```
```
Zara fit-out complete — requesting formal handover inspection
```
```
Post-construction inspection required before soft opening
```

**Expected:** Description stored; bot asks for start date.

---

### 3B — Very short descriptions (edge case)

```
inspection
```
```
handover
```
```
check
```
```
ok
```
```
.
```

**Expected:** Bot should accept any non-empty string as description.

---

### 3C — Very long descriptions

```
This is a comprehensive fit-out handover inspection for the Under Armour flagship unit at Jawharat Jeddah mall. The tenant has completed all fit-out works including flooring, lighting, signage, air conditioning, fire suppression, and electrical installations. The inspection is expected to cover all aspects of the fit-out as specified in the lease agreement schedule of works, and should be conducted by a qualified FM Manager with authority to sign off on the fit-out completion certificate. All outstanding snagging items must be documented and a re-inspection date must be agreed before the certificate is issued.
```

**Expected:** Description accepted (no length limit enforced by the bot).

---

### 3D — Description with special characters

```
Fit-out inspection for unit FF050 — 420 sqm, 3rd floor (north wing)
```
```
"Quick" inspection before June 5 opening
```
```
Inspection: Phase 2 & 3 fit-out works (level B1)
```

**Expected:** Stored verbatim; no issues with dashes, quotes, ampersands.

---

## 4. Dates

### 4A — ISO format (YYYY-MM-DD)

```
2026-06-01
```
```
2026-07-15
```
```
2026-11-01
```
```
2027-01-01
```

**Expected:** Parsed and stored correctly.

---

### 4B — Natural language dates

```
June 1st
```
```
1st of June
```
```
first of June 2026
```
```
June 1, 2026
```
```
1 June
```
```
next Monday
```
```
end of next month
```
```
November 3rd
```
```
the third of November
```
```
3rd Nov
```
```
March 15
```

**Expected:** LLM extracts and normalises to `YYYY-MM-DD` (relative dates like "next Monday" should be resolved relative to current date).

---

### 4C — Date range validation — valid pairs

| Start | End | Expected |
|---|---|---|
| `2026-06-01` | `2026-06-03` | ✅ Valid |
| `2026-06-01` | `2027-06-01` | ✅ Valid (1 year apart) |
| `2026-01-01` | `2026-01-02` | ✅ Valid (next day) |
| `June 10` | `June 12 2026` | ✅ Valid |

---

### 4D — Date range validation — invalid pairs (should block submission)

| Start | End | Expected |
|---|---|---|
| `2026-06-05` | `2026-06-03` | ❌ Start after end |
| `2026-06-03` | `2026-06-03` | ❌ Equal dates |
| `2025-01-01` | `2025-01-03` | ❌ Dates in the past (if past-date validation is active) |

**Expected:** Blocking validation error; bot asks user to correct the date(s).

---

### 4E — Garbage date inputs

```
tomorrow
```
```
soon
```
```
ASAP
```
```
don't know yet
```
```
TBD
```
```
June 40th
```
```
13/13/2026
```
```
99-99-9999
```
```
the day after never
```

**Expected:** LLM either asks again or stores `null`; bot re-asks for a valid date.

---

### 4F — Multi-message date correction

1. Type `2026-09-05` as start date
2. Then for end date, type `2026-09-03` ← intentionally before start
3. Bot should surface blocking validation error
4. Then type `2026-09-07` to correct

**Expected:** After step 4, validation clears and confirmation card appears.

---

## 5. Inspection Done By

### 5A — All valid inputs and their expected enum values

| Input | Expected enum |
|---|---|
| `FM Manager` | `FM_MANAGER` |
| `fm manager` | `FM_MANAGER` |
| `FM manager` | `FM_MANAGER` |
| `The FM Manager` | `FM_MANAGER` |
| `FM team` | `FM_MANAGER` |
| `facility management` | `FM_MANAGER` |
| `Operations` | `OPERATIONS` |
| `operations team` | `OPERATIONS` |
| `ops` | `OPERATIONS` |
| `ops team` | `OPERATIONS` |
| `the operations department` | `OPERATIONS` |
| `by our operations guys` | `OPERATIONS` |

**Expected:** Card always shows `FM_MANAGER` or `OPERATIONS`, never the display text.

---

### 5B — Ambiguous or unknown inspector

```
my team
```
```
John from facilities
```
```
the contractor
```
```
not sure yet
```
```
whoever is available
```
```
the third party inspector
```

**Expected:** Bot asks to clarify — FM Manager or Operations.

---

## 6. Comments

### 6A — Non-empty comments

```
Please prioritise — hard opening date is June 5
```
```
Tenant has requested access from July 9 — confirm availability with ops team
```
```
Both GF101 and GF102 must be inspected together in the same visit
```
```
Need sign-off by end of month for insurance purposes
```

**Expected:** Stored verbatim.

---

### 6B — Explicit "no comments" inputs (should store empty string, not re-ask)

```
No comments
```
```
No additional comments
```
```
None
```
```
N/A
```
```
nothing to add
```
```
skip
```
```
No
```
```
(empty — just press enter / send blank)
```

**Expected:** `comments` stored as `""` or `"None"` normalised to `""`. Confirmation card shown; bot does NOT re-ask.

---

## 7. All-at-Once Queries (Multi-field Extraction)

### 7A — Entire request in one message

```
Create a handover service request for lease t0105712 — description: Standard fit-out inspection for new tenant unit. The inspection runs from June 1 to June 3 2026 and will be done by FM Manager. No additional comments.
```

```
New handover SR: lease t0419977, Zara Dubai. Description: Final pre-opening fit-out check. Start June 10, end June 12 2026. Operations team will inspect. No comments needed.
```

```
I want to raise a handover for t0208831. It's a seasonal inspection for Nike Riyadh Park. Start date 2026-09-01, end 2026-09-03. Done by Operations. Units GF101 and GF102 both need inspection.
```

```
Handover request for Under Armour at Jawharat Jeddah (t0105712), description: end of fit-out walkthrough, from November 1 to November 3 2026, FM Manager, no comments.
```

**Expected:** Confirmation card appears on this single turn with all fields pre-filled.

---

### 7B — Lease + description in opener, rest in follow-ups

Turn 1:
```
Create a handover service request for t0301144 — Nike Mall of Arabia. Description: pre-opening inspection for LG220.
```
Turn 2:
```
2026-08-01 to 2026-08-03, FM Manager, no comments
```

**Expected:** Turn 1 sets lease + description. Turn 2 fills all remaining fields at once → confirmation card.

---

### 7C — Lease only in opener

Turn 1:
```
Create a handover service request for Zara Dubai
```
Turn 2:
```
New tenant fit-out handover for flagship unit. Starts June 10, ends June 12 2026, Operations, no comments.
```

**Expected:** Turn 1 resolves lease t0419977. Turn 2 fills description + dates + inspector + comments → confirmation card.

---

### 7D — Partial over-provision (extra fields the bot wasn't asking for)

During start-date turn, send:
```
Start date is 2026-07-10, end is 2026-07-12, and it will be done by FM Manager
```

**Expected:** All three fields captured simultaneously; bot only asks for the remaining missing field (comments).

---

## 8. Correction Flows

### 8A — Text correction after confirmation card appears

After card appears, send:
```
Actually, change the end date to 2026-08-05
```
```
I need to update the description — it should say "Annual pre-opening inspection for LG220"
```
```
Change inspector to Operations
```
```
Update comments to: Tenant has requested early access from the day before
```
```
The start date is wrong — it should be 2026-06-15
```

**Expected:** Card re-appears with the corrected field. Status remains PENDING.

---

### 8B — Multiple corrections in one message

```
Change end date to 2026-08-10 and inspector to Operations
```
```
Update start date to 2026-07-20 and comments to urgent — hard opening on July 25
```

**Expected:** Both fields updated simultaneously; refreshed card shown.

---

### 8C — Correction that creates a new validation error

Start with valid card (`startDate: 2026-07-01`, `endDate: 2026-07-03`), then send:
```
Change the start date to 2026-07-05
```

**Expected:** Validation error — start date now after end date. Bot asks user to fix the end date before submitting.

---

### 8D — Cancel button then provide correction

1. Reach confirmation card
2. Click **Cancel** (or type `Cancel`)
3. Type: `Change the start date to 2026-06-15`

**Expected:** After step 2 bot asks what to change. After step 3 the corrected card appears with the new start date.

---

### 8E — Cancel button then re-confirm without changes

1. Reach confirmation card
2. Click **Cancel**
3. Type: `Actually it's all fine, confirm`

**Expected:** Bot re-shows card; on "confirm" the SR is submitted successfully.

---

## 9. Confirmation & Submission

### 9A — All valid confirmation inputs (text-only, no action field)

```
Confirm
```
```
Yes
```
```
Yes please
```
```
Submit
```
```
Looks good
```
```
Go ahead
```
```
That's correct
```
```
Proceed
```
```
OK
```
```
Approve
```

**Expected:** SR submitted, UUID returned.

---

### 9B — All valid rejection inputs (text-only)

```
No
```
```
Cancel
```
```
Change something
```
```
Edit
```
```
That's wrong
```
```
Fix it
```

**Expected:** `confirmation_status` → `REJECTED`; bot asks what to change (card stays, no submission).

---

### 9C — Ambiguous confirmation response

```
maybe
```
```
I guess
```
```
not sure
```
```
hmm
```

**Expected:** Bot asks "Please reply with 'yes' to confirm or tell me what you'd like to change."

---

### 9D — Confirm with `action: "confirm"` field (API)

Send with `"action": "confirm"` in request body alongside any message.

**Expected:** Submitted unconditionally regardless of message text.

---

### 9E — Cancel with `action: "cancel"` field (API)

Send with `"action": "cancel"` in request body.

**Expected:** `confirmation_status` → `REJECTED`; bot asks what to change.

---

## 10. Restart / Session Reset

### 10A — Restart phrases mid-flow (before confirmation card)

```
start over
```
```
restart
```
```
new request
```
```
begin again
```
```
reset
```
```
different request
```

**Expected:** `active_agent` cleared; all context erased; bot asks what to do next.

---

### 10B — Restart after confirmation card appears

1. Reach confirmation card
2. Type: `start over`

**Expected:** Card dismissed; all data cleared; bot starts fresh. On next message the user should be able to open a completely different handover.

---

### 10C — Restart then immediately open a different handover

Turn 1:
```
I want to create a handover request for Nike Riyadh Park
```
*(Reaches lease resolution for t0208831)*

Turn 2:
```
start over
```

Turn 3:
```
I need to raise a handover for Zara Dubai
```

**Expected:** Turn 3 correctly classifies a new intent and resolves t0419977 — no Nike context leaks through.

---

## 11. Session Continuity

### 11A — Continue a session with an explicit `session_id`

1. Start a request, get `session_id` from response
2. Send Turn 2 with the same `session_id`

**Expected:** Bot remembers lease and collected fields from Turn 1.

---

### 11B — Omit `session_id` on every turn

Send each turn without `session_id`.

**Expected:** Each turn is a completely new session; bot starts from scratch on every message.

---

### 11C — Send wrong `session_id`

Use a made-up UUID such as `00000000-0000-0000-0000-000000000000`.

**Expected:** No prior state found; bot treats it as a new session.

---

## 12. Inline Card Edits (`corrected_fields` API)

### 12A — Single field correction

```json
"corrected_fields": {"endDate": "2026-08-05"}
```

**Expected:** `endDate` updated; SR submitted with new value.

---

### 12B — Multiple fields corrected simultaneously

```json
"corrected_fields": {
  "endDate": "2026-08-10",
  "comments": "Revised timeline — tenant now opens August 12"
}
```

**Expected:** Both fields updated; SR submitted with both corrections applied.

---

### 12C — Correcting a backend-protected field (should be ignored)

```json
"corrected_fields": {
  "lease_id": 99999,
  "brand_id": 999,
  "endDate": "2026-08-05"
}
```

**Expected:** `lease_id` and `brand_id` are silently ignored; only `endDate` is applied.

---

### 12D — `corrected_fields` that create a date range violation

```json
"corrected_fields": {"startDate": "2026-09-10"}
```
*(When endDate is 2026-09-03)*

**Expected:** Blocking validation error; SR not submitted; bot asks to fix the dates.

---

## 13. Selected Lease via API (`selected_lease_id`)

### 13A — Valid selection

After Nike lease selection card, send:
```json
"selected_lease_id": "t0208831",
"message": "t0208831"
```

**Expected:** Lease t0208831 resolved; bot asks for description.

---

### 13B — Select the other Nike lease

```json
"selected_lease_id": "t0301144",
"message": "t0301144"
```

**Expected:** Lease t0301144 (Mall of Arabia) resolved.

---

### 13C — `selected_lease_id` for an unrelated lease (not in the match list)

```json
"selected_lease_id": "t0419977",
"message": "t0419977"
```
*(When the card showed Nike leases, not Zara)*

**Expected:** Bot still resolves t0419977 via lease-code lookup (fallback Path B); does not error.

---

### 13D — Invalid / non-existent `selected_lease_id`

```json
"selected_lease_id": "t9999999",
"message": "t9999999"
```

**Expected:** Zero matches from lookup; bot says lease not found and asks again.

---

## 14. Boundary & Stress Inputs

### 14A — Empty message body (API)

```json
{"user_id": "tester", "message": "a"}
```
*(Minimum valid message)*

**Expected:** Accepted; bot responds.

---

### 14B — Message with only whitespace

```
     
```

**Expected:** Bot either ignores or asks for a real message.

---

### 14C — Extremely long message (>5000 chars)

Send a 5000-character string.

**Expected:** Bot handles gracefully — no 500 error, responds or truncates.

---

### 14D — Special characters and Unicode

```
I want to create a handover request 🏗️ for lease t0105712
```
```
تفضل إنشاء طلب تسليم للإيجار t0105712
```
```
<script>alert('xss')</script>
```
```
'; DROP TABLE service_requests; --
```

**Expected:** Bot responds correctly; no XSS or injection effects; Arabic text handled without crash.

---

### 14E — Repeated identical turns

Send the same message 5 times in a row within the same session:
```
t0105712
```

**Expected:** Bot does not double-apply the lease; responds consistently on each turn.

---

### 14F — All fields squeezed into one extreme message

```
I want to raise a handover service request for t0105712 Brand Under Armour Jawharat Jeddah. Description: complete pre-opening fit-out inspection and snagging review for unit FF050. Start date is 2026-06-01, end date is 2026-06-03. It will be done by FM Manager. Comments: hard opening date is June 5, please prioritise and coordinate directly with the tenant fit-out manager.
```

**Expected:** All fields extracted in one shot; confirmation card appears on first turn.

---

## 15. Title Auto-Generation Verification

Run the following and confirm the `title` field in the confirmation card matches the pattern `handover-{lease_code}-{first-5-words-of-description-as-slug}`:

| Lease | Description input | Expected title |
|---|---|---|
| `t0105712` | `Standard fit-out inspection for new tenant unit` | `handover-t0105712-standard-fitout-inspection-for-new` |
| `t0419977` | `New tenant fit-out handover for Zara flagship unit UF301` | `handover-t0419977-new-tenant-fitout-handover-for` |
| `t0208831` | `Seasonal inspection for Nike Riyadh Park units` | `handover-t0208831-seasonal-inspection-for-nike` |
| `t0301144` | `Annual walkthrough` | `handover-t0301144-annual-walkthrough` |

---

## 16. Observability Verification (Post-Submission Checklist)

After any successful submission, verify the following in the [observability dashboard](http://localhost:3000/admin/agent-observability):

- [ ] Trace for the session appears at the top of the list
- [ ] All graph nodes show green (no red spans)
- [ ] `api_submission` tool call has `status_code: 201` and a non-null `sr_id` UUID
- [ ] `PAYLOAD_BUILDER_OUTPUT` state snapshot contains all fields from the API payload reference
- [ ] `title` in payload matches `handover-{lease_code}-{description_slug}`
- [ ] `inspection_done_by` in payload is `FM_MANAGER` or `OPERATIONS` (not display text)
- [ ] `audit_log` entry `service_request.created` is present in the trace timeline
- [ ] `workflow_stage` in API response is `SR_CREATED`

---

## 17. Quick Reference — API Test Sequences

All sequences use `http://localhost:8000/api/chat/service-request`. Copy a block, run Turn 1, capture `session_id`, then run subsequent turns.

### Full happy path (curl)

```bash
# Turn 1
SESSION=$(curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d '{"user_id":"tester","message":"I want to create a handover service request"}' \
  | jq -r '.session_id')
echo "Session: $SESSION"

# Turn 2 — lease
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"t0105712\"}" | jq '{message}'

# Turn 3 — description
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"Standard fit-out inspection for new tenant unit\"}" | jq '{message}'

# Turn 4 — start date
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"2026-06-01\"}" | jq '{message}'

# Turn 5 — end date
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"2026-06-03\"}" | jq '{message}'

# Turn 6 — inspector
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"FM Manager\"}" | jq '{message}'

# Turn 7 — comments + triggers card
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"Hard opening June 5, please prioritise\"}" \
  | jq '{message, ui_type: .ui.type, title: (.ui.fields[]? | select(.label=="Title") | .value)}'

# Turn 8 — confirm
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"Confirm\",\"action\":\"confirm\"}" \
  | jq '{message, status: .state.workflow_stage}'
```

---

### All fields in one shot (curl)

```bash
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "tester",
    "message": "Create a handover service request for lease t0419977 — description: New tenant fit-out handover for Zara flagship unit UF301. The inspection runs from June 10 to June 12 2026 and will be done by FM Manager. No additional comments."
  }' | jq '{message, ui_type: .ui.type, fields: [.ui.fields[]? | {label, value}]}'
```

---

### Invalid lease then correct (curl)

```bash
SESSION=$(curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d '{"user_id":"tester","message":"I want to create a handover request"}' | jq -r '.session_id')

# Bad lease
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"LC-FAKE-999\"}" | jq '{message}'

# Correct it
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"Sorry, the correct code is t0208831\"}" | jq '{message}'
```

---

### Date range violation then fix (curl)

```bash
# (Assumes session is at the start-date turn)
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"2026-09-05\"}" | jq '{message}'

# End date before start — triggers validation error
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"2026-09-03\"}" | jq '{message, missing_fields: .state.missing_fields}'

# Correct the end date
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"2026-09-07\"}" | jq '{message, ui_type: .ui.type}'
```

---

### Start over mid-flow (curl)

```bash
SESSION=$(curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d '{"user_id":"tester","message":"I want to create a handover request"}' | jq -r '.session_id')

curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"t0208831\"}" | jq '{message}' 

# Restart mid-flow
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"start over\"}" \
  | jq '{message, active_agent: .active_agent}'

# Fresh intent — should resolve Zara, not Nike
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"tester\",\"session_id\":\"$SESSION\",\"message\":\"I need to raise a handover for Zara Dubai\"}" \
  | jq '{message}'
```

---

### Inline card edit via `corrected_fields` (curl)

```bash
# (Assumes $SESSION is at the confirmation card stage)
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{
    \"user_id\": \"tester\",
    \"session_id\": \"$SESSION\",
    \"message\": \"Confirmed\",
    \"action\": \"confirm\",
    \"corrected_fields\": {
      \"endDate\": \"2026-06-05\",
      \"comments\": \"Revised — hard opening pushed to June 7\"
    }
  }" | jq '{message, status: .state.workflow_stage}'
```

---

### Lease selection via `selected_lease_id` (curl)

```bash
SESSION=$(curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d '{"user_id":"tester","message":"I need to raise a handover request for Nike"}' | jq -r '.session_id')

# Select Nike Riyadh Park
curl -s -X POST http://localhost:8000/api/chat/service-request \
  -H "Content-Type: application/json" \
  -d "{
    \"user_id\": \"tester\",
    \"session_id\": \"$SESSION\",
    \"message\": \"t0208831\",
    \"selected_lease_id\": \"t0208831\"
  }" | jq '{message, ui_type: .ui.type}'
```
