# FAQ Node RAG Integration — Cloud-Agnostic Design

> Implementation guide for adding hybrid-search RAG to the helper agent's `faq_node`.
> All changes are **self-contained in this repo** — no code is imported from staging.

---

## Staging Branch Dependency Clarification

The staging branch (`cenomi-ai-backend`) is used **only as a reference**. Nothing is imported from it at runtime.

| What we take from staging | How | Runtime dependency? |
|---|---|---|
| `AzureSearchRepository` logic | **Ported** (copy + adapt) into new `app/integrations/search/azure_search.py` | No |
| `_format_rag_context()` + `_detect_language()` | **Inlined** into `faq_node.py` | No |
| `cenomi-help-index` (Azure AI Search index) | **Shared** — both apps query the same live index | **Yes — infrastructure only** |

The only real dependency on staging is the **live Azure AI Search index** (`cenomi-help-index`). All code is fully self-contained in this repo.

---

## Architecture Review

### 1. Current State — faq_node today

The helper agent is a 26-node LangGraph compiled in `helper_agent_graph.py`. The FAQ node answers questions using a static embedded string in `faq_prompt.py` — no external search, no vector DB.

```
POST /chat
    → load_session
    → sr_status_sync
    → supervisor_node
         ↓ ASK_HELP / UNKNOWN
    → faq_node  ──── [static FAQ_SYSTEM_PROMPT] ──→ LLMGateway (gpt-4o-mini)
    → response_generation
    → save_state
    → END
```

**Tech stack today:** Python 3.11, FastAPI, LangGraph, OpenAI (`gpt-4o-mini`), PostgreSQL 16, Redis 7. No Azure services.

---

### 2. Staging Reference — Help Agent RAG Pattern

The staging Help agent (`cenomi-ai-backend`) is a standalone usecase (not LangGraph). It runs hybrid search against Azure AI Search before every LLM call and injects retrieved chunks as context.

```
POST /chat (with context)
    → HelpUsecase.ask
        → embed query (text-embedding-3-small)
        → AzureSearchRepository.search
            → [parallel] broad help_content query    (top 3)
            → [parallel] mall_info query             (top 4)
            → [parallel] key_contact query           (top 2)
            → [parallel] event query                 (top 2)
        → deduplicate + merge chunks
        → format as ### Relevant Knowledge Base Results block
        → Azure AI Foundry Agent (LLM)
```

**Index:** `cenomi-help-index` on Azure AI Search — sources: `help_content`, `mall_info`, `key_contact`, `event`. Embeddings: `text-embedding-3-small` (1536-dim) via Azure OpenAI.

---

### 3. Target State — faq_node after integration

The RAG search layer is lifted into `faq_node`. The **LangGraph graph topology is unchanged** — only the internals of `faq_node` gain a search step.

```
faq_node internals:
    user_message
        → detect language (en / ar)
        → get_search_repository()
              ↓ available (env vars set)            ↓ unavailable (no env vars)
        → embed query                         → static FAQ_SYSTEM_PROMPT only
        → hybrid search (cenomi-help-index)
        → format RAG context block
        → LLMGateway.complete_json
              (RAG context + FAQ_SYSTEM_PROMPT)
        → response_message + faq_sources []
```

---

### 4. Cloud-Agnostic Design — Following the LLMGateway Pattern

The existing `LLMGateway` is already cloud-agnostic: one interface, provider-agnostic, config-driven factory, injectable singleton. The RAG integration follows the **exact same pattern**.

```
Abstract Interfaces (Protocols)
    EmbeddingProvider.embed(text) → list[float] | None
    SearchRepository.search(query, lang, top_k) → list[SearchResult]

Concrete Implementations
    OpenAIEmbeddingProvider       ← EMBEDDING_PROVIDER=openai (default)
    AzureOpenAIEmbeddingProvider  ← EMBEDDING_PROVIDER=azure_openai
    AzureSearchRepository         ← SEARCH_PROVIDER=azure_search

    Future (new file only, zero node changes):
    QdrantSearchRepository        ← SEARCH_PROVIDER=qdrant
    PgVectorSearchRepository      ← SEARCH_PROVIDER=pgvector

Factory (config-driven singletons)
    get_embedding_provider() → EmbeddingProvider | None
    get_search_repository()  → SearchRepository | None
    close_integrations()     → called on app shutdown

faq_node imports only the Protocol + factory
    zero cloud-specific imports in the node itself
```

