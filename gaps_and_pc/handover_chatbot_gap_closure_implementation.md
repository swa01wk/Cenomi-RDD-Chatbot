# Handover Service Request Chatbot — Gap Closure Implementation Document

## Purpose

This document captures the implementation gaps between the current chatbot architecture and the expected Handover Service Request platform workflow represented in the Postman collection.

The goal is to use this document together with the Postman collection in Cursor to review and complete the implementation.

---

## 1. Target Objective

The chatbot should not only collect form fields. It should act as a conversational workflow assistant that:

1. Understands the user's service request intent.
2. Identifies the correct service request workflow.
3. Collects required datapoints through natural conversation.
4. Resolves backend-derived fields from platform APIs.
5. Validates user-provided and system-derived data.
6. Uploads required documents using platform file endpoints.
7. Builds the exact platform-compatible payload.
8. Calls the correct platform endpoints.
9. Tracks service request status across workflow stages.
10. Continues the conversation based on the current workflow stage and user role.

The chatbot should eventually replace the manual form-filling and manual API/Postman workflow.

---

## 2. Expected End-to-End Platform Flow

The Postman collection represents the full Handover Service Request lifecycle.

```text
Login
  ↓
Fetch Handover workflow/form schema
  ↓
Mall Manager creates Handover SR
  ↓
FM Manager / Operations uploads checklist/site survey documents
  ↓
FM Manager / Operations saves progress as IN_PROCESS
  ↓
FM Manager / Operations approves
  ↓
DD Engineer / RDD PM uploads handover report
  ↓
DD Engineer / RDD PM submits report as REPORT_SUBMITTED
  ↓
Platform updates workflow status
```

The chatbot must eventually support this same sequence through conversation and UI actions.

---

## 3. Current High-Level Gap

Current implementation is mainly aligned to:

```text
CREATE_SR
```

But the Postman workflow requires:

```text
CREATE_SR
  → FM_REVIEW
  → RDD_REVIEW
  → REPORT_SUBMITTED / COMPLETED
```

So the major gap is:

> The chatbot currently behaves mainly like a CREATE_SR data-collection agent, but the platform workflow requires a full lifecycle agent that can create, update, upload documents, approve, submit reports, and sync status with the platform.

---

## 4. Required Platform Endpoints

The chatbot backend should use the following platform endpoints.

### 4.1 Login

```http
POST /cenomi-ai/login
```

Headers:

```http
Content-Type: application/json
x-internal-api-token: {{internal_api_token}}
```

Body:

```json
{
  "email": "{{login_email}}"
}
```

Expected response:

```json
{
  "success": true,
  "data": {
    "access_token": "..."
  }
}
```

Implementation requirement:

- Authenticate user/session before platform operations.
- Store access token for the session or request context.
- Use Bearer token for downstream service request/file APIs.

---

### 4.2 Fetch Workflow/Form Schema

```http
GET /service-requests/workflows?service_category=FIT_OUT_AND_HANDOVER&sub_category=HANDOVER&sort_by=updated_at&order=ASC
```

Implementation requirement:

- Use this to verify the Handover workflow schema.
- Optionally cache workflow schema.
- Ensure chatbot schema matches platform schema.

---

### 4.3 Create Handover Service Request

```http
POST /service-requests
```

Used during `CREATE_SR`.

Important:

- Do not send top-level `status` during initial create.
- Backend/platform should default workflow status.
- Response returns `service_request_id`.

Expected response:

```json
{
  "success": true,
  "data": {
    "service_request_id": "10197"
  }
}
```

---

### 4.4 Get Service Request By ID

```http
GET /service-requests/{{sr_id}}
```

Used for:

- Refreshing latest platform state.
- Reading `service_request_operations`.
- Mapping current workflow status to chatbot stage.
- Avoiding stale updates.
- Continuing workflow after SR creation.

---

### 4.5 Upload Files

```http
PUT /files?query=SERVICE_REQUEST&file_extension=pdf&document_type_id={{document_type_id}}&lease_id={{lease_id}}&brand_id={{brand_id}}&property_id={{property_id}}&lease_code={{lease_code}}&sr_id={{sr_id}}&tenant_profile_id={{tenant_profile_id}}&document_type_status={{document_type_status}}&signed_url=true&file_name={{file_name}}
```

