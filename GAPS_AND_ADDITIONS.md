# Cenomi-RDD-Chatbot — Gaps & Additions Notes

> Reference document comparing `Cenomi-RDD-Chatbot` against `cenomi-ai-backend` (staging branch).
> Excludes the three agents in staging that don't apply here: **Help Agent (standalone)**, **RDD Agent**, **Tenant Ops Agent**.

---

## Context

`Cenomi-RDD-Chatbot` is the standalone POC for the Handover SR chatbot.
`cenomi-ai-backend` (staging) is the production-bound unified Python service that evolved from this codebase.

The two missing pieces in `Cenomi-RDD-Chatbot` are:

1. **RAG in the FAQ / Help node**
2. **Five new SR sub-types**

Everything else in the codebase is fine as-is.

---

## Gap 1 — RAG in the FAQ Node

### Current state

The FAQ/help path in the LangGraph graph is:

```
supervisor (intent=ASK_HELP) → faq_node → response_generation → save_state
```

`faq_node` makes a single LLM call with a **148-line static embedded prompt** (`FAQ_SYSTEM_PROMPT`).
No search, no knowledge base, no source citations, no context from the frontend.

### What needs to be added (from staging's Help Agent)

| Feature | Where it comes from |
|---|---|
| Azure AI Search RAG (hybrid vector + keyword, 4 parallel queries) | `app/integrations/azure/search.py` in staging |
| Context injection (`[User is viewing: /url > category]` prefix) | `HelpUsecase._build_viewing_context()` in staging |
| Source citations returned in response | `HelpUsecase._format_rag_context()` + Foundry annotations |
| Graceful fallback to static prompt when Azure Search not configured | New behaviour |

### What is NOT being ported from staging's Help Agent

| Feature | Reason |
|---|---|
| Azure AI Foundry agent (thread/run/poll) | RDD-Chatbot keeps plain OpenAI — Foundry is a separate major dependency |
| Language detection (Arabic/English) | Not a priority right now |
| Real SSE streaming | Deferred |
| RBAC mall scoping in search | Staging itself doesn't implement this; noted gap in both |
| `HelpUsecase` as standalone class | Logic stays inside `faq_node` to match the LangGraph pipeline design |
| External routing classifier | LangGraph supervisor already handles routing — keep it |

### Files to create (new)

```
app/integrations/__init__.py
app/integrations/azure/__init__.py
app/integrations/azure/search.py          ← port of AzureSearchRepository from staging (drop AccessScope param)
app/agents/services/help_search_service.py ← singleton getter: get_help_search_service() → AzureSearchRepository | None
```

### Files to modify (existing)

| File | Change |
|---|---|
| `app/agents/graph/state.py` | Add `help_context: dict` and `help_sources: list[dict]` fields |
| `app/agents/graph/nodes/faq/faq_node.py` | Add RAG retrieval + context injection + source output before LLM call |
| `app/agents/prompts/faq_prompt.py` | Instructions-only prompt when RAG present; static knowledge as fallback |
| `app/core/config.py` | Add optional Azure Search + embedding config vars |
| `.env.example` | Document new vars (all optional, empty by default) |
| `app/api/routes/chat.py` | Add `context: dict | None` to request; add `sources: list[dict]` to response |
| `app/services/chat_orchestration_service.py` | Map `context` to `initial_state`; extract `help_sources` from final state |

### New env vars (all optional)

