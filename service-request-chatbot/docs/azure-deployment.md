# Azure Deployment Guide

> **Audience:** DevOps / platform engineer deploying the Cenomi RDD Chatbot to Azure.  
> **Last updated:** July 2026  
> **App version:** 2.0.0

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Azure Services Required](#3-azure-services-required)
4. [Dockerfiles](#4-dockerfiles)
5. [Azure Container Registry](#5-azure-container-registry)
6. [Azure Database for PostgreSQL](#6-azure-database-for-postgresql)
7. [Azure Cache for Redis](#7-azure-cache-for-redis)
8. [Azure AI Search (RAG)](#8-azure-ai-search-rag)
9. [Backend — Azure Container Apps](#9-backend--azure-container-apps)
10. [Frontend — Azure Static Web Apps](#10-frontend--azure-static-web-apps)
11. [Environment Variables Reference](#11-environment-variables-reference)
12. [MSP Platform Integration Configuration](#12-msp-platform-integration-configuration)
13. [Health Checks & Probes](#13-health-checks--probes)
14. [CI/CD with GitHub Actions](#14-cicd-with-github-actions)
15. [Post-Deployment Smoke Test](#15-post-deployment-smoke-test)
16. [Scaling & Cost Notes](#16-scaling--cost-notes)

---

## 1. Architecture Overview

```
                    ┌──────────────────────────────────────────────────────────┐
                    │                    Azure                                  │
                    │                                                            │
  MSP Platform ─────┼──► Container App (FastAPI backend)                       │
  Frontend           │      POST /api/v1/chat                                   │
                    │      POST /api/v1/chat/stream                             │
  RDD Chatbot ───────┼──► Container App (FastAPI backend)                       │
  Frontend           │      POST /api/v2/chat/service-request                   │
                    │                │                                          │
                    │     ┌──────────┼──────────────┐                          │
                    │     ▼          ▼              ▼                           │
                    │  Azure DB   Azure Cache   Azure AI Search                 │
                    │  (Postgres)  (Redis)       (cenomi-help-index)            │
                    │                │                                          │
  Next.js UI ────────┼──► Static Web App                                        │
                    │      (or Container App for SSR)                           │
                    └──────────────────────────────────────────────────────────┘
                                      │
                         External: OpenAI API / Azure OpenAI
                         External: Cenomi Platform APIs
```

---

## 2. Prerequisites

- Azure CLI (`az`) installed and logged in
- Docker Desktop
- GitHub repository with Actions enabled
- Azure subscription with Contributor access
- An OpenAI API key (or Azure OpenAI deployment)

```bash
# Log in
az login

# Set subscription
az account set --subscription "<your-subscription-id>"
```

---

## 3. Azure Services Required

| Service | SKU | Notes |
|---------|-----|-------|
| Azure Container Registry | Basic | Stores backend Docker image |
| Azure Container Apps (backend) | Consumption | FastAPI + LangGraph |
| Azure Static Web Apps (frontend) | Free / Standard | Next.js 15 static export |
| Azure Database for PostgreSQL Flexible Server | Burstable B1ms (dev) / General Purpose D2s (prod) | Primary DB |
| Azure Cache for Redis | C0 Basic (dev) / C1 Standard (prod) | Used for health probe + future rate limiting |
| Azure AI Search | Basic | `cenomi-help-index` for RAG |
| Azure OpenAI (optional) | S0 | Alternative to direct OpenAI API |
| Azure Key Vault (recommended) | Standard | Secret storage |

Estimated monthly cost (dev tier): ~$80–$130 USD  
Estimated monthly cost (production, 2 replicas): ~$300–$500 USD

---

## 4. Dockerfiles

The repository does not currently ship Dockerfiles. Create them as follows:

### 4.1 Backend Dockerfile

Create `service-request-chatbot/backend/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System deps for asyncpg and bcrypt
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY . .

# Run migrations then start app
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2"]

EXPOSE 8000
```

### 4.2 Frontend Dockerfile

Create `service-request-chatbot/frontend/Dockerfile`:

```dockerfile
FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
```

> For `next.config.js`, enable standalone output:
> ```js
> module.exports = { output: 'standalone' };
> ```

---

## 5. Azure Container Registry

```bash
# Create resource group
az group create --name cenomi-rdd-rg --location uaenorth

# Create ACR
az acr create \
  --resource-group cenomi-rdd-rg \
  --name cenomirddacr \
  --sku Basic \
  --admin-enabled true

# Log in
az acr login --name cenomirddacr

# Build and push backend image
cd service-request-chatbot/backend
docker build -t cenomirddacr.azurecr.io/rdd-chatbot-backend:latest .
docker push cenomirddacr.azurecr.io/rdd-chatbot-backend:latest
```

---

## 6. Azure Database for PostgreSQL

```bash
# Create Flexible Server
az postgres flexible-server create \
  --resource-group cenomi-rdd-rg \
  --name cenomi-rdd-postgres \
  --location uaenorth \
  --admin-user pgadmin \
  --admin-password "<strong-password>" \
  --sku-name Standard_B1ms \
  --tier Burstable \
  --storage-size 32 \
  --version 16

# Create database
az postgres flexible-server db create \
  --resource-group cenomi-rdd-rg \
  --server-name cenomi-rdd-postgres \
  --database-name service_request_chatbot

# Allow Container Apps egress (or use VNet integration)
az postgres flexible-server firewall-rule create \
  --resource-group cenomi-rdd-rg \
  --name cenomi-rdd-postgres \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0
```

**Connection string format:**
```
postgresql+asyncpg://pgadmin:<password>@cenomi-rdd-postgres.postgres.database.azure.com/service_request_chatbot?ssl=require
```

**Run migrations on first deploy:**
The backend Dockerfile runs `alembic upgrade head` before starting uvicorn. Verify this runs cleanly in the Container App startup logs.

---

## 7. Azure Cache for Redis

```bash
az redis create \
  --resource-group cenomi-rdd-rg \
  --name cenomi-rdd-redis \
  --location uaenorth \
  --sku Basic \
  --vm-size c0

# Get connection string
az redis show \
  --resource-group cenomi-rdd-rg \
  --name cenomi-rdd-redis \
  --query "hostName" -o tsv
```

**Redis URL format:**
```
rediss://:<primary-key>@cenomi-rdd-redis.redis.cache.windows.net:6380/0
```

> Note: Azure Redis uses SSL on port 6380. Set `REDIS_URL` accordingly.

---

## 8. Azure AI Search (RAG)

```bash
# Create Azure AI Search service
az search service create \
  --resource-group cenomi-rdd-rg \
  --name cenomi-rdd-search \
  --location uaenorth \
  --sku basic \
  --partition-count 1 \
  --replica-count 1
```

**Required environment variables:**
```
AZURE_SEARCH_ENDPOINT=https://cenomi-rdd-search.search.windows.net
AZURE_SEARCH_API_KEY=<admin-key>
AZURE_SEARCH_INDEX_NAME=cenomi-help-index
SEARCH_PROVIDER=azure_search
```

**Index schema** (must match `SearchResult` dataclass in `app/integrations/search/base.py`):

Each document in the index should have:
- `id` (key field)
- `source_type` (`help_content` | `user_guide` | `mall_info` | `key_contact` | `event`)
- `title`
- `content`
- `url_pattern`
- `mall_name`
- `language` (`en` | `ar`)
- `content_vector` (embedding, 1536-dim for `text-embedding-3-small`)

**Indexing:** Use the Azure AI Search indexer or a custom script with the Azure SDK. The search repository (`app/integrations/search/azure_search_repository.py`) uses hybrid search (keyword + vector).

---

## 9. Backend — Azure Container Apps

### 9.1 Create Container Apps environment

```bash
# Create Log Analytics workspace
az monitor log-analytics workspace create \
  --resource-group cenomi-rdd-rg \
  --workspace-name cenomi-rdd-logs

WORKSPACE_ID=$(az monitor log-analytics workspace show \
  --resource-group cenomi-rdd-rg \
  --workspace-name cenomi-rdd-logs \
  --query "customerId" -o tsv)

WORKSPACE_KEY=$(az monitor log-analytics workspace get-shared-keys \
  --resource-group cenomi-rdd-rg \
  --workspace-name cenomi-rdd-logs \
  --query "primarySharedKey" -o tsv)

# Create Container Apps environment
az containerapp env create \
  --resource-group cenomi-rdd-rg \
  --name cenomi-rdd-env \
  --location uaenorth \
  --logs-workspace-id $WORKSPACE_ID \
  --logs-workspace-key $WORKSPACE_KEY
```

### 9.2 Deploy backend Container App

```bash
az containerapp create \
  --resource-group cenomi-rdd-rg \
  --name rdd-chatbot-backend \
  --environment cenomi-rdd-env \
  --image cenomirddacr.azurecr.io/rdd-chatbot-backend:latest \
  --registry-server cenomirddacr.azurecr.io \
  --registry-username cenomirddacr \
  --registry-password "<acr-password>" \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 5 \
  --cpu 1 \
  --memory 2Gi \
  --env-vars \
    ENVIRONMENT=production \
    DATABASE_URL="postgresql+asyncpg://pgadmin:<password>@cenomi-rdd-postgres.postgres.database.azure.com/service_request_chatbot?ssl=require" \
    REDIS_URL="rediss://:<redis-key>@cenomi-rdd-redis.redis.cache.windows.net:6380/0" \
    OPENAI_API_KEY="<openai-key>" \
    JWT_SECRET_KEY="<strong-jwt-secret>" \
    RBAC_ENFORCE=true \
    MSP_SERVICE_TOKEN="<msp-service-uuid>" \
    PLATFORM_INTERNAL_API_TOKEN="<platform-token>" \
    PLATFORM_LOGIN_EMAIL="service@cenomi.com" \
    SERVICE_REQUEST_API_BASE_URL="https://your-platform-api.cenomi.com" \
    LEASE_TENANT_API_BASE_URL="https://your-lease-api.cenomi.com" \
    AZURE_SEARCH_ENDPOINT="https://cenomi-rdd-search.search.windows.net" \
    AZURE_SEARCH_API_KEY="<search-key>" \
    AZURE_SEARCH_INDEX_NAME="cenomi-help-index" \
    CORS_ORIGINS="https://your-frontend.azurestaticapps.net,https://msp-platform.cenomi.com"
```

### 9.3 Get backend URL

```bash
az containerapp show \
  --resource-group cenomi-rdd-rg \
  --name rdd-chatbot-backend \
  --query "properties.configuration.ingress.fqdn" -o tsv
# e.g. rdd-chatbot-backend.nicefield-abc123.uaenorth.azurecontainerapps.io
```

### 9.4 Use Azure Key Vault for secrets (recommended)

```bash
# Create Key Vault
az keyvault create \
  --resource-group cenomi-rdd-rg \
  --name cenomi-rdd-kv \
  --location uaenorth

# Store secrets
az keyvault secret set --vault-name cenomi-rdd-kv --name openai-api-key --value "<key>"
az keyvault secret set --vault-name cenomi-rdd-kv --name jwt-secret-key --value "<key>"
az keyvault secret set --vault-name cenomi-rdd-kv --name msp-service-token --value "<token>"
az keyvault secret set --vault-name cenomi-rdd-kv --name database-url --value "<url>"

# Enable managed identity on Container App and grant Key Vault access
az containerapp identity assign \
  --resource-group cenomi-rdd-rg \
  --name rdd-chatbot-backend \
  --system-assigned

PRINCIPAL_ID=$(az containerapp show \
  --resource-group cenomi-rdd-rg \
  --name rdd-chatbot-backend \
  --query "identity.principalId" -o tsv)

az keyvault set-policy \
  --name cenomi-rdd-kv \
  --object-id $PRINCIPAL_ID \
  --secret-permissions get list
```

---

## 10. Frontend — Azure Static Web Apps

> Use Azure Static Web Apps for a fully static Next.js export, or a Container App if SSR features are needed.

### Option A — Static Web Apps (recommended for Next.js 15 with `output: 'export'`)

```bash
az staticwebapp create \
  --resource-group cenomi-rdd-rg \
  --name cenomi-rdd-frontend \
  --location uaenorth \
  --source "https://github.com/<org>/Cenomi-RDD-Chatbot" \
  --branch main \
  --app-location "service-request-chatbot/frontend" \
  --output-location "out" \
  --login-with-github
```

Set app settings in the portal or via CLI:
```bash
az staticwebapp appsettings set \
  --name cenomi-rdd-frontend \
  --setting-names \
    NEXT_PUBLIC_API_BASE_URL="https://rdd-chatbot-backend.nicefield-abc123.uaenorth.azurecontainerapps.io" \
    NEXT_PUBLIC_API_V1_PREFIX="/api/v1"
```

### Option B — Container App (SSR / App Router server components)

Build the frontend Docker image, push to ACR, and deploy as a separate Container App on port 3000 with `ingress external`.

---

## 11. Environment Variables Reference

### Backend (production minimum)

| Variable | Value | Notes |
|----------|-------|-------|
| `ENVIRONMENT` | `production` | Disables `/docs` and `/redoc` |
| `DATABASE_URL` | `postgresql+asyncpg://...?ssl=require` | Must use SSL |
| `REDIS_URL` | `rediss://...:6380/0` | SSL port for Azure Redis |
| `OPENAI_API_KEY` | `sk-...` | Or use `LLM_BASE_URL` for Azure OpenAI |
| `JWT_SECRET_KEY` | Random 64-char string | Never reuse across environments |
| `RBAC_ENFORCE` | `true` | Enforce JWT in production |
| `MSP_SERVICE_TOKEN` | UUID | Token MSP Platform frontend sends as `x-internal-api-token` |
| `PLATFORM_INTERNAL_API_TOKEN` | Secret | Outbound token for Cenomi platform login |
| `PLATFORM_LOGIN_EMAIL` | Email | Service account |
| `SERVICE_REQUEST_API_BASE_URL` | URL | Cenomi platform SR API |
| `LEASE_TENANT_API_BASE_URL` | URL | Cenomi lease/tenant API |
| `AZURE_SEARCH_ENDPOINT` | URL | Azure AI Search endpoint |
| `AZURE_SEARCH_API_KEY` | Secret | Azure AI Search admin key |
| `AZURE_SEARCH_INDEX_NAME` | `cenomi-help-index` | Search index name |
| `CORS_ORIGINS` | Comma-separated URLs | Frontend origins + MSP Platform origin |
| `API_V1_PREFIX` | `/api/v1` | Leave default |
| `API_V2_PREFIX` | `/api/v2` | Leave default |

### Using Azure OpenAI instead of OpenAI

```bash
LLM_BASE_URL=https://<instance>.openai.azure.com/openai/deployments/<deployment-name>
LLM_MODEL=gpt-4o-mini          # Must match your Azure deployment name
EMBEDDING_PROVIDER=azure_openai
AZURE_AI_ENDPOINT=https://<instance>.openai.azure.com
AZURE_AI_API_KEY=<azure-openai-key>
AZURE_AI_API_VERSION=2024-02-15-preview
```

### Frontend

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_BASE_URL` | Backend Container App FQDN (with `https://`) |
| `NEXT_PUBLIC_API_V1_PREFIX` | `/api/v1` |

---

## 12. MSP Platform Integration Configuration

When deploying for MSP Platform integration, ensure:

1. **`MSP_SERVICE_TOKEN`** is set to a UUID shared with the MSP Platform team. The MSP frontend sends this as the `x-internal-api-token` header.

2. **CORS** includes the MSP Platform frontend's origin:
   ```
   CORS_ORIGINS=https://rdd-frontend.azurestaticapps.net,https://msp-platform.cenomi.com
   ```

3. **Endpoints exposed to MSP:**
   - `POST https://<backend-fqdn>/api/v1/chat` — sync
   - `POST https://<backend-fqdn>/api/v1/chat/stream` — SSE (primary)

4. **SSL is required** — Azure Container Apps provide TLS termination automatically. Do not disable HTTPS.

5. **MSP JWT validation:** The MSP frontend sends `Authorization: Bearer <ai_token>` issued by `cenomi-api-2`. The backend's `get_auth_context()` will decode it using `JWT_SECRET_KEY`. Coordinate the JWT signing key with the MSP team, or set `RBAC_ENFORCE=false` to run in shadow mode initially.

6. **Smoke test the MSP integration:**
   ```bash
   curl -X POST https://<backend-fqdn>/api/v1/chat \
     -H "Content-Type: application/json" \
     -H "x-internal-api-token: <MSP_SERVICE_TOKEN>" \
     -d '{"message": "How do I submit a service request?"}'
   ```
   Expected: `200 OK` with `conversation_id`, `message_id`, `message`, `sources`, `language`.

---

## 13. Health Checks & Probes

### Liveness probe
```
GET /api/v1/health
→ 200 { "status": "ok" }
```

### Readiness probe
```
GET /api/v1/ready
→ 200 { "status": "ready", "db": "ok", "redis": "ok" }
→ 503 { "status": "unavailable", "db": "error", "redis": "ok" }
```

### Container Apps probe configuration

In `containerapp.yaml` or via CLI:
```yaml
probes:
  liveness:
    httpGet:
      path: /api/v1/health
      port: 8000
    initialDelaySeconds: 10
    periodSeconds: 30
  readiness:
    httpGet:
      path: /api/v1/ready
      port: 8000
    initialDelaySeconds: 15
    periodSeconds: 10
    failureThreshold: 3
```

---

## 14. CI/CD with GitHub Actions

Create `.github/workflows/deploy-backend.yml`:

```yaml
name: Deploy Backend

on:
  push:
    branches: [main]
    paths:
      - 'service-request-chatbot/backend/**'

env:
  REGISTRY: cenomirddacr.azurecr.io
  IMAGE_NAME: rdd-chatbot-backend
  RESOURCE_GROUP: cenomi-rdd-rg
  CONTAINER_APP: rdd-chatbot-backend

jobs:
  test:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: service-request-chatbot/backend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -e ".[dev]"
      - run: python -m pytest tests/unit/ tests/integration/ -q --tb=short

  build-and-deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Log in to Azure
        uses: azure/login@v2
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}

      - name: Log in to ACR
        run: az acr login --name cenomirddacr

      - name: Build and push Docker image
        working-directory: service-request-chatbot/backend
        run: |
          docker build -t $REGISTRY/$IMAGE_NAME:${{ github.sha }} .
          docker tag $REGISTRY/$IMAGE_NAME:${{ github.sha }} $REGISTRY/$IMAGE_NAME:latest
          docker push $REGISTRY/$IMAGE_NAME:${{ github.sha }}
          docker push $REGISTRY/$IMAGE_NAME:latest

      - name: Deploy to Container Apps
        run: |
          az containerapp update \
            --resource-group $RESOURCE_GROUP \
            --name $CONTAINER_APP \
            --image $REGISTRY/$IMAGE_NAME:${{ github.sha }}
```

Create `.github/workflows/deploy-frontend.yml`:

```yaml
name: Deploy Frontend

on:
  push:
    branches: [main]
    paths:
      - 'service-request-chatbot/frontend/**'

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build and Deploy to Static Web Apps
        uses: Azure/static-web-apps-deploy@v1
        with:
          azure_static_web_apps_api_token: ${{ secrets.AZURE_STATIC_WEB_APPS_API_TOKEN }}
          repo_token: ${{ secrets.GITHUB_TOKEN }}
          action: upload
          app_location: service-request-chatbot/frontend
          output_location: out
          app_build_command: npm run build
```

**Required GitHub secrets:**
- `AZURE_CREDENTIALS` — service principal JSON from `az ad sp create-for-rbac`
- `AZURE_STATIC_WEB_APPS_API_TOKEN` — from Azure Static Web Apps portal

---

## 15. Post-Deployment Smoke Test

Run these checks after every deployment:

```bash
BASE=https://<backend-fqdn>

# 1. Liveness
curl -sf $BASE/api/v1/health && echo "✓ liveness"

# 2. Readiness
curl -sf $BASE/api/v1/ready && echo "✓ readiness"

# 3. RDD chat (v2)
curl -sf -X POST $BASE/api/v2/chat/service-request \
  -H "Content-Type: application/json" \
  -d '{"user_id":"smoke","message":"hello"}' | python3 -m json.tool

# 4. MSP sync help (v1)
curl -sf -X POST $BASE/api/v1/chat \
  -H "Content-Type: application/json" \
  -H "x-internal-api-token: $MSP_SERVICE_TOKEN" \
  -d '{"message":"How do I submit a service request?"}' | python3 -m json.tool

# 5. MSP SSE stream (v1)
curl -N -X POST $BASE/api/v1/chat/stream \
  -H "Content-Type: application/json" \
  -H "x-internal-api-token: $MSP_SERVICE_TOKEN" \
  -H "Accept: text/event-stream" \
  -d '{"message":"What is FM Review?"}'
# Expected: event: token, event: source (if RAG), event: done
```

---

## 16. Scaling & Cost Notes

### Scaling triggers (Container Apps)

| Metric | Scale-out at | Scale-in at |
|--------|-------------|-------------|
| HTTP concurrent requests | > 10/replica | < 5/replica |
| CPU | > 70% | < 30% |

The graph is fully async (`ainvoke`) and each request blocks a worker for 2–8 seconds (LLM call). A single container with `--workers 2` handles ~3–5 concurrent users comfortably. For 20+ concurrent users, set `--min-replicas 2 --max-replicas 10`.

### Cost optimisation

- Use `gpt-4o-mini` (default) — 10× cheaper than `gpt-4o` with comparable quality for intent classification and FAQ answering.
- Azure AI Search Basic tier handles up to 15 indexes and 2GB storage — sufficient for the help content KB.
- PostgreSQL Burstable B1ms is fine for development and light production loads. Upgrade to General Purpose D2s for > 50 concurrent sessions.
- Container Apps Consumption plan scales to zero at night — you only pay per request.

### Networking (production hardening)

- Deploy PostgreSQL and Redis into a VNet and use private endpoints — remove the public firewall rule added above.
- Place Container Apps in the same VNet using VNet integration.
- Use Azure Front Door or Application Gateway for WAF, global routing, and SSL offloading if serving both RDD frontend and MSP traffic.