Used during:

- FM_REVIEW document upload.
- RDD_REVIEW report upload.

Expected response:

```json
{
  "success": true,
  "data": {
    "document_id": "...",
    "file_path": "...",
    "signed_url": "...",
    "document_type_id": "...",
    "appian_document_id": 0
  }
}
```

Implementation requirement:

- Frontend uploads file to chatbot backend.
- Chatbot backend calls platform `PUT /files`.
- Store returned `document_id`.
- Add `document_id` to `documents_ids`.
- Add document metadata to `document_status_map`.

---

### 4.6 Save FM Progress

```http
PATCH /service-requests/{{sr_id}}
```

Used during `FM_REVIEW`.

Top-level fields:

```json
{
  "status": "IN_PROCESS",
  "service_request_id": "{{sr_id}}"
}
```

Payload should include:

```json
{
  "documents_ids": ["{{doc_fm_uuid}}"],
  "document_status_map": [
    {
      "id": "{{doc_fm_uuid}}",
      "document_status": "",
      "handover_date": "",
      "actual_handover_date": "",
      "fitout_start_date": "",
      "fitout_end_date": "",
      "trading_date": ""
    }
  ],
  "unit_readiness_date": "2026-05-12",
  "expected_handover_date": "2026-05-20",
  "document_saved": true
}
```

---

### 4.7 Approve FM Review

```http
PATCH /service-requests/{{sr_id}}
```

Top-level fields:

```json
{
  "status": "APPROVED",
  "comment": "ok",
  "title": "...",
  "sub_category": "HANDOVER"
}
```

Expected behavior:

```text
FM_MANAGER / OPERATIONS → FINISHED
DD_ENGINEER → IN_PROGRESS
```

Implementation requirement:

- Must call `GET /service-requests/{sr_id}` before approval to avoid stale operation state.
- Must ensure current user role is allowed to approve.
- Must only approve after required FM fields and documents exist.

---

### 4.8 Upload RDD Handover Report

```http
PUT /files?query=SERVICE_REQUEST&file_extension=pdf&document_type_id=DR_SR_HANDOVER_REPORT&lease_id={{lease_id}}&brand_id={{brand_id}}&property_id={{property_id}}&lease_code={{lease_code}}&sr_id={{sr_id}}&tenant_profile_id={{tenant_profile_id}}&document_type_status=APPROVED&signed_url=true&file_name={{file_name_pdf}}
```

Expected returned `document_id` must be stored as `doc_dd_report_uuid`.

---

### 4.9 Submit RDD Report

```http
POST /service-requests
```

Used with existing `service_request_id`.

Top-level fields:

```json
{
  "service_request_id": "{{sr_id}}",
  "status": "REPORT_SUBMITTED"
}
```

Payload must include:

```json
{
  "guideLineLink": "http://...",
  "documents_ids": [
    "{{doc_fm_uuid}}",
    "{{doc_dd_report_uuid}}"
  ],
  "document_status_map": [
    {
      "id": "{{doc_fm_uuid}}",
      "document_status": "",
      "expected_handover_date": "2026-05-20"
    },
    {
      "id": "{{doc_dd_report_uuid}}",
      "document_status": "APPROVED",
      "actual_handover_date": "12/05/2026",
      "fitout_start_date": "14/05/2026",
      "fitout_end_date": "21/05/2026",
      "trading_date": "28/05/2026"
    }
  ]
}
```

---

## 5. CREATE_SR Gap Details

### 5.1 Required User-Supplied Fields

The chatbot should collect these conversationally:

| Field | Required | Notes |
|---|---:|---|
| `lease_code` / tenant / brand / mall | Yes | User can provide any one or more identifiers |
| `description` | Yes or empty allowed depending schema | Can be conversational |
| `startDate` | Yes | Normalize internally |
| `endDate` | Yes | Must be after startDate |
| `inspection_done_by` | Yes | Must be `FM_MANAGER` or `OPERATIONS` |
| `comments` | Yes or empty allowed depending schema | Can be conversational |
| `notes` | Optional | Default empty |

