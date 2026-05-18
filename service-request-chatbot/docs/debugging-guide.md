# Debugging Guide

## Overview

This guide covers the practical steps to diagnose the most common failure modes in the Service Request Chatbot. Each section identifies what to look at, where to look, and what signals to interpret.

---

## How to Debug Failed Conversations

### Step 1: Get the `session_id` and `trace_id`

Every response from `POST /api/chat/service-request` includes:
```json
{
  "session_id": "550e8400-...",
  "trace_id": "abc123-..."
}
```

If you don't have these from the response, query the database:

```sql
-- Find recent sessions for a user
SELECT id, user_id, active_agent, intent, workflow_stage, status, updated_at
FROM chat_sessions
WHERE user_id = 'user-123'
ORDER BY updated_at DESC
LIMIT 10;
```

### Step 2: Inspect the audit log

The audit log records every turn start, turn completion, and security events without redaction:

```sql
SELECT event_type, metadata, created_at
FROM service_request_chat_audit_logs
WHERE session_id = '<session-id>'
ORDER BY created_at;
```

Key `event_type` values:

| Event | Meaning |
|-------|---------|
| `turn.started` | Turn began processing |
| `turn.completed` | Turn completed normally |
| `security.injection_attempt` | Injection guard fired — message was blocked |

If you see `security.injection_attempt`, the user message was rejected before any graph execution. The `metadata` field contains the scan score and matched patterns.

### Step 3: Check the draft state

```sql
SELECT workflow_stage, collected_data, missing_fields, documents, sr_id, service_request_status, ready_to_submit
FROM service_request_drafts
WHERE session_id = '<session-id>';
```

This tells you exactly what data was accumulated and what stage the workflow is at.

### Step 4: Correlate with traces

Use the trace to understand what the agent did in each turn. See "How to Inspect Traces" below.

---

## How to Inspect Traces

### Via Admin UI

Navigate to `http://localhost:3000/admin/agent-observability`.

1. Find the trace by `session_id` or time range in the trace list.
2. Click a trace to open the detail view with the full run tree.
3. Expand individual runs to see state snapshots, diffs, LLM calls, and tool calls.

### Via API

```bash
# List traces for a session
curl "http://localhost:8000/api/observability/traces?session_id=<session-id>"

# Get full trace detail
curl "http://localhost:8000/api/observability/traces/<trace-id>"
```

### Via SQL

```sql
-- All traces for a session
SELECT id, status, started_at, finished_at,
       EXTRACT(EPOCH FROM (finished_at - started_at)) * 1000 AS duration_ms
FROM agent_traces
WHERE session_id = '<session-id>'
ORDER BY started_at;

-- All runs for a trace
SELECT id, parent_run_id, name, run_type, status, latency_ms, started_at
FROM agent_runs
WHERE trace_id = '<trace-id>'
ORDER BY started_at;
```

### Interpreting trace status

| Trace status | Meaning |
|-------------|---------|
| `COMPLETED` | Graph ran to `save_state_node` normally |
| `FAILED` | Unhandled exception or injection guard triggered `fail_trace` |
| `RUNNING` | In-flight (or process crashed mid-turn — check `started_at` age) |

A trace stuck in `RUNNING` with `started_at` > 5 minutes ago indicates a crashed process. Safe to mark `FAILED` manually for audit purposes.

---

## How to Inspect State Diffs

State diffs show exactly what each graph node changed in the conversation state. This is the fastest way to understand why the agent behaved unexpectedly.

### Via Admin UI

In the trace detail view, open any run → click "State Diff" to see the before/after comparison for that node.

### Via SQL

```sql
-- Get all diffs for a trace's runs
SELECT ar.name AS node_name, asd.diff, asd.created_at
FROM agent_state_diffs asd
JOIN agent_runs ar ON asd.run_id = ar.id
WHERE ar.trace_id = '<trace-id>'
ORDER BY asd.created_at;
```

### Reading a diff

```json
{
  "added": {
    "intent": "CREATE_HANDOVER_SERVICE_REQUEST",
    "service_category": "FIT_OUT_AND_HANDOVER"
  },
  "removed": {},
  "changed": {
    "workflow_stage": {
      "before": null,
      "after": "CREATE_SR"
    }
  }
}
```

