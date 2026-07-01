# Local Development

## Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.11+ |
| Node.js | 18+ |
| Docker + Docker Compose | v2 |
| Git | any |

---

## Setup Instructions

### 1. Clone and navigate

```bash
git clone <repo-url>
cd Cenomi-RDD-Chatbot/service-request-chatbot
```

### 2. Start infrastructure (Docker Compose)

```bash
docker compose up -d
```

This starts:

| Service | Container | Port | Credentials |
|---------|-----------|------|-------------|
| PostgreSQL 16 | `sr-chatbot-postgres` | `5432` | `postgres:postgres` / db `service_request_chatbot` |
| Redis 7 | `sr-chatbot-redis` | `6379` | none |

Check health:

```bash
docker compose ps
# Both services should show "healthy"
```

Stop:

```bash
docker compose down
# To also delete volumes:
docker compose down -v
```

---

## Environment Variables

### Backend (`backend/.env`)

Copy the example file:

```bash
cd backend
cp .env.example .env
```

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `APP_NAME` | `service-request-chatbot-api` | No | Application name |
| `ENVIRONMENT` | `development` | No | `development` \| `staging` \| `production` |
| `DEBUG` | `false` | No | Enable debug logging |
| `API_V1_PREFIX` | `/api/v1` | No | Prefix for versioned routes |
| `CORS_ORIGINS` | `http://localhost:3000` | No | Comma-separated allowed origins |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/service_request_chatbot` | **Yes** | Must use `postgresql+asyncpg://` driver prefix |
| `REDIS_URL` | `redis://localhost:6379/0` | No | Redis connection URL |
| `SERVICE_REQUEST_API_BASE_URL` | *(empty)* | **Yes (prod)** | Cenomi SR API — leave empty for mock mode |
| `LEASE_TENANT_API_BASE_URL` | *(empty)* | **Yes (prod)** | Cenomi Lease-Tenant API — leave empty for mock mode |
| `FILE_UPLOAD_API_BASE_URL` | *(empty)* | No | Reserved — uploads use `SERVICE_REQUEST_API_BASE_URL + /files` |
| `PLATFORM_AUTH_BASE_URL` | *(empty)* | No | Platform auth endpoint — defaults to `SERVICE_REQUEST_API_BASE_URL` |
| `PLATFORM_INTERNAL_API_TOKEN` | *(empty)* | **Yes (prod)** | `x-internal-api-token` for service-to-service platform login |
| `PLATFORM_LOGIN_EMAIL` | *(empty)* | **Yes (prod)** | Email for service-to-service platform login |
| `JWT_SECRET_KEY` | `change-me-in-production` | **Yes (prod)** | JWT signing key |
| `JWT_ALGORITHM` | `HS256` | No | JWT algorithm |
| `JWT_EXPIRE_MINUTES` | `60` | No | JWT token expiry in minutes |
| `RBAC_ENFORCE` | `false` | No | `false` = shadow mode (warn + pass); `true` = reject unauthenticated requests |
| `OPENAI_API_KEY` | *(empty)* | **Yes** | OpenAI API key for LLM calls |
| `LLM_MODEL` | `gpt-4o-mini` | No | Model name |
| `LLM_BASE_URL` | *(empty)* | No | Custom LLM base URL (Azure OpenAI, proxy, etc.) |
| `LLM_CONFIDENCE_THRESHOLD` | `0.6` | No | Minimum confidence for intent/extraction acceptance |

### Frontend (`frontend/.env.local`)

```bash
cd frontend
cp .env.example .env.local
```

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Backend base URL (browser-accessible) |
| `NEXT_PUBLIC_API_V1_PREFIX` | `/api/v1` | **Set to `""` for local dev** — the chat route is at `/api/chat/service-request`, not `/api/v1/chat/service-request` |

> **Important:** Set `NEXT_PUBLIC_API_V1_PREFIX=` (empty) in `.env.local` for local development, or the chat API calls will 404. The frontend `chat-client.ts` builds the URL as `${NEXT_PUBLIC_API_BASE_URL}${NEXT_PUBLIC_API_V1_PREFIX}/chat/service-request`.

---

## Running Backend

```bash
cd backend

# Create virtual environment (first time only)
python3.11 -m venv .venv

# Activate
source .venv/bin/activate          # macOS/Linux
# .venv\Scripts\activate           # Windows

# Install dependencies (first time or after pyproject.toml changes)
pip install --upgrade pip
pip install -e ".[dev]"

# Apply migrations (first time or after schema changes)
alembic upgrade head

# Seed test users (first time only)
python scripts/seed_users.py
# Creates: aisha@cenomi.com / test1234 (MALL_MANAGER)
#          khalid@cenomi.com / test1234 (FM_MANAGER)
#          omar@cenomi.com   / test1234 (OPERATIONS)
#          sara@cenomi.com   / test1234 (DD_ENGINEER)
#          admin@cenomi.com  / test1234 (ADMIN)

# Start development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Available once running:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Health: http://localhost:8000/api/v1/health

---

## Running Frontend

```bash
cd frontend