Current gap:

- Verify whether chatbot asks for only required user fields.
- It should not ask for backend-only IDs.

---

### 5.2 Required Backend-Derived Fields

The chatbot should never ask the user for these directly:

| Field | Source |
|---|---|
| `tenant_profile_id` | Lease/tenant lookup |
| `property_id` | Lease/mall lookup |
| `brand_id` | Lease/brand lookup |
| `lease_id` | Lease lookup |
| `contract_id` | Lease lookup; usually same as `lease_id` equivalent |
| `mall` | Lease lookup |
| `brand` | Lease lookup |
| `city` | Lease/property lookup |
| `unit_codes` | Lease lookup |
| `contracted_area` | Lease lookup |
| `company_name` | Tenant lookup |
| `tenant_contact` | Tenant/user lookup or empty |
| `lease_brand_mall` | Derived from lease + brand + mall |
| `startDateLT` | Derived local display date |
| `endDateLT` | Derived local display date |

Required implementation:

- Ensure lease lookup/enrichment returns all of the above.
- If one endpoint does not return all fields, add an enrichment call.
- Protect all backend-derived fields from LLM overwrite.

---

### 5.3 CREATE_SR Payload Compatibility

The create payload must match the Postman payload structure.

Expected shape:

```json
{
  "payload": {
    "mall": "...",
    "brand": "...",
    "lease": "...",
    "notes": "",
    "title": "...",
    "endDate": "...",
    "comments": "...",
    "startDate": "...",
    "attachments": "",
    "description": "...",
    "documents_ids": [],
    "guideLineLink": "",
    "inspectionDoneBy": "FM_MANAGER",
    "lease_brand_mall": "...",
    "inspection_done_by": "FM_MANAGER",
    "document_status_map": [],
    "unit_readiness_date": "",
    "expected_handover_date": "",
    "company_name": "...",
    "tenant_contact": "",
    "user_action": null,
    "unit_codes": ["..."],
    "contracted_area": 420,
    "city": "...",
    "brand_id": 123,
    "tenant_profile_id": 116,
    "contract_id": 456,
    "property_id": 789,
    "startDateLT": "...",
    "endDateLT": "..."
  },
  "title": "...",
  "tenant_profile_id": 116,
  "property_id": 789,
  "service_category": "FIT_OUT_AND_HANDOVER",
  "sub_category": "HANDOVER",
  "lease_code": "...",
  "lease_id": 456,
  "service_request_id": ""
}
```

Implementation gap:

- Existing payload builder may be conceptually correct but must be checked against exact Postman payload.
- Add snapshot tests comparing expected payload shape.

---

## 6. File Upload Gap

Current documentation says upload route exists but is stubbed/partial.

Required implementation:

```text
Frontend
  → POST /api/v1/upload
Backend
  → validate MIME type
  → validate document_type
  → validate current role/action
  → call platform PUT /files
  → receive document_id/file_path/signed_url
  → persist document metadata
  → update draft documents
```

### 6.1 Supported MIME Types

Allow:

```text
application/pdf
image/jpeg
image/png
```

### 6.2 Supported Document Types

FM stage:

```text
SR_HANDOVER_CHECKLIST
SR_HANDOVER_SITE_SURVEY
SR_COP_CHECKLIST_OTHER
SR_HANDOVER_OTHER
```

RDD stage:

```text
DR_SR_HANDOVER_REPORT
SR_REJECTED_HANDOVER_REPORT
SR_HANDOVER_OTHER
```

### 6.3 Document Storage in Draft

Store:

```json
{
  "documents": [
    {
      "document_id": "...",
      "document_type_id": "SR_HANDOVER_CHECKLIST",
      "document_type_status": "",
      "file_path": "...",
      "signed_url": "...",
      "file_name": "sample-handover.pdf"
    }
  ],
  "documents_ids": ["..."],
  "document_status_map": [
    {
      "id": "...",
      "document_status": "",
      "handover_date": "",
      "actual_handover_date": "",
      "fitout_start_date": "",
      "fitout_end_date": "",
      "trading_date": ""
    }
  ]
}
```