**Key principle:** Swapping a provider requires only a config/env var change — no node code changes.

---

### 5. New Package Structure

```
app/integrations/
├── __init__.py
├── factory.py                       # config-driven singletons + close_integrations()
├── embeddings/
│   ├── __init__.py
│   ├── base.py                      # EmbeddingProvider Protocol
│   ├── openai_embed.py              # OpenAIEmbeddingProvider (mirrors LLMGateway style)
│   └── azure_openai_embed.py        # AzureOpenAIEmbeddingProvider
└── search/
    ├── __init__.py
    ├── base.py                      # SearchRepository Protocol + SearchResult dataclass
    └── azure_search.py              # AzureSearchRepository (EmbeddingProvider injected via DI)
```

`AzureSearchRepository` receives an `EmbeddingProvider` at construction time — it does **not** call Azure OpenAI directly. Search and embeddings are independently swappable.

---

### 6. Component Map

| Component | Source | Destination in this repo |
|---|---|---|
| `EmbeddingProvider` Protocol | New | `app/integrations/embeddings/base.py` |
| `OpenAIEmbeddingProvider` | New (mirrors LLMGateway) | `app/integrations/embeddings/openai_embed.py` |
| `AzureOpenAIEmbeddingProvider` | Adapted from staging `search.py` embed logic | `app/integrations/embeddings/azure_openai_embed.py` |
| `SearchRepository` Protocol + `SearchResult` | New | `app/integrations/search/base.py` |
| `AzureSearchRepository` | Ported from staging `search.py`, embed decoupled | `app/integrations/search/azure_search.py` |
| `_format_rag_context()` | Adapted from staging `usecase.py` | Inlined into `faq_node.py` |
| Language detection | Adapted from staging `usecase.py` | Inlined into `faq_node.py` |
| Factory | New | `app/integrations/factory.py` |

---

### 7. Key Design Decisions

| Concern | Decision |
|---|---|
| LLM provider | Keep existing `LLMGateway` — **unchanged** |
| Embeddings | `EmbeddingProvider` Protocol — `openai` (default) or `azure_openai` via `EMBEDDING_PROVIDER` |
| Search | `SearchRepository` Protocol — `azure_search` (first impl) via `SEARCH_PROVIDER` |
| Embedding ↔ Search coupling | **Decoupled** — `EmbeddingProvider` injected into `SearchRepository` constructor |
| Knowledge index | Reuse staging's `cenomi-help-index` — same schema, no re-indexing needed |
| Fallback | All env vars absent → static `FAQ_SYSTEM_PROMPT` unchanged (current behavior preserved) |
| Graph topology | **No change** — `faq_node → response_generation → save_state` |
| Citations | `faq_sources: list[dict]` added to graph state and surfaced via API |
| Extensibility | Add new provider = one new file in `embeddings/` or `search/` + update factory only |

---

## Concerns — Pipeline, State & Observability

### Agent Pipeline

**1. Latency budget — 3 sequential I/O rounds per FAQ turn**

Before: 2 LLM calls (faq_node + response_generation).
After: embed (1 call) → 4 parallel search queries (1 round, parallelised via `asyncio.gather`) → LLM call (faq_node) → LLM call (response_generation) = **3 sequential I/O rounds, 7+ network calls**.

Net effect: 1 extra sequential round per FAQ turn (~200–400 ms combined for embed + search when Azure endpoints are in the same region). Accepted cost for v1. Flag for future optimisation (e.g. skip `response_generation_node` for pure FAQ via conditional edge once latency is measured in production).

---

**2. `response_generation_node` rewrites the RAG answer without seeing sources**