# Install Node dependencies (first time or after package.json changes)
npm install

# Start development server
npm run dev
```

Available once running:

- Login: http://localhost:3000/login (`aisha@cenomi.com` / `test1234`)
- Chat UI: http://localhost:3000/service-request-chat
- Admin observability: http://localhost:3000/admin/agent-observability

---

## Running Migrations

Migrations use **Alembic** against the `DATABASE_URL` in `backend/.env`.

```bash
cd backend
source .venv/bin/activate

# Apply all pending migrations
alembic upgrade head

# Check current revision
alembic current

# See migration history
alembic history --verbose
```

**Migration files:**

| Revision | File | What it creates |
|----------|------|----------------|
| `001` | `alembic/versions/001_initial_schema.py` | `chat_sessions`, `chat_messages`, `service_request_drafts`, `service_request_chat_audit_logs`, legacy observability stubs |
| `002` | `alembic/versions/002_agent_observability.py` | `agent_traces`, `agent_runs`, `agent_state_snapshots`, `agent_state_diffs`, `agent_llm_calls`, `agent_tool_calls`, `agent_feedback` |
| `003` | `alembic/versions/003_users.py` | `users` table — `username`, `email`, `password_hash`, `role`, `unique_property_ids`, `mall_names`, `is_global_admin`, `is_active` |

**Create a new migration** (after changing `app/db/models.py`):

```bash
alembic revision --autogenerate -m "describe_your_change"
# Review the generated file in alembic/versions/ before applying
alembic upgrade head
```

---

## Running Tests

```bash
cd backend
source .venv/bin/activate

# All tests
pytest

# With verbose output
pytest -v

# Specific layer
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest tests/e2e/ -v

# Specific file
pytest tests/unit/test_security_guardrails.py -v

# With coverage
pytest --cov=app --cov-report=html
# Open htmlcov/index.html in browser

# Stop on first failure
pytest -x
```

**E2E tests require no running server** — they use `httpx.AsyncClient` with `ASGITransport` directly against the FastAPI app. No Docker / Postgres required for E2E tests (DB is mocked).

---

## Running Eval Suite (Live)

The `tests/eval/` scripts drive a **running backend** over HTTP. They are not pytest — run them directly:

```bash
cd backend
source .venv/bin/activate

# Make sure the backend is running on port 8000 first

# Run all 12 manual test blocks (authenticates as aisha@cenomi.com)
PYTHONPATH=$(pwd) python tests/eval/test_manual_blocks.py --verbose

# Run 33 automated scenarios
PYTHONPATH=$(pwd) python tests/eval/run_eval.py --verbose

# Score a specific session from the observability replay
PYTHONPATH=$(pwd) python tests/eval/eval_session.py --session-id <uuid>

# Compile all results into a markdown report
PYTHONPATH=$(pwd) python tests/eval/report_writer.py
# → results/manual-test-eval-report-YYYY-MM-DD.md
```

> **Note:** Use `PYTHONPATH=$(pwd)` when running scripts from `backend/` — the `tests` package import requires the backend root to be on the path.

---

## Docker Compose Reference

Full `docker-compose.yml` is at the `service-request-chatbot/` root:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: sr-chatbot-postgres
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: service_request_chatbot
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d service_request_chatbot"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: sr-chatbot-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  postgres_data:
  redis_data:
```

No application `Dockerfile` is included — the backend is run with `uvicorn` and the frontend with `next dev` / `next start` directly.

---

## Common Setup Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| `asyncpg` connection error | Wrong `DATABASE_URL` format | Must start with `postgresql+asyncpg://`, not `postgresql://` |
| `ModuleNotFoundError: app` | Virtual environment not activated | `source .venv/bin/activate` |
| Frontend calls fail with 404 | `NEXT_PUBLIC_API_V1_PREFIX=/api/v1` | Set it to `""` in `.env.local` |
| Alembic `can't locate revision` | Migrations not applied | `alembic upgrade head` |
| Login returns 401 `Incorrect username or password` | Users not seeded | `python scripts/seed_users.py` |
| `OPENAI_API_KEY` missing error | LLM calls fail without key | Set `OPENAI_API_KEY=sk-...` in `backend/.env` |
| Redis connection refused | Redis not started | `docker compose up -d redis` |
| Eval scripts fail with `ModuleNotFoundError: tests` | PYTHONPATH not set | Prefix with `PYTHONPATH=$(pwd)` when running from `backend/` |