### Common diffs to look for

| Node | What to look for |
|------|-----------------|
| `supervisor` | `intent` added — is it correct? Is `confidence` above 0.6? |
| `field_extraction` | `extracted_fields` added — are expected fields present? |
| `merge_state` | `collected_data` updated — which fields made it past confidence threshold? |
| `validation` | `validation_errors` added — are there blocking errors? |
| `confirmation` | `confirmation_status` changed to `PENDING` |
| `handover_entry` | `confirmation_status` changed to `CONFIRMED` or `DENIED` |
| `payload_builder` | `backend_refs.create_payload` added |
| `api_submission` | `workflow_stage` changed to `SR_CREATED`, `status` to `SUBMITTED` |

---

## How to Debug Failed Lease Lookup

Lease lookup failures surface as `WAITING_FOR_USER` state with an error message, but no `lease_id` in `collected_data`.

### Step 1: Check the lease lookup run

```sql
SELECT ar.id, ar.status, ar.output, ar.latency_ms
FROM agent_runs ar
JOIN agent_traces at ON ar.trace_id = at.id
WHERE at.session_id = '<session-id>'
  AND ar.name = 'lease_lookup';
```

- `status = FAILED` → exception in lease lookup. Check `output` for error detail.
- `status = COMPLETED`, `output.status = "WAITING_FOR_USER"` → multiple leases found (disambiguation), or API returned empty list.

### Step 2: Check the tool call record

```sql
SELECT tc.tool_name, tc.input, tc.output, tc.latency_ms
FROM agent_tool_calls tc
JOIN agent_runs ar ON tc.run_id = ar.id
WHERE ar.name = 'lease_lookup'
  AND ar.trace_id = '<trace-id>';
```

The `input` shows the `user_id` and params sent to the Lease-Tenant API. The `output` shows the raw API response (redacted internal IDs). Check:

- Was the correct `user_id` sent?
- Did the API return a non-empty lease list?
- Did the API return an error status?

### Step 3: Check environment configuration

```bash
# Verify LEASE_TENANT_API_BASE_URL is set
grep LEASE_TENANT_API_BASE_URL backend/.env
```

An empty `LEASE_TENANT_API_BASE_URL` means the lease API client will fail with a connection error on every call.

### Step 4: Reproduce locally

```python
# Quick test in a Python shell
import asyncio
import httpx

async def test_lease_api():
    async with httpx.AsyncClient(base_url="<LEASE_TENANT_API_BASE_URL>") as client:
        r = await client.get("/leases", params={"user_id": "user-123"})
        print(r.status_code, r.json())

asyncio.run(test_lease_api())
```

---

## How to Debug Failed Submission

A failed submission means `api_submission_node` returned with `status = "FAILED"` instead of `"SUBMITTED"`.

### Step 1: Find the submission run

```sql
SELECT ar.id, ar.status, ar.output
FROM agent_runs ar
JOIN agent_traces at ON ar.trace_id = at.id
WHERE at.session_id = '<session-id>'
  AND ar.name = 'api_submission';
```

If `ar.status = "FAILED"`, the SR API call itself threw an exception. Check `ar.output` for the error message.

### Step 2: Check the tool call

```sql
SELECT tc.input, tc.output, tc.latency_ms
FROM agent_tool_calls tc
JOIN agent_runs ar ON tc.run_id = ar.id
WHERE ar.name = 'api_submission'
  AND ar.trace_id = '<trace-id>';
```

`tc.input` = the redacted payload that was sent. `tc.output` = the API response (error body on failure).

> **Note:** `tc.input` has `tenant_profile_id`, `property_id`, `brand_id`, `lease_id` replaced with `[REDACTED]`. You can get the real values from `service_request_drafts.collected_data`.

### Step 3: Check guard conditions

If the run never created a `TOOL` child run, the submission guard blocked it. Check the state snapshot for the `api_submission` run's `BEFORE_NODE`:

```sql
SELECT ass.state
FROM agent_state_snapshots ass
JOIN agent_runs ar ON ass.run_id = ar.id
WHERE ar.name = 'api_submission'
  AND ar.trace_id = '<trace-id>'
  AND ass.snapshot_type = 'BEFORE_NODE';
```