---

## 7. FM_REVIEW Gap Details

Current state:

```text
FM_REVIEW schema exists.
FM_REVIEW graph routing and nodes are not fully implemented.
FM_REVIEW endpoint calls are missing/incomplete.
```

### 7.1 FM_REVIEW Required Fields

```text
unit_readiness_date
expected_handover_date
```

Expected handover date can be auto-calculated:

```text
expected_handover_date = unit_readiness_date + 7 days
```

But user should be able to confirm or override if business allows.

### 7.2 FM_REVIEW Required Documents

```text
SR_HANDOVER_CHECKLIST
SR_HANDOVER_SITE_SURVEY
SR_COP_CHECKLIST_OTHER
```

Depending on platform requirements, some may be mandatory and some optional. Confirm from actual workflow rules.

### 7.3 FM_REVIEW Actions

Implement structured actions:

```text
save_fm_progress
approve_fm_review
reject_fm_review
```

### 7.4 FM_REVIEW Nodes to Implement

```text
fm_review_entry_node
fm_document_validation_node
fm_payload_builder_node
fm_save_progress_node
fm_approve_node
```

These can be separate nodes or handled through generic stage-aware nodes.

### 7.5 FM_REVIEW Payload Builders

Implement:

```python
build_fm_review_save_progress_payload(collected_data, documents, sr_id)
build_fm_review_approve_payload(collected_data, documents, sr_id, comment)
```

### 7.6 FM_REVIEW Endpoint Calls

Save progress:

```http
PATCH /service-requests/{sr_id}
```

With status:

```text
IN_PROCESS
```

Approve:

```http
PATCH /service-requests/{sr_id}
```

With status:

```text
APPROVED
```

---

## 8. RDD_REVIEW Gap Details

Current state:

```text
RDD_REVIEW schema exists.
RDD_REVIEW graph routing and nodes are not fully implemented.
RDD_REVIEW endpoint calls are missing/incomplete.
```

### 8.1 RDD_REVIEW Required Fields

```text
guideLineLink
actual_handover_date
fitout_start_date
fitout_end_date
trading_date
```

### 8.2 RDD_REVIEW Required Documents

```text
DR_SR_HANDOVER_REPORT
```

### 8.3 RDD Date Validation

Must enforce:

```text
actual_handover_date <= fitout_start_date <= fitout_end_date <= trading_date
```

### 8.4 RDD_REVIEW Actions

Implement structured actions:

```text
submit_rdd_report
reject_rdd_report
request_changes
```

### 8.5 RDD_REVIEW Nodes to Implement

```text
rdd_review_entry_node
rdd_document_validation_node
rdd_payload_builder_node
rdd_submit_report_node
```

### 8.6 RDD_REVIEW Payload Builder

Implement:

```python
build_rdd_report_submission_payload(collected_data, documents, sr_id)
```

### 8.7 RDD_REVIEW Endpoint Calls

Upload report:

```http
PUT /files?...document_type_id=DR_SR_HANDOVER_REPORT&document_type_status=APPROVED...
```

Submit report:

```http
POST /service-requests
```

With status:

```text
REPORT_SUBMITTED
```

---

## 9. Workflow Status Sync Gap

After the SR is created, the platform becomes the source of truth for workflow status.

The chatbot must sync status using:

```http
GET /service-requests/{sr_id}
```

### 9.1 Required Sync Logic

Before every turn for an existing SR session:

```text
1. Load session/draft from DB.
2. If sr_id exists, call GET /service-requests/{sr_id}.
3. Read service_request_operations.
4. Map platform operation status to chatbot workflow_stage.
5. Continue conversation from correct stage.
```

### 9.2 Suggested Mapping

| Platform Operation | Platform Status | Chatbot Stage |
|---|---|---|
| `MALL_MANAGER` | `IN_PROGRESS` | `CREATE_SR` or initial review |
| `FM_MANAGER` | `IN_PROGRESS` | `FM_REVIEW` |
| `OPERATIONS` | `IN_PROGRESS` | `FM_REVIEW` |
| `DD_ENGINEER` | `IN_PROGRESS` | `RDD_REVIEW` |
| All required operations | `FINISHED` / completed | `COMPLETED` |