`response_generation_node` takes `response_message` from `faq_node` as a polish hint and calls the LLM again. It has no visibility into `faq_sources`. The polished text won't include inline citations unless `faq_node` embeds them.

Fix: `faq_node` embeds source titles inline in `response_message` (e.g. `[Source: Work Permit Overview]`). `faq_sources` in state is the structured version for the API/frontend. `response_generation_node` is untouched — it polishes tone only and never overwrites `faq_sources`.

---

**3. `ChatTurnResult` doesn't expose `faq_sources` to the API layer (must fix)**

`chat_orchestration_service.py` builds `ChatTurnResult` from `result_state` but never extracts `faq_sources`. Sources are silently dropped before reaching the frontend.

Fix: add `faq_sources: list[dict]` to `ChatTurnResult`, extract from `result_state` in `chat_orchestration_service.py`, expose in the API response JSON.

---

**4. `httpx.AsyncClient` has no graceful shutdown (should fix)**

`AzureSearchRepository` creates `httpx.AsyncClient(timeout=15.0)` in `__init__`. The singleton is never closed, causing `ResourceWarning` on shutdown.

Fix: add a `close()` coroutine to the repository; call it from a FastAPI `lifespan` shutdown hook via `close_integrations()` in `factory.py`.

---

### State Management

**5. Stale `faq_sources` carry-over across turns (must fix)**

`save_state_node` checkpoints the full state dict to DB — including `faq_sources`. `load_session_node` restores this on the next turn, so turn N+1 starts with stale sources from turn N.

This is the exact same pattern already fixed for `missing_fields`:
```python
# load_session_node.py — already present:
loaded.pop("missing_fields", None)

# Add alongside it:
loaded.pop("faq_sources", None)
```

---

**6. `faq_sources` must always be a list, never `None` (must fix)**

`ServiceRequestGraphState` is `total=False` — all fields are optional by default. `faq_node` must always return `faq_sources` as a `list` (empty `[]` when RAG is skipped, populated list when search runs).

---

### Observability

**7. `@trace_node` captures `faq_sources` automatically — no changes needed**

The existing decorator takes BEFORE/AFTER state snapshots. `faq_sources` will appear in both snapshots and the state diff (`[] → [{source_type, title}, ...]`) automatically. No tracing infrastructure changes needed.

---

**8. New credentials are already covered by `redact_payload` — no changes needed**

`redact.py` uses substring matching. `azure_search_api_key` and `azure_ai_api_key` both contain `api_key` → automatically `[REDACTED]` in all trace snapshots.

---

**9. Use `structlog` in all new integration code (should fix)**

The staging `AzureSearchRepository` uses standard `logging`. This repo uses `structlog.get_logger(__name__)` everywhere. All new files must use structlog for consistent structured log fields.

---

**10. Per-operation latency logging inside `faq_node` (nice to have)**

`@trace_node` captures total node latency but not sub-operation latency. Add:
```python
log.info("faq_node.embed_complete", latency_ms=..., vector_dims=1536)
log.info("faq_node.search_complete", latency_ms=..., hits=len(results))
```

---

**11. `faq_sources` in assistant message metadata (nice to have)**

When `chat_orchestration_service.py` persists the assistant reply, add `faq_sources` to `metadata`. Creates a message-level citation record for replay without querying trace tables.

---

### Summary — Priority Table

| # | Concern | Priority |
|---|---------|----------|
| 5 | Stale `faq_sources` reset in `load_session_node` | Must fix |
| 3 | `faq_sources` surfaced in `ChatTurnResult` / API | Must fix |
| 6 | `faq_node` always returns `faq_sources: list` | Must fix |
| 4 | `httpx.AsyncClient` graceful shutdown | Should fix |
| 2 | Inline source attribution in `response_message` | Should fix |
| 9 | `structlog` in all new integration code | Should fix |
| 10 | Per-operation latency logging in `faq_node` | Nice to have |
| 11 | `faq_sources` in assistant message metadata | Nice to have |
| 1 | Latency budget — accepted for v1 | Monitor |
| 7, 8 | Tracing + redaction — no changes needed | N/A |

