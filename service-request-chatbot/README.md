# Cenomi Service Request Chatbot

A production-oriented conversational agent for **Cenomi mall-tenant handover service requests**. Tenants interact in natural language; the LLM extracts and proposes field values while application services own validation, enrichment, payload construction, and outbound submission to Cenomi's Service Request API.

> **Design principle:** LLMs understand and propose — application code validates, authorises, persists, and submits.

---

## Repository layout

```
service-request-chatbot/
├── backend/               FastAPI app, LangGraph agent, services, repositories, tests
│   ├── app/
│   │   ├── agents/        LangGraph graph, nodes, prompts, domain services
│   │   ├── api/routes/    chat, health, upload endpoints
│   │   ├── core/          config, logging, security, injection guard, permissions
│   │   ├── db/            SQLAlchemy models (async), session factory, repositories
│   │   ├── observability/ TraceManager, traces/runs/metrics/feedback APIs
│   │   └── services/      ChatOrchestrationService, ConversationStateService
│   ├── alembic/           DB migrations (001 initial schema, 002 observability)
│   └── tests/             unit/, integration/, e2e/
├── frontend/              Next.js 15 (App Router) chat + admin UI
│   ├── app/
│   │   ├── service-request-chat/   Tenant chat page
│   │   └── admin/agent-observability/  Trace explorer
│   ├── components/
│   │   ├── chatbot/       ServiceRequestChat, lease/summary/input components
│   │   └── observability/ Trace list/detail, replay, LLM/tool call viewers
│   └── lib/api/           chat-client.ts, observability-client.ts
├── docs/                  Architecture, API reference, agent design, security, etc.
└── docker-compose.yml     PostgreSQL 16 + Redis 7 for local development
```

---

## Architecture overview

```
Browser (Next.js)
  └─▶ POST /api/chat/service-request
        └─▶ ChatOrchestrationService.process_turn
              ├─ Session load / injection scan
              ├─ LangGraph graph.ainvoke (stateless per request)
              │    Nodes: supervisor → handover/registry → extraction → merge
              │          → lease lookup → validation → confirmation
              │          → payload build → SR API submission → response gen
              │          → save state
              └─ TraceManager → Postgres (sessions, drafts, messages, traces)
```

**State strategy:** graph execution is stateless per HTTP turn; all conversation state is persisted to and restored from Postgres by `ConversationStateService`.

---

## Technology stack

| Layer | Technologies |
|-------|-------------|
| Backend runtime | Python 3.11+, FastAPI, Uvicorn, Pydantic v2 |
| Agent / LLM | LangGraph, OpenAI SDK (OpenAI-compatible) |
| Database | PostgreSQL 16 (SQLAlchemy 2 async + asyncpg), Alembic |
| Cache | Redis 7 |
| Frontend | Next.js ~15.3, React 19, TypeScript 5, Tailwind CSS 3 |
| Dev tooling | pytest, pytest-asyncio, ruff, mypy, ESLint |
| Infrastructure | Docker Compose (local), no app Dockerfile required for dev |

---

## Layer responsibilities

| Layer | Responsibility |
|-------|---------------|
| LLM / graph | Understand user text, propose fields, generate replies |
| Services | Validation, enrichment (lease lookup), payload building, outbound API calls |
| API | Auth context, request/response contracts, orchestration entry |
| Repositories | Persistence only |
| Observability | Traces, LLM/tool call records, state snapshots, metrics, feedback |

---

## Quick start

### 1 — Infrastructure

```bash
cd service-request-chatbot
docker compose up -d        # starts Postgres 16 on :5432 and Redis 7 on :6379
```

### 2 — Backend

Requires **Python 3.11+**.

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env        # fill in OPENAI_API_KEY and any integration URLs
alembic upgrade head        # run both DB migrations
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Interactive API docs: `http://localhost:8000/docs`
- Health check: `GET http://localhost:8000/api/v1/health`