### 9.3 POC vs Production

POC:

```text
Sync on every chat turn.
```

Production:

```text
Use webhook or scheduled polling, with turn-level sync as fallback.
```

---

## 10. Permission and Role Gap

The chatbot must enforce role-stage-action access.

### 10.1 Required Actions

```text
CREATE_HANDOVER_SR
VIEW_HANDOVER_SR
UPLOAD_FM_HANDOVER_DOCUMENT
SAVE_FM_HANDOVER_PROGRESS
APPROVE_FM_HANDOVER
REJECT_FM_HANDOVER
UPLOAD_RDD_HANDOVER_REPORT
SUBMIT_RDD_HANDOVER_REPORT
REJECT_RDD_HANDOVER_REPORT
```

### 10.2 Required Role Mapping

| Action | Allowed Roles |
|---|---|
| `CREATE_HANDOVER_SR` | `MALL_MANAGER` |
| `VIEW_HANDOVER_SR` | `MALL_MANAGER`, `FM_MANAGER`, `OPERATIONS`, `DD_ENGINEER` |
| `UPLOAD_FM_HANDOVER_DOCUMENT` | `FM_MANAGER`, `OPERATIONS` |
| `SAVE_FM_HANDOVER_PROGRESS` | `FM_MANAGER`, `OPERATIONS` |
| `APPROVE_FM_HANDOVER` | `FM_MANAGER`, `OPERATIONS` depending on `inspection_done_by` |
| `REJECT_FM_HANDOVER` | `FM_MANAGER`, `OPERATIONS` depending on `inspection_done_by` |
| `UPLOAD_RDD_HANDOVER_REPORT` | `DD_ENGINEER` |
| `SUBMIT_RDD_HANDOVER_REPORT` | `DD_ENGINEER` |
| `REJECT_RDD_HANDOVER_REPORT` | `DD_ENGINEER` |
| Unknown action | Deny |

### 10.3 Required Hardening

Current known issue:

```text
Unknown actions fail-open.
```

Required behavior:

```text
Unknown actions fail-closed.
```

---

## 11. Structured UI Action Gap

The chatbot should not rely only on natural language confirmation for platform-changing actions.

### 11.1 Existing

```text
action = confirm
action = cancel
```

### 11.2 Required Additions

```text
confirm_create_sr
cancel_create_sr
save_fm_progress
approve_fm_review
reject_fm_review
submit_rdd_report
reject_rdd_report
upload_document
change_field
select_lease
```

### 11.3 Why This Matters

Structured actions prevent ambiguous text from triggering critical platform operations.

Example:

```json
{
  "action": "approve_fm_review",
  "comment": "Approved after inspection"
}
```

is safer than relying on:

```text
"yes approve it"
```

---

## 12. API Client Service Layer Gap

Avoid scattering HTTP calls inside graph nodes.

Implement or complete:

```text
ServiceRequestPlatformClient
```

### 12.1 Required Methods

```python
class ServiceRequestPlatformClient:
    async def login(self, email: str, internal_api_token: str) -> dict: ...
    async def get_workflows(self, service_category: str, sub_category: str) -> dict: ...
    async def create_service_request(self, payload: dict) -> dict: ...
    async def get_service_request(self, sr_id: str) -> dict: ...
    async def patch_service_request(self, sr_id: str, payload: dict) -> dict: ...
    async def submit_service_request_report(self, payload: dict) -> dict: ...
    async def upload_file(self, file_bytes: bytes, metadata: dict) -> dict: ...
```

### 12.2 Node Usage

Graph nodes should call service methods, not raw HTTP requests.

```text
api_submission_node → create_service_request()
fm_save_progress_node → patch_service_request()
fm_approve_node → patch_service_request()
rdd_submit_report_node → submit_service_request_report()
upload route/node → upload_file()
status_sync_node → get_service_request()
```

---