---

## Implementation — Files to Create / Change

### Step 1 — `app/core/config.py`

Add under the LLM section:

```python
# RAG provider selection
embedding_provider: str = Field(default="openai", validation_alias="EMBEDDING_PROVIDER")
search_provider: str = Field(default="azure_search", validation_alias="SEARCH_PROVIDER")

# Embeddings — standard OpenAI (reuses existing openai_api_key)
embedding_model: str = Field(default="text-embedding-3-small", validation_alias="EMBEDDING_MODEL")
embedding_base_url: str | None = Field(default=None, validation_alias="EMBEDDING_BASE_URL")

# Embeddings — Azure OpenAI (only when EMBEDDING_PROVIDER=azure_openai)
azure_ai_endpoint: str | None = Field(default=None, validation_alias="AZURE_AI_ENDPOINT")
azure_ai_api_key: str | None = Field(default=None, validation_alias="AZURE_AI_API_KEY")
azure_ai_api_version: str = Field(default="2024-02-15-preview", validation_alias="AZURE_AI_API_VERSION")

# Search — Azure AI Search (only when SEARCH_PROVIDER=azure_search)
azure_search_endpoint: str | None = Field(default=None, validation_alias="AZURE_SEARCH_ENDPOINT")
azure_search_api_key: str | None = Field(default=None, validation_alias="AZURE_SEARCH_API_KEY")
azure_search_index_name: str | None = Field(default=None, validation_alias="AZURE_SEARCH_INDEX_NAME")
```

---

### Step 2 — `app/integrations/embeddings/base.py` (new)

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float] | None: ...
```

---

### Step 3 — `app/integrations/embeddings/openai_embed.py` (new)

Uses `openai.AsyncOpenAI` with configurable `base_url` — mirrors `LLMGateway` pattern. Works for standard OpenAI and any OpenAI-compatible endpoint.

---

### Step 4 — `app/integrations/embeddings/azure_openai_embed.py` (new)

Uses `openai.AsyncAzureOpenAI` with `azure_endpoint` + `api_key` + `api_version`.

---

### Step 5 — `app/integrations/search/base.py` (new)

```python
from dataclasses import dataclass
from typing import Protocol

@dataclass
class SearchResult:
    source_type: str
    title: str
    content: str
    url_pattern: str = ""
    mall_name: str = ""
    language: str = ""

class SearchRepository(Protocol):
    async def search(self, query: str, lang: str, top_k: int = 5) -> list[SearchResult]: ...
    async def close(self) -> None: ...
```

---

### Step 6 — `app/integrations/search/azure_search.py` (new)

Port `AzureSearchRepository` from staging's `app/integrations/azure/search.py`.

Adaptations vs staging:
- `EmbeddingProvider` injected at construction (no internal Azure OAI calls)
- `embed()` method removed — calls `self._embedding_provider.embed()` instead
- Standard `logging` replaced with `structlog.get_logger(__name__)`
- `close()` coroutine added: `await self._client.aclose()`
- Import path: `from app.core.config import settings` (same as this repo)

---

### Step 7 — `app/integrations/factory.py` (new)

```python
def get_embedding_provider() -> EmbeddingProvider | None:
    """Return singleton EmbeddingProvider based on settings.embedding_provider."""
    # "openai"       → OpenAIEmbeddingProvider(api_key, base_url, model)
    # "azure_openai" → AzureOpenAIEmbeddingProvider(endpoint, api_key, api_version, model)
    # missing creds  → None (faq_node falls back to static prompt)

def get_search_repository() -> SearchRepository | None:
    """Return singleton SearchRepository based on settings.search_provider."""
    # "azure_search" → AzureSearchRepository(endpoint, api_key, index, embedding_provider)
    # missing creds  → None

async def close_integrations() -> None:
    """Close all open HTTP clients — called from FastAPI lifespan shutdown."""