### 3 — Frontend

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

- Tenant chat: `http://localhost:3000/service-request-chat`
- Observability admin: `http://localhost:3000/admin/agent-observability`

### 4 — Tests

```bash
cd backend
pytest                      # unit + integration + e2e (ASGI transport; Postgres not required for e2e)
```

---

## Environment variables

### Backend — `backend/.env.example`

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@localhost:5432/db` |
| `REDIS_URL` | `redis://localhost:6379` |
| `OPENAI_API_KEY` | LLM API key |
| `LLM_MODEL` | Model name (e.g. `gpt-4o`) |
| `LLM_BASE_URL` | Optional override for OpenAI-compatible endpoints |
| `LLM_CONFIDENCE_THRESHOLD` | Extraction confidence threshold |
| `SERVICE_REQUEST_API_BASE_URL` | Cenomi SR API base URL |
| `LEASE_TENANT_API_BASE_URL` | Lease-Tenant lookup API |
| `FILE_UPLOAD_API_BASE_URL` | File upload API |
| `JWT_SECRET_KEY` / `JWT_ALGORITHM` | Auth placeholders |
| `CORS_ORIGINS` | Comma-separated allowed origins |
| `API_V1_PREFIX` | Default `/api/v1` |
| `ENVIRONMENT` / `DEBUG` | Runtime environment flags |

### Frontend — `frontend/.env.example`

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_API_BASE_URL` | Backend origin, e.g. `http://localhost:8000` |
| `NEXT_PUBLIC_API_V1_PREFIX` | API prefix sent by the frontend client |

> **Note:** the primary chat endpoint is mounted at `/api/chat/service-request` (not under `/api/v1`). Ensure your frontend env and `chat-client.ts` target this path.

---

## Key API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | Health check |
| `POST` | `/api/chat/service-request` | Primary chat turn endpoint |
| `POST` | `/api/v1/upload` | File attachment upload (MIME-validated) |
| `GET/POST` | `/api/observability/...` | Traces, runs, feedback, state snapshots |
| `GET` | `/api/v1/observability/metrics/summary` | Aggregated agent metrics |

Full request/response schemas: [`docs/api-reference.md`](docs/api-reference.md).

---

## Implemented features

- **Conversational handover SR flow** driven by a multi-node LangGraph `StateGraph`
- **Lease lookup** via `LeaseLookupService` (local stub) or external Lease-Tenant API
- **Extraction, merge, and validation** nodes with missing-field re-prompting
- **Confirmation gate** (keyword-based + hard submission guards)
- **Payload builder + SR API submission** (`PayloadBuilderService`, `ServiceRequestAPIService`)
- **Injection guard** on every inbound user message
- **Full observability**: per-turn traces, LLM/tool call records, state snapshots, diffs, metrics, and user feedback — all persisted via Alembic migration `002`
- **Admin trace explorer** UI with replay and LLM/tool call drill-down

---

## Documentation

| File | Topic |
|------|-------|
| [`docs/architecture.md`](docs/architecture.md) | System design, LangGraph execution model, DB schema, integrations |
| [`docs/api-reference.md`](docs/api-reference.md) | Full HTTP API reference |
| [`docs/agent-design.md`](docs/agent-design.md) | Agent and graph node design |
| [`docs/handover-workflow.md`](docs/handover-workflow.md) | CREATE_SR sequence and schema |
| [`docs/security-guardrails.md`](docs/security-guardrails.md) | Injection guard, confirmation guards, submission guards |
| [`docs/observability.md`](docs/observability.md) | Observability data model and behavior |
| [`docs/local-development.md`](docs/local-development.md) | Full local setup, migrations, troubleshooting |
| [`docs/testing-strategy.md`](docs/testing-strategy.md) | Testing approach and coverage |
| [`docs/debugging-guide.md`](docs/debugging-guide.md) | Debugging tips |

---

## License

Proprietary / internal — update as appropriate for your organisation.