## 13. Payload Builder Registry Gap

Current builder is handover-create specific.

Required registry:

```python
PAYLOAD_BUILDERS = {
    ("handover_service_request_agent", "CREATE_SR", "create"): build_create_handover_payload,
    ("handover_service_request_agent", "FM_REVIEW", "save_progress"): build_fm_review_save_progress_payload,
    ("handover_service_request_agent", "FM_REVIEW", "approve"): build_fm_review_approve_payload,
    ("handover_service_request_agent", "RDD_REVIEW", "submit_report"): build_rdd_report_submission_payload,
}
```

Benefits:

- Avoid hardcoded payload builder calls.
- Make future service request agents easier to add.
- Keep LLM away from payload construction.

---

## 14. Dynamic Routing Gap

Current graph routing is handover-specific.

Required dynamic routing:

```python
_AGENT_ENTRY_NODES = {
    "handover_service_request_agent": "handover_entry",
}
```

For stage-specific routing:

```python
_STAGE_ENTRY_NODES = {
    ("handover_service_request_agent", "CREATE_SR"): "handover_entry",
    ("handover_service_request_agent", "FM_REVIEW"): "fm_review_entry",
    ("handover_service_request_agent", "RDD_REVIEW"): "rdd_review_entry",
}
```

Routing should use:

```text
active_agent
workflow_stage
current platform status
```

---

## 15. Field Extraction Registry Gap

Current extraction is tied to Handover extraction schema/prompt.

Required registry:

```python
EXTRACTION_REGISTRY = {
    ("handover_service_request_agent", "CREATE_SR"): {
        "schema": HandoverCreateExtractedFields,
        "prompt": HANDOVER_CREATE_EXTRACTION_PROMPT,
    },
    ("handover_service_request_agent", "FM_REVIEW"): {
        "schema": HandoverFMReviewExtractedFields,
        "prompt": HANDOVER_FM_REVIEW_EXTRACTION_PROMPT,
    },
    ("handover_service_request_agent", "RDD_REVIEW"): {
        "schema": HandoverRDDReviewExtractedFields,
        "prompt": HANDOVER_RDD_REVIEW_EXTRACTION_PROMPT,
    },
}
```

This prevents one extraction model from becoming too broad and unreliable.

---

## 16. Validation Gap

Validation must be stage-aware.

### 16.1 CREATE_SR Validation

```text
Required fields exist.
inspection_done_by is FM_MANAGER or OPERATIONS.
startDate < endDate.
Backend-derived fields are present.
```

### 16.2 FM_REVIEW Validation

```text
unit_readiness_date exists.
expected_handover_date exists.
Required FM documents exist.
Document types are valid for FM stage.
User role can act on FM stage.
```

### 16.3 RDD_REVIEW Validation

```text
guideLineLink exists.
actual_handover_date exists.
fitout_start_date exists.
fitout_end_date exists.
trading_date exists.
DR_SR_HANDOVER_REPORT exists.
Date chain is valid:
actual_handover_date <= fitout_start_date <= fitout_end_date <= trading_date.
User role can act on RDD stage.
```

---

## 17. Error Recovery Gap

Platform API calls can fail.

Required error handling scenarios:

| Scenario | Expected Bot Behavior |
|---|---|
| Lease not found | Ask user for another lease/tenant/mall |
| Multiple leases found | Show lease selection UI |
| Token expired | Re-authenticate and retry once |
| File upload failed | Ask user to retry upload |
| SR create failed | Show clear platform validation error |
| PATCH failed due to stale status | Refresh SR status and continue from latest stage |
| Unauthorized role | Explain user cannot perform current action |
| Invalid document type | Ask user to upload correct document |
| Invalid dates | Ask for corrected date values |
| Platform unavailable | Save draft and ask user to retry later |

---

## 18. Observability and Audit Gap

Before any platform-changing action, persist:

```json
{
  "event": "platform_action_attempted",
  "action": "CREATE_HANDOVER_SR",
  "sr_id": null,
  "payload_preview": "...redacted...",
  "confirmed_by_user": true,
  "trace_id": "...",
  "timestamp": "..."
}
```

