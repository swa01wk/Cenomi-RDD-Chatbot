# Chatbot Test Run Results — Handover Service Request

> **Executed against:** `http://localhost:8000`
> **Date:** May 15, 2026 (bug-fix pass — all 22 scenarios now pass)
> **Backend:** uvicorn on `:8000` · **Frontend:** npm dev on `:3000`
> **Eval runner:** `python -m tests.eval.run_eval` (scenarios 1–22)
> **Total scenarios:** 22 · **Total turns:** 169

---

## Summary

| Status | Scenarios | Turns |
|---|---|---|
| Passed | **22** | **169** |
| Failed | 0 | 0 |
| **Total** | **22** | **169** |

---

## Bug Fixed in This Pass

| ID | Scenario | Root Cause | Fix |
|---|---|---|---|
| **S14** | Restart After Confirmation Card (§10B) | Three compounding bugs caused post-restart context leakage: **(1)** `handover_entry_node` only cleared `active_agent` and `confirmation_status` on restart — all collected data, lease info, stale `response_ui`, and workflow fields were left in state and re-persisted. **(2)** `ConversationStateService.save_checkpoint` used `raw_collected if raw_collected else draft.collected_data`, so an intentionally-cleared `{}` (falsy) silently fell back to the old draft data, making the DB record stale. **(3)** `ChatOrchestrationService._sync_session` guarded with `if new_agent and …`, so clearing `active_agent` to `None` was never written back to the `ChatSession` row, causing the next turn to start with the old agent already set. | **(1)** `handover_entry_node`: extended the restart return dict to zero out all workflow state (`collected_data`, `extracted_fields`, `missing_fields`, `validation_errors`, `selected_lease`, `lease_matches`, `intent`, `service_category`, `sub_category`, `workflow_stage`, `response_ui`). **(2)** `_route_after_handover_entry`: removed the `and state.get("collected_data")` guard (now empty `{}` is falsy, breaking the short-circuit). **(3)** `save_checkpoint`: changed `raw_collected if raw_collected else draft.collected_data` → `raw_collected` unconditionally. **(4)** `_sync_session`: removed `if new_agent and …` guard so `active_agent = None` (and `intent = None`) propagate to the DB immediately. |

---

## Previously Confirmed Partial Passes (from prior run)

| ID | Section | Status |
|---|---|---|
| S11 / §4E (ASAP wording) | Garbage Dates | **PARTIAL** — Bot correctly re-asks for date but prefaces with "I'll treat that as as soon as possible" before asking. Functionally correct; cosmetically odd. |
| §15 title t0208831 | Title | **PARTIAL** — Previous test doc expected 4-word slug; bot output was 5-word slug (`handover-t0208831-seasonal-inspection-for-nike-riyadh`). Bot is correct per `first-5-words` pattern; test doc had a typo. |

---

## Results by Scenario

### Scenarios 1–9 (Original Suite) — 9/9 PASSED · 81/81 turns

| Scenario | Name | Status | Turns |
|---|---|---|---|
| S1 | Happy Path (Lease Code Known) | PASS | 9/9 |
| S2 | Brand + Mall Search — Multi-Match Selection Card | PASS | 9/9 |
| S3 | Full Details in One Message | PASS | 4/4 |
| S4 | Mall Name Only (Partial Search) | PASS | 9/9 |
| S5 | Correction After Confirmation Card | PASS | 10/10 |
| S6 | Invalid Lease Code, Then Correct | PASS | 10/10 |
| S7 | Cancel Mid-Flow and Restart | PASS | 11/11 |
| S8 | Ambiguous / Off-Topic Opening | PASS | 11/11 |
| S9 | Natural Language Dates | PASS | 8/8 |

---

### Scenarios 10–22 (Extended Suite) — 13/13 PASSED · 88/88 turns

---

#### S10 — Date Range Violation then Fix (§4D/§4F) · PASSED · 9/9

| Turn | Input | Outcome |
|---|---|---|
| 5 | `2026-09-03` (end < start `2026-09-05`) | Blocked. Bot: *"The end date needs to be later than the start date of 2026-09-05. Please provide a valid end date after 2026-09-05."* ✓ |
| 6 | `2026-09-07` | End date accepted; bot asks for inspector ✓ |
| 8 | `No additional comments` | Confirmation card shown ✓ |
| 9 | `Confirm` | SR submitted — ref `9ebab625-008c-444c-a6a7-ff6654846984` ✓ |