```bash
# Azure AI Search — leave empty to use static FAQ prompt (graceful fallback)
AZURE_SEARCH_ENDPOINT=
AZURE_SEARCH_API_KEY=
AZURE_SEARCH_INDEX_NAME=cenomi-help-index

# Azure OpenAI embeddings (reused for vector search)
AZURE_AI_ENDPOINT=
AZURE_AI_API_KEY=
AZURE_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

---

## Gap 2 — New SR Sub-types

### Current state

Only one SR sub-type is registered: `FIT_OUT_AND_HANDOVER / HANDOVER`.

### What needs to be added

| SR sub-type | Service category | Key behaviour |
|---|---|---|
| OCI (Open Ceiling Inspection) | FIT_OUT_AND_HANDOVER | Forced DD_ENGINEER inspector |
| CCI (Close Ceiling Inspection) | FIT_OUT_AND_HANDOVER | Same as OCI |
| POI Architectural | FIT_OUT_AND_HANDOVER | Point-of-inspection architectural |
| POI MEP | FIT_OUT_AND_HANDOVER | M&E point-of-inspection |
| General Inquiry | INQUIRY | Optional lease lookup; different schema |

### Files to port from staging (direct port, no changes needed)

| File | What it contains |
|---|---|
| `app/agents/schemas/fitout_inspection_schema.py` | `SubCategoryConfig` + per-type required fields + labels for OCI, CCI, POI Arch, POI MEP |
| `app/agents/schemas/inquiry_schema.py` | General Inquiry schema, required fields, `is_general_inquiry()`, `should_skip_lease_lookup()` |
| `app/agents/schemas/service_request_config.py` | Unified config resolver: `get_create_sr_required_fields()`, `get_request_type_label()`, `should_skip_lease_lookup()` |
| `app/agents/prompts/inquiry_extraction_prompt.py` | Field extraction prompt for General Inquiry |
| `app/agents/graph/nodes/silent_finalize_node.py` | 18-line node for silent draft patches (no chat bubble) |

### Files to update (existing)

| File | Change |
|---|---|
| `app/agents/registries/service_request_registry.py` (or `registry.py`) | Register OCI, CCI, POI Arch, POI MEP, General Inquiry |
| `app/agents/schemas/supervisor_schema.py` | Add 5 new intent literals (`CREATE_OPEN_CEILING_INSPECTION_SERVICE_REQUEST`, etc.) |
| `app/agents/prompts/supervisor_prompt.py` | Describe new intents so the LLM classifies them correctly |
| `app/agents/services/payload_builder_service.py` | Add payload construction for new SR sub-types |
| `app/agents/services/validation_service.py` | Add validation rules for new SR sub-types |
| `app/agents/graph/helper_agent_graph.py` | Two routing additions: `silent_draft_patch` shortcut in `_route_after_load`; `should_skip_lease_lookup` in `_route_after_merge` for General Inquiry; wire `silent_finalize_node` |

---

## Routes — What Staging Has vs What RDD-Chatbot Needs

### Staging routes overview

| Route file | Mounted at | Purpose |
|---|---|---|
| `chat.py` | `/api/chat/service-request` | Primary SR chat turn |
| `health.py` | `/api/v1/health`, `/api/v1/ready` | Liveness + readiness |
| `upload.py` | `/api/v1/upload` | Document upload |
| `assistant_compat.py` | `/api/v1/assistant/chat` | Unified multi-agent router (Help/RDD/TenantOps/SR) |
| `go_compat_routes.py` | `/api/v1/chat`, `/api/v1/rdd/chat`, `/api/v1/tenant-ops/chat` | Go proxy backward compat |
| `conversations.py` | `/api/v1/conversations` | Azure Foundry thread lifecycle (create/delete Help agent threads) |
| `admin.py` | `/api/v1/admin/reindex`, `/api/v1/admin/index-status` | Knowledge reindex + search stats |
| `dashboard.py` | `/api/v1/dashboard/assistant-admin` | Admin analytics + conversation listing |
| `eval_routes.py` | `/api/v1/eval/*`, `/api/v1/analytics/*` | Eval pipeline + analytics |
| `livedata.py` | `/api/v1/admin/livedata/*` | RDD live SQL gateway |

### Which staging routes apply to RDD-Chatbot

| Route file | Apply? | Notes |
|---|---|---|
| `chat.py` | Yes | Already exists; minor additions needed for RAG (`context`, `sources`) |
| `health.py` | Yes | Already exists, unchanged |
| `upload.py` | Yes | Already exists, unchanged |
| `assistant_compat.py` | **No** | Multi-agent unified router — not needed, RDD-Chatbot is SR-only |
| `go_compat_routes.py` | **No** | Go proxy backward compat — not applicable |
| `conversations.py` | **No** | Foundry thread management — only relevant if Foundry is added |
| `livedata.py` | **No** | RDD analytics live SQL — not applicable |
| `admin.py` (reindex) | Deferred | Only relevant once Azure Search RAG is live |
| `dashboard.py` | Deferred | Useful admin analytics; can be added later |
| `eval_routes.py` | Deferred | Eval pipeline exists differently in RDD-Chatbot |

---

## What Is Explicitly Not Changing

- LangGraph graph topology (`helper_agent_graph.py`) — minimal routing additions only for new SR types
- `response_generation_node.py` — unchanged
- `LLMGateway` — unchanged (same OpenAI call, JSON mode, temp=0)
- Auth / RBAC model — unchanged (RDD-Chatbot keeps own JWT + bcrypt users table)
- All existing SR workflow nodes (core logic) — unchanged
- Frontend API contract — backward-compatible additions only
- Service depth improvements unrelated to new SR types (lease lookup enrichment, validation depth) — deferred
- SSE streaming for FAQ/help — deferred

---

## File Change Summary

### New files to create (9)

```
app/integrations/__init__.py
app/integrations/azure/__init__.py
app/integrations/azure/search.py
app/agents/services/help_search_service.py
app/agents/schemas/fitout_inspection_schema.py
app/agents/schemas/inquiry_schema.py
app/agents/schemas/service_request_config.py
app/agents/prompts/inquiry_extraction_prompt.py
app/agents/graph/nodes/silent_finalize_node.py
```

### Existing files to modify (11)

```
app/agents/graph/state.py
app/agents/graph/nodes/faq/faq_node.py
app/agents/prompts/faq_prompt.py
app/agents/prompts/supervisor_prompt.py
app/agents/schemas/supervisor_schema.py
app/agents/registries/service_request_registry.py   (or registry.py)
app/agents/services/payload_builder_service.py
app/agents/services/validation_service.py
app/agents/graph/helper_agent_graph.py
app/api/routes/chat.py
app/services/chat_orchestration_service.py
app/core/config.py
.env.example
```