After action succeeds:

```json
{
  "event": "platform_action_succeeded",
  "action": "CREATE_HANDOVER_SR",
  "sr_id": "10197",
  "platform_response": "...redacted..."
}
```

After action fails:

```json
{
  "event": "platform_action_failed",
  "action": "CREATE_HANDOVER_SR",
  "error": "...",
  "platform_response": "...redacted..."
}
```

Sensitive fields should be redacted.

---

## 19. Frontend Gap

Frontend should support stage-aware UI components.

### 19.1 Required UI Components

```text
Chat messages
Lease selection cards
Missing field prompt
Confirmation summary card
Document upload card
Uploaded document list
FM review action card
RDD report submission card
Status/progress timeline
Error recovery prompt
```

### 19.2 Required UI Actions

```text
select_lease
confirm_create_sr
cancel_create_sr
upload_document
save_fm_progress
approve_fm_review
submit_rdd_report
change_field
```

---

## 20. Testing Gap

The Postman collection should become the acceptance reference.

### 20.1 E2E Test 1 — Create Handover SR

```text
Given user wants to create handover request
When chatbot detects Handover intent
And resolves lease details
And collects required fields
And user confirms
Then backend calls POST /service-requests
And stores returned service_request_id
```

Assert:

```text
Payload contains service_category = FIT_OUT_AND_HANDOVER
Payload contains sub_category = HANDOVER
Payload contains lease_code
Payload contains tenant_profile_id
Payload contains property_id
Payload contains brand_id
Payload contains contract_id
Payload contains lease_brand_mall
Payload contains startDateLT and endDateLT
No top-level status is sent
```

---

### 20.2 E2E Test 2 — FM Save Progress

```text
Given existing sr_id
And platform status maps to FM_REVIEW
When FM user uploads required document
And clicks save progress
Then backend calls PUT /files
And PATCH /service-requests/{sr_id} with status IN_PROCESS
```

Assert:

```text
documents_ids contains uploaded document_id
document_status_map contains uploaded document_id
unit_readiness_date exists
expected_handover_date exists
```

---

### 20.3 E2E Test 3 — FM Approve

```text
Given FM_REVIEW is complete
When FM user approves
Then backend calls PATCH /service-requests/{sr_id} with status APPROVED
And chatbot syncs latest SR status
```

Assert:

```text
comment is included
payload is complete
DD_ENGINEER moves to IN_PROGRESS or next platform status is reflected
```

---

### 20.4 E2E Test 4 — RDD Submit Report

```text
Given platform status maps to RDD_REVIEW
When DD Engineer uploads DR_SR_HANDOVER_REPORT
And provides required dates
And submits report
Then backend calls POST /service-requests with status REPORT_SUBMITTED
```

Assert:

```text
service_request_id is present
documents_ids includes FM and RDD document IDs
document_status_map includes RDD report status APPROVED
RDD dates are included
Date order validation passed
```

---

### 20.5 Negative Tests

```text
End date before start date
Invalid inspection_done_by
Missing lease
Multiple lease matches
Wrong document type for stage
Unauthorized user role
Prompt injection attempt
Confirm without required fields
Submit without payload
Upload file before sr_id exists
Approve stale SR status
```

---

## 21. Recommended Implementation Order

Use this sequence in Cursor.

```text
1. Align CREATE_SR payload builder exactly with Postman payload.
2. Verify lease lookup resolves every backend-derived field required by Postman.
3. Fix frontend/backend route mismatch if present.
4. Implement real upload route:
   Frontend → backend → platform PUT /files.
5. Store uploaded document metadata in draft/session state.
6. Add status sync:
   GET /service-requests/{sr_id} before every turn with existing SR.
7. Implement FM_REVIEW routing and entry node.
8. Implement FM_REVIEW payload builders:
   save progress and approve.
9. Implement FM_REVIEW endpoint calls:
   PATCH IN_PROCESS and PATCH APPROVED.
10. Implement RDD_REVIEW routing and entry node.
11. Implement RDD_REVIEW payload builder:
   submit report.
12. Implement RDD endpoint calls:
   PUT DR_SR_HANDOVER_REPORT and POST REPORT_SUBMITTED.
13. Harden permission service:
   unknown actions fail-closed.
14. Add structured UI actions for all platform-changing actions.
15. Add platform API error recovery.
16. Add E2E tests mirroring Postman.
17. Refactor into registries:
   payload builder registry, extraction registry, dynamic stage routing.
```