```

---

### Step 8 — `app/agents/graph/nodes/faq/faq_node.py` (update)

New execution flow:

1. `search_repo = get_search_repository()` — if `None`, skip to step 5
2. Detect language (Arabic regex check on `user_message`)
3. Run `search_repo.search(query, lang)` — log embed + search latency
4. Format results as `### Relevant Knowledge Base Results` block; build `faq_sources` list
5. Prepend RAG context (or empty string) to `user_content`
6. Call `LLMGateway.complete_json(FAQ_SYSTEM_PROMPT, user_content)`
7. Return `{"response_message": answer, "status": "WAITING_FOR_USER", "faq_sources": sources}`

Imports from: `app.integrations.factory` only — zero cloud-specific imports.

---

### Step 9 — `app/agents/prompts/faq_prompt.py` (update)

Add two lines to `FAQ_SYSTEM_PROMPT` instructions section:

```
When a "### Relevant Knowledge Base Results" block is present in the user message,
prefer that content over the built-in knowledge below. If both conflict, the
retrieved block takes precedence.
```

Keep all static knowledge unchanged — it remains the fallback.

---

### Step 10 — `app/agents/graph/state.py` (update)

```python
faq_sources: list[dict]   # [{source_type, title}, ...] — RAG citations for this turn
```

---

### Step 11 — `app/agents/graph/nodes/shared/load_session_node.py` (update)

```python
loaded.pop("missing_fields", None)  # already present
loaded.pop("faq_sources", None)     # add: reset citations each turn
```

---

### Step 12 — `app/services/chat_orchestration_service.py` (update)

- Add `faq_sources: list[dict] = field(default_factory=list)` to `ChatTurnResult`
- Extract `result_state.get("faq_sources") or []` and set on result
- Add `"faq_sources": faq_sources` to assistant message `metadata` when persisting

---

### Step 13 — FastAPI lifespan shutdown hook (update `app/main.py`)

```python
from contextlib import asynccontextmanager
from app.integrations.factory import close_integrations

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_integrations()

app = FastAPI(lifespan=lifespan, ...)
```

---

### Step 14 — `requirements.txt` (verify)

Confirm `httpx` is listed. Add if missing.

---

## Environment Variables

### Option A — Standard OpenAI embeddings (default, no Azure OAI needed)

```env
# Provider selection (EMBEDDING_PROVIDER=openai is the default — can omit)
SEARCH_PROVIDER=azure_search
EMBEDDING_MODEL=text-embedding-3-small
# Reuses existing OPENAI_API_KEY — no new credential

AZURE_SEARCH_ENDPOINT=https://<instance>.search.windows.net
AZURE_SEARCH_API_KEY=<key>
AZURE_SEARCH_INDEX_NAME=cenomi-help-index
```

### Option B — Azure OpenAI embeddings

```env
EMBEDDING_PROVIDER=azure_openai
SEARCH_PROVIDER=azure_search
EMBEDDING_MODEL=text-embedding-3-small

AZURE_AI_ENDPOINT=https://<oai-instance>.openai.azure.com
AZURE_AI_API_KEY=<key>
AZURE_AI_API_VERSION=2024-02-15-preview

AZURE_SEARCH_ENDPOINT=https://<instance>.search.windows.net
AZURE_SEARCH_API_KEY=<key>
AZURE_SEARCH_INDEX_NAME=cenomi-help-index
```

### Option C — No env vars (safe fallback)

`faq_node` silently uses the static `FAQ_SYSTEM_PROMPT`. Current behavior is fully preserved.

---

## What Does NOT Change

- LangGraph graph topology — `supervisor → faq_node → response_generation → save_state`
- `_FAQ_INTENTS` routing constant in `helper_agent_graph.py`
- `response_generation_node` — untouched
- All SR workflow nodes (handover, FM review, RDD review) — untouched
- `LLMGateway` — untouched
- Frontend / API contract — `faq_sources` field is additive (no breaking change)
- Observability infrastructure (`@trace_node`, `redact_payload`) — no changes needed