Verify:
- `confirmation_status = "CONFIRMED"` — if not, the guard blocked it.
- `validation_errors = []` — if there are blocking errors, the guard blocked it.
- `backend_refs.create_payload` is set — if missing, `payload_builder_node` didn't run or failed.

### Step 4: Verify `SERVICE_REQUEST_API_BASE_URL`

```bash
grep SERVICE_REQUEST_API_BASE_URL backend/.env
```

---

## How to Debug Validation Errors

Validation errors block the conversation from progressing to confirmation. Symptoms: the bot keeps asking for the same field or returns an error message about a field value.

### Step 1: Read `validation_errors` from state

```sql
SELECT collected_data, missing_fields
FROM service_request_drafts
WHERE session_id = '<session-id>';
```

Also check the most recent validation run output:

```sql
SELECT ar.output
FROM agent_runs ar
JOIN agent_traces at ON ar.trace_id = at.id
WHERE at.session_id = '<session-id>'
  AND ar.name = 'validation'
ORDER BY ar.started_at DESC
LIMIT 1;
```

`ar.output` contains the `validation_errors` list:
```json
[
  {
    "field": "endDate",
    "message": "End date must be after start date.",
    "blocking": true
  }
]
```

### Step 2: Check what the LLM extracted

Look at the `field_extraction` run's output for the failing turn:

```sql
SELECT ar.output
FROM agent_runs ar
JOIN agent_traces at ON ar.trace_id = at.id
WHERE at.session_id = '<session-id>'
  AND ar.name = 'field_extraction'
ORDER BY ar.started_at DESC
LIMIT 1;
```

Check `ar.output.extracted_fields` — are the fields there? What values did the LLM extract? What confidence scores?

### Step 3: Check merge output

Look at the `merge_state` run's `AFTER_NODE` snapshot to confirm which fields made it into `collected_data`:

```sql
SELECT ass.state -> 'collected_data' AS collected_data_after_merge
FROM agent_state_snapshots ass
JOIN agent_runs ar ON ass.run_id = ar.id
JOIN agent_traces at ON ar.trace_id = at.id
WHERE at.session_id = '<session-id>'
  AND ar.name = 'merge_state'
  AND ass.snapshot_type = 'AFTER_NODE'
ORDER BY ass.created_at DESC
LIMIT 1;
```

If a field the user provided is **not** in `collected_data` after merge, it either:
1. Had confidence below `0.6` — the LLM wasn't confident enough in the extraction.
2. Is a `BACKEND_ONLY_FIELD` — it was stripped by `HandoverExtractedFields` (check `handover_schema.py`).
3. The user's phrasing didn't trigger extraction for that field.

### Step 4: Reproduce with a unit test

```python
# backend/tests/unit/test_validation_node.py pattern
async def test_end_date_before_start_date():
    state = {
        "collected_data": {
            "startDate": "2026-06-15",
            "endDate": "2026-06-01",   # before startDate
            # ... other required fields
        },
        "workflow_stage": "CREATE_SR",
    }
    result = await validation_node(state)
    assert any(
        e["field"] == "endDate" and e["blocking"]
        for e in result["validation_errors"]
    )
```

---

## Quick Reference: Node-to-Table Mapping

| Node | DB Table | Key columns |
|------|----------|------------|
| `load_session_node` | `service_request_drafts` | `collected_data`, `workflow_stage` |
| `supervisor_node` | `agent_runs` (run_type=SUPERVISOR) + `agent_llm_calls` | `output.intent`, `output.confidence` |
| `field_extraction_node` | `agent_runs` + `agent_llm_calls` | `output.extracted_fields` |
| `merge_state_node` | `agent_state_diffs` | `diff.changed.collected_data` |
| `lease_lookup_node` | `agent_tool_calls` | `tool_name`, `output` |
| `validation_node` | `agent_runs` | `output.validation_errors` |
| `confirmation_node` | `agent_state_snapshots` | `snapshot_type=AFTER_NODE`, `state.confirmation_status` |
| `api_submission_node` | `agent_tool_calls` | `tool_name=create_service_request`, `input`, `output` |
| `save_state_node` | `service_request_drafts` | All draft columns updated |
