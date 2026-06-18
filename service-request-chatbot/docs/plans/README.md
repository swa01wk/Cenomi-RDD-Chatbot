# RDD Lifecycle Extension — Plan Index

## Overview

The RDD Handover workflow has 4 lifecycle phases involving 3 distinct user roles. This work extends the existing chatbot (which already has Phase 1 / CREATE_SR working end-to-end) to complete the full lifecycle.

```
Phase 0  System      Lease activated in PMS → notification to Mall Manager
Phase 1  MALL_MANAGER  CREATE_SR → POST /service-requests          ✓ DONE
Phase 2  FM_MANAGER    FM_REVIEW → PUT /files ×3 + PATCH APPROVED  ⚠ Plan 02
Phase 3a DD_ENGINEER   RDD_REVIEW → PUT /files + POST REPORT_SUBMITTED  ⚠ Plan 02
Phase 3b DD_ENGINEER   RDD Final Approve → PATCH APPROVED           ✗ Plan 02
Phase 4  System      SR_COMPLETED → tenant notified                 ✓ Status sync exists
```

---

## The Four Plans

| Plan | Focus | Depends On | Sprint |
|---|---|---|---|
| [Plan 01 — Role & Auth Foundation](plan-01-role-auth-foundation.md) | Wire `user_role` through the entire stack; permission enforcement; role-aware supervisor and response generation | Nothing | Sprint 1 |
| [Plan 02 — Backend Lifecycle Completion](plan-02-backend-lifecycle-completion.md) | Document upload bridge; `expected_handover_date` auto-calc; RDD final approval; status sync; **stage-to-stage data contract** | Plan 01 | Sprint 1 |
| [Plan 03 — Frontend Stage-Aware UI](plan-03-frontend-stage-ui.md) | Role selector; FM/RDD action buttons; document upload panel; lifecycle stepper; **stage context summary panel** | Plans 01 + 02 | Sprint 1 |
| [Plan 04 — Extensible Agent System](plan-04-extensible-agent-system.md) | WorkflowDefinitionRegistry; generic stage nodes; dynamic supervisor; second workflow onboarding | Plans 01–03 done | Sprint 2 |

---

## Dependency Flow

```
Plan 01 (Role & Auth)
    │
    ├──► Plan 02 (Backend Completion)
    │         │
    │         └──► Plan 03 (Frontend UI)
    │                   │
    └─────────────────────────► Plan 04 (Extensible Architecture)
```

**Start with Plan 01** — it unblocks everything else.

---

## Role Personas Quick Reference

| Role | Platform ID | Stage | Primary Actions |
|---|---|---|---|
| Mall Manager | `MALL_MANAGER` | CREATE_SR | Create SR, set inspection window, assign FM/Ops |
| FM Manager | `FM_MANAGER` | FM_REVIEW | Inspect site, upload 3 docs, set readiness date, approve |
| Operations | `OPERATIONS` | FM_REVIEW | Same as FM Manager |
| RDD Project Manager | `DD_ENGINEER` | RDD_REVIEW | Upload report, set 4 dates, submit report, final approve |

---

## Key Files Being Changed (Sprint 1)

### Backend
| File | Plan | Change |
|---|---|---|
| `api/routes/chat.py` | 01 + 02 + 03 | Add `user_role` to request; add `rdd_status` and `collected_data` to `ChatStatePayload` response |
| `agents/graph/state.py` | 01 | Add `user_role`, `auth` fields |
| `services/chat_orchestration_service.py` | 01 | Inject role + auth context |
| `agents/services/permission_service.py` | 01 | Add `ROLE_PERMISSION_MAP` |
| `agents/prompts/supervisor_prompt.py` | 01 | Add role guidance section |
| `agents/prompts/response_generation_prompt.py` | 01 | Add per-role persona blocks |
| `agents/graph/nodes/supervisor_node.py` | 01 | Include `user_role` in LLM context |
| `agents/graph/nodes/response_generation_node.py` | 01 | Inject persona context |
| `agents/graph/service_request_graph.py` | 01 + 02 | Role-aware routing; wire `document_upload` |
| `agents/graph/nodes/document_upload_node.py` | 02 | Implement from empty stub |
| `agents/schemas/handover_schema.py` | 02 | Move `expected_handover_date` to `BACKEND_COMPUTED_FIELDS` |
| `agents/graph/nodes/merge_state_node.py` | 02 | Auto-calc `expected_handover_date` |
| `agents/graph/nodes/rdd_review_entry_node.py` | 02 | Add `approve_rdd_final` action |
| `agents/graph/nodes/rdd_payload_builder_node.py` | 02 | Branch on `rdd_action` |
| `agents/graph/nodes/rdd_api_submission_node.py` | 02 | Add PATCH branch for final approval |
| `agents/services/payload_builder_service.py` | 02 | Add `build_rdd_approve_payload()` |
| `agents/graph/nodes/sr_status_sync_node.py` | 02 | Store `rdd_status` in `backend_refs` |

### Frontend
| File | Plan | Change |
|---|---|---|
| `frontend/components/chatbot/RoleSelector.tsx` | 03 | New: role card picker |
| `frontend/components/chatbot/StageActions.tsx` | 03 | New: role+stage action buttons |
| `frontend/components/chatbot/DocumentUploadPanel.tsx` | 03 | New: role-scoped file upload |
| `frontend/components/chatbot/LifecycleStepper.tsx` | 03 | New: stage progress indicator |
| `frontend/components/chatbot/StageContextPanel.tsx` | 03 | New: collapsible prior-stage data panel for reviewers |
| `frontend/lib/api/chat-client.ts` | 03 | Add `user_role` to request |
| `frontend/app/service-request-chat/page.tsx` | 03 | Wire role selector + stage UI |

---

## Architecture Principle

The entire lifecycle runs within the **existing single-agent, multi-stage LangGraph**. No new agents, no new graphs, no multi-agent hierarchy.

```
All 4 phases → one agent (handover_service_request_agent)
             → one graph (service_request_graph.py)
             → one state schema (ServiceRequestGraphState)
             → stage routing via sr_status_sync → workflow_stage
```

The only new graph node is `document_upload_node`. Everything else is completing existing stubs and extending existing nodes with role awareness.

## Stage-to-Stage Context Flow

`collected_data` and `backend_refs` accumulate across all three stages via PostgreSQL. Each reviewer sees all prior-stage data without any explicit handover step.

```
CREATE_SR                    FM_REVIEW                     RDD_REVIEW
─────────────────────────    ──────────────────────────    ───────────────────────────
collected_data:              reads all Stage 1 data +      reads all Stage 1+2 data +
  lease fields               adds:                         adds:
  unit_code, description       unit_readiness_date           4 contractual dates
  title (auto)                 expected_handover_date
                               (auto: readiness + 7d)
backend_refs:                backend_refs adds:            backend_refs adds:
  sr_id                        uploaded_documents            rdd_document_id
  tenant_profile_id            fm_status=APPROVED            rdd_status
  property_id
```

The backend exposes `collected_data` in `ChatStatePayload`; the frontend `StageContextPanel` renders it as a collapsible read-only summary for FM and RDD reviewers.