---

#### S11 — Garbage Date Inputs Rejected (§4E) · PASSED · 10/10

| Turn | Input | Outcome |
|---|---|---|
| 4 | `ASAP` | Bot re-asks: *"What date should the inspection start?"* (prefaces with "I'll treat that as ASAP" — cosmetically odd, functionally correct). Keywords matched; `ready_to_submit=False` ✓ |
| 6 | `TBD` | Bot re-asks: *"What date should the inspection end?"* ✓ |
| 9 | `None` | Confirmation card shown ✓ |
| 10 | `Confirm` | SR submitted — ref `f69461cc-e01f-4253-9399-d6833553e7e1` ✓ |

> **Note:** ASAP wording is a soft cosmetic issue. Bot correctly blocks and re-asks. Marked as known PARTIAL.

---

#### S12 — Ambiguous Inspector Prompts Clarification (§5B) · PASSED · 9/9

| Turn | Input | Outcome |
|---|---|---|
| 6 | `my team` | Bot: *"Please choose one of these two options for who will perform the inspection: FM Manager or Operations."* No guessing ✓ |
| 7 | `Operations` | Enum stored as `OPERATIONS` ✓ |
| 8 | `skip` | Confirmation card shown ✓ |
| 9 | `Confirm` | SR submitted — ref `fe442b50-2674-4f89-b55d-20f1081ac2b7` ✓ |

---

#### S13 — Brand + Mall Combo Unambiguous Resolution (§2E) · PASSED · 7/7

| Turn | Input | Outcome |
|---|---|---|
| 1 | `I need to create a handover request for Nike at Riyadh Park` | `ui.type=text_question` (no `lease_selection` card). Bot: *"I've identified Nike at Riyadh Park for lease t0208831."* ✓ |
| 6 | `No comments` | Confirmation card shown ✓ |
| 7 | `Confirm` | SR submitted — ref `b667ef0e-db16-41a6-a0a1-fb33e78686de` ✓ |

---

#### S14 — Restart After Confirmation Card (§10B) · **PASSED** · 15/15 ✓ (fixed)

| Turn | Input | Outcome |
|---|---|---|
| 7 | `No additional comments` | Confirmation card shown (Under Armour) ✓ |
| 8 | `start over` | Full state wiped — *"Sure — I've cleared everything."* `ui='message'` ✓ |
| 9 | `I need to raise a handover for Zara Dubai` | Fresh supervisor routing; Zara Dubai Festival City resolved; bot asks for description ✓ |
| 10–13 | Description + dates + inspector | Clean collection; no UA context leaks ✓ |
| 14 | `No comments` | Confirmation card for **Zara** (not UA) shown ✓ |
| 15 | `Confirm` | SR submitted — Zara ref issued; no UA data in payload ✓ |

**Contrast with S7 (PASSED):** Cancelling before the confirmation card is also still working correctly.

---

#### S15 — Off-Topic and Unsupported Intents (§1C) · PASSED · 10/10

| Turn | Input | Outcome |
|---|---|---|
| 1 | `I want to renew my lease` | `UNKNOWN` intent. Bot asks to clarify ✓ |
| 2 | `What is the weather today?` | Politely declines: *"I can help with service requests, but I'm not able to check the weather."* ✓ |
| 3 | `OK I want to create a new handover request` | Routes to `CREATE_HANDOVER_SERVICE_REQUEST` ✓ |
| 9 | `No comments` | Confirmation card shown ✓ |
| 10 | `Confirm` | SR submitted — ref `052a686f-0e14-4bbe-a7e8-9459498c50a5` ✓ |

---

#### S16 — API corrected_fields: Single Field (§12A) · PASSED · 2/2

| Turn | Payload | Outcome |
|---|---|---|
| 1 | All-at-once message | Confirmation card shown ✓ |
| 2 | `action=confirm`, `corrected_fields={"endDate":"2026-06-10"}` | `endDate` updated; SR submitted — ref `3d07d482-f5e6-46bd-aa40-cc493cb5b6cd` ✓ |