---

## 22. Cursor Review Prompt

Use this prompt in Cursor with the codebase, this document, and the Postman collection.

```text
You are reviewing and completing the implementation of a Handover Service Request chatbot.

Context:
- The chatbot should collect required datapoints through conversation.
- It should resolve backend-derived fields using platform APIs.
- It should build platform-compatible payloads.
- It should call the same endpoints and follow the same sequence as the attached Postman collection.
- The current implementation mainly supports CREATE_SR.
- FM_REVIEW and RDD_REVIEW are schema-defined but not fully wired.

Use the attached gap document and Postman collection as the source of truth.

Tasks:
1. Review the current codebase and identify which gaps from the document are already implemented, partially implemented, or missing.
2. Do not rewrite the architecture unnecessarily.
3. Preserve the principle: LLM provides, code decides.
4. Ensure LLM is only used for intent classification, field extraction, and response generation.
5. Ensure routing, validation, permissions, payload construction, and API submission are deterministic code.
6. Align CREATE_SR payload exactly with the Postman collection.
7. Implement or fix platform file upload integration using PUT /files.
8. Implement status sync using GET /service-requests/{sr_id}.
9. Implement FM_REVIEW lifecycle:
   - collect unit_readiness_date and expected_handover_date
   - upload FM documents
   - save progress as IN_PROCESS
   - approve as APPROVED
10. Implement RDD_REVIEW lifecycle:
   - collect guideline link and handover/fitout/trading dates
   - upload DR_SR_HANDOVER_REPORT
   - submit report as REPORT_SUBMITTED
11. Add role-stage-action permission checks.
12. Change unknown actions to fail-closed.
13. Add structured UI actions for create, upload, save progress, approve, and submit report.
14. Add E2E tests that mirror the Postman sequence.
15. Add negative tests for invalid dates, missing fields, wrong document type, unauthorized role, stale SR status, and prompt injection.

Before coding:
- Produce an implementation plan.
- List files that need changes.
- List assumptions and uncertainties.
- Identify the minimum viable changes to make the Postman flow work end-to-end.

While coding:
- Make small, reviewable changes.
- Keep payload builders deterministic.
- Do not let the LLM generate API payloads.
- Add tests for every new platform action.

After coding:
- Provide a gap closure checklist.
- Show which Postman steps are now covered by code.
- Show remaining TODOs if any.
```

---

## 23. Definition of Done

The implementation can be considered complete for this milestone when:

```text
1. User can create Handover SR through chatbot.
2. Chatbot builds CREATE_SR payload matching Postman.
3. Chatbot submits SR and stores returned sr_id.
4. Chatbot can sync SR status from platform.
5. Chatbot can detect FM_REVIEW stage.
6. FM user can upload required documents.
7. FM user can save progress as IN_PROCESS.
8. FM user can approve as APPROVED.
9. Chatbot can detect RDD_REVIEW stage.
10. DD Engineer can upload DR_SR_HANDOVER_REPORT.
11. DD Engineer can submit report as REPORT_SUBMITTED.
12. Permissions are enforced per role and stage.
13. Unknown actions are denied.
14. Platform-changing actions require explicit confirmation or structured UI action.
15. Full happy path is covered by E2E tests.
16. Negative cases are covered by tests.
17. Observability captures every platform action attempt/success/failure.
```

---

## 24. Final Implementation Principle

Do not make the chatbot a free-form automation agent.

Make it a controlled workflow agent.

```text
LLM:
- Understands user language
- Extracts field values
- Generates natural responses

Code:
- Routes workflow
- Validates data
- Protects backend fields
- Builds payloads
- Checks permissions
- Calls platform APIs
- Audits and traces actions
```

This boundary is mandatory for reliability, security, and platform safety.