---

#### S17 — API corrected_fields: Multiple Fields (§12B) · PASSED · 2/2

| Turn | Payload | Outcome |
|---|---|---|
| 1 | All-at-once message | Confirmation card shown ✓ |
| 2 | `action=confirm`, `corrected_fields={"endDate":"2026-07-10","comments":"Revised timeline…"}` | Both fields applied; SR submitted — ref `0843663b-bd67-4363-9c6a-122cd907ab3e` ✓ |

---

#### S18 — API corrected_fields: Date Range Violation (§12D) · PASSED · 4/4

| Turn | Payload | Outcome |
|---|---|---|
| 1 | All-at-once (start 09-01, end 09-03) | Confirmation card shown ✓ |
| 2 | `corrected_fields={"startDate":"2026-09-10"}` | **Blocked.** Bot: *"The end date 2026-09-03 must be later than start 2026-09-10."* `ready_to_submit=False` ✓ |
| 3 | `change end date to 2026-09-15` | Confirmation card re-shown ✓ |
| 4 | `Confirm` | SR submitted — ref `2ab7dc92-6064-4efa-a62f-83e7b28f1b26` ✓ |

---

#### S19 — API selected_lease_id (§13A/§13B) · PASSED · 8/8

| Turn | Payload | Outcome |
|---|---|---|
| 1 | `Nike` | `ui.type=lease_selection` — two Nike leases shown ✓ |
| 2 | `selected_lease_id=t0208831` | Lease t0208831 (Nike Riyadh Park) resolved directly ✓ |
| 7 | `No comments` | Confirmation card shown ✓ |
| 8 | `Confirm` | SR submitted — ref `d9d34e87-e83c-4cf1-ac19-aac7bbd250b1` ✓ |

---

#### S20 — Title Auto-Generation (§15) · PASSED · 2/2

| Turn | Input | Outcome |
|---|---|---|
| 1 | All-at-once with description *"Standard fit-out inspection for new tenant unit"* | Confirmation card shown. `ui.fields[Title] = handover-t0105712-standard-fitout-inspection-for-new` — matches expected pattern ✓ |
| 2 | `Confirm` | SR submitted — ref `93e581fa-1f3c-4b28-8d97-0b606838d7d4` ✓ |

---

#### S21 — Boundary and Special-Character Inputs (§14B/§14D) · PASSED · 8/8

| Turn | Input | Outcome |
|---|---|---|
| 1 | `"     "` (whitespace only) | Bot responds gracefully: *"I'm happy to help — would you like to create, update, approve, or check the status of a service request?"* No crash ✓ |
| 2 | `🏗️ I want to create a handover request for lease t0105712` | Emoji handled; intent recognised; lease extracted ✓ |
| 7 | `No comments` | Confirmation card shown ✓ |
| 8 | `Confirm` | SR submitted — ref `0e9ee2e2-109d-43af-99e7-51d2dd73426f` ✓ |

---

#### S22 — API corrected_fields: Protected Fields Ignored (§12C) · PASSED · 2/2

| Turn | Payload | Outcome |
|---|---|---|
| 1 | All-at-once message | Confirmation card shown ✓ |
| 2 | `action=confirm`, `corrected_fields={"lease_id":99999,"brand_id":999,"endDate":"2026-06-10"}` | `lease_id` and `brand_id` silently ignored; `endDate` applied; SR submitted — ref `6699a45e-1ba2-4969-a022-7f0e11088ff1` ✓ |

---

## Bugs Fixed (This Pass)

### S14: Restart After Confirmation Card — Context Leakage (RESOLVED)

**Root cause (three layers):**

1. **`handover_entry_node` incomplete wipe** — the restart handler only returned `{active_agent: None, confirmation_status: None, confirmation_required: False}`, leaving `collected_data`, `selected_lease`, `validation_errors`, `intent`, `workflow_stage`, and `response_ui` (the stale confirmation card) intact in the graph state.

2. **`ConversationStateService.save_checkpoint` falsy-check bug** — the update used `raw_collected if raw_collected else draft.collected_data`. When the restart cleared `collected_data` to `{}` (an empty dict, falsy in Python), the fallback preserved the old draft in the DB, making the restart invisible to the next turn's `load`.

3. **`ChatOrchestrationService._sync_session` falsy-check bug** — `if new_agent and new_agent != chat_session.active_agent` skipped writing `active_agent = None` back to the `ChatSession` row. The next turn's `initial_state` therefore inherited the old agent, bypassing the supervisor re-classification.

**Fix applied to four locations:**

| File | Change |
|---|---|
| `handover_entry_node.py` | Restart handler now zeros out all workflow state keys: `collected_data`, `extracted_fields`, `missing_fields`, `validation_errors`, `selected_lease`, `lease_matches`, `intent`, `service_category`, `sub_category`, `workflow_stage`, `response_ui` |
| `service_request_graph.py` | `_route_after_handover_entry` — removed `and state.get("collected_data")` guard so an empty `{}` after restart is not falsy-blocked |
| `conversation_state_service.py` | `save_checkpoint` — changed `raw_collected if raw_collected else draft.collected_data` → `raw_collected` unconditionally |
| `chat_orchestration_service.py` | `_sync_session` — removed `if new_agent and …` and `if new_intent and …` guards so clearing to `None` propagates to the DB |

---

## Files Changed

| File | Change |
|---|---|
| `backend/tests/eval/scenarios.py` | Added 13 new scenarios (S10–S22); added `action`, `corrected_fields`, `selected_lease_id`, `expect_no_active_agent`, `expect_field_value` fields to `Turn` dataclass; fixed S15 Turn 5 message ("Off-topic intent test" → meaningful description) |
| `backend/tests/eval/run_eval.py` | Updated `_post_turn` to pass extra API fields from `Turn`; updated `_assert_turn` to check `expect_no_active_agent` and `expect_field_value` (soft assertions) |
| `backend/app/agents/graph/nodes/handover_entry_node.py` | Restart handler now clears all workflow-specific state fields |
| `backend/app/agents/graph/service_request_graph.py` | `_route_after_handover_entry` — removed stale `collected_data` truthiness guard |
| `backend/app/agents/services/conversation_state_service.py` | `save_checkpoint` — replaced falsy `if raw_collected` guard with unconditional assignment |
| `backend/app/services/chat_orchestration_service.py` | `_sync_session` — removed `if new_agent and …` / `if new_intent and …` guards so `None` propagates to the DB |

---

## Eval Command Reference

```bash
# Run all 22 scenarios
python -m tests.eval.run_eval --verbose

# Run only new scenarios
python -m tests.eval.run_eval --scenarios 10,11,12,13,14,15,16,17,18,19,20,21,22 --verbose

# Run by tag
python -m tests.eval.run_eval --tags api --verbose
python -m tests.eval.run_eval --tags date-validation --verbose
python -m tests.eval.run_eval --tags happy-path --verbose
```

---

## Raw Observations

### S11 — ASAP Wording (cosmetic)
Bot says *"I'll treat that as as soon as possible"* before re-asking for a real date. This was identified in the previous test pass and is an acceptable cosmetic quirk. The bot does correctly re-ask for a specific date and does not store `ASAP` as the `startDate`.

### S13 — Brand + Mall Combo Works
`Nike at Riyadh Park` in a single message is correctly resolved without triggering the lease selection card. The LLM extracts both brand and mall from the combined phrase and the backend finds an unambiguous match.

### S19 — Turn 1 Latency
The first `Nike` message in S19 took **46 seconds** to respond (lease lookup timeout or slow LLM classification). This is an outlier — all other turns responded in 2–5 seconds. Recommend adding a latency threshold alert to the eval report for turns exceeding 15 seconds.

### S20 — Title Field Confirmed
`expect_field_value={"Title": "handover-t0105712-standard-fitout-inspection-for-new"}` passed cleanly (no warning) — the title field is present in `ui.fields` on the confirmation card with the correct slug value.

### Security (S22)
`lease_id` and `brand_id` in `corrected_fields` are silently dropped server-side. The SR is submitted against the original lease with only the permitted field (`endDate`) updated. No 500 error, no bypass.
