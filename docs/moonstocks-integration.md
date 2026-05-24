# Moonstocks × Equity OS — 3-service plan

## Target architecture (AWS)

| # | Service | Repo | Role |
|---|---------|------|------|
| 1 | **equity-os** | `companyData` | Screener, company pages, EODHD charts, **AI report storage** (replaces `moonstocks-api`) |
| 2 | **moonstocks-ai-analyzer** | `moonstocks-ai-analyzer` | Async LLM analysis (OpenAI or Claude) → POSTs JSON to equity-os |
| 3 | **moonstocks-app** | (existing frontend) | Public Moonstocks UI — point API base at equity-os |

**Retire:** `moonstocks-api` (C#) after equity-os is live in ECS.

```text
Browser → equity-os (Flask :3000)
              ↑ POST /api/analysis/{TICKER.EX}
              │
moonstocks-ai-analyzer ← POST /{TICKER.EX} trigger (equity-os or UI)
```

## LLM providers (analyzer)

The analyzer picks **one** backend:

| Provider | Keys | Data | When used |
|----------|------|------|-----------|
| **OpenAI** (recommended locally) | `OPENAI_API_KEY`, optional `OPENAI_MODEL` | EODHD REST prefetch + stock-analysis skill in prompt | `ANALYZER_LLM_PROVIDER=openai`, or only `OPENAI_API_KEY` set |
| **Anthropic** | `ANTHROPIC_API_KEY` | EODHD MCP via Claude Agent SDK + skill | Default if both keys set; or only `ANTHROPIC_API_KEY` |

Override: `ANALYZER_LLM_PREFER=openai` or `anthropic` when both API keys exist.

Check active provider: `GET http://localhost:8000/health` → `"llm_provider": "openai"`.

## API contract (C# compatible)

| Method | Path | Caller |
|--------|------|--------|
| GET | `/api/analysis` | moonstocks-app |
| POST | `/api/analysis/{ticker}` | analyzer (`jsonReport` string) |
| POST | `/api/analysis/{ticker}/trigger` | moonstocks-app |
| GET | `/api/moonstocks/{ticker}` | Equity OS company page |
| POST | `/api/moonstocks/{ticker}/trigger` | Equity OS company page |
| GET | `/health` | ECS / load balancer |

## Environment variables

### equity-os (`companyData`)

| Variable | Purpose |
|----------|---------|
| `MOONSTOCKS_DATABASE_URL` | **Postgres** (required for `run_server.py`, Docker, prod) |
| `MOONSTOCKS_DB_PATH` | **Tests only** — in-memory/temp SQLite in unit tests and `e2e_moonstocks_local.py` |
| `MOONSTOCKS_ANALYZER_URL` | Analyzer base URL (no trailing slash), e.g. `http://127.0.0.1:8000` |
| `ANALYZER_API_KEY` | Optional; sent to analyzer on trigger, required on ingest if set |
| `MOONSTOCKS_INGEST_API_KEY` | Optional override for ingest-only secret |
| `MOONSTOCKS_API_URL` | Moonstocks public app link on company page (default: prod LB) |
| `EODHD_API_KEY` | Fundamentals / quotes |

### moonstocks-ai-analyzer

| Variable | Purpose |
|----------|---------|
| `ANALYSIS_API_BASE_URL` | equity-os base, e.g. `http://127.0.0.1:3000` or `http://equity-os-prod:3000` |
| `ANALYZER_API_KEY` | Inbound trigger auth + outbound ingest to equity-os |
| `EODHD_API_KEY` | Required for both providers |
| `OPENAI_API_KEY` | OpenAI provider |
| `OPENAI_MODEL` | Default `gpt-4o` |
| `ANALYZER_LLM_PROVIDER` | `openai` or `anthropic` |
| `ANALYZER_LLM_PREFER` | `openai` or `anthropic` when both keys exist |
| `ANTHROPIC_API_KEY` | Claude provider only |

The analyzer loads `moonstocks-ai-analyzer/.env` and the parent `companyData/.env`, so a single root `.env` with `OPENAI_API_KEY` is enough for local dev.

## Local dev (native host + Postgres container)

**Postgres** (prod-like, exposed on host):

```bash
docker compose -f docker-compose.moonstocks.yml up -d postgres
# .env from .env.native.example → MOONSTOCKS_DATABASE_URL=@127.0.0.1:5432/...
```

**Terminal 1 — equity-os**

```bash
pip install -r web/requirements.txt
# .env: MOONSTOCKS_DATABASE_URL + MOONSTOCKS_ANALYZER_URL=http://127.0.0.1:8000
python run_server.py   # exits with a clear error if Postgres is down or URL uses host "postgres"
```

**Terminal 2 — analyzer (OpenAI)**

```bash
cd moonstocks-ai-analyzer
pip install -r requirements.txt
set ANALYSIS_API_BASE_URL=http://127.0.0.1:3000
set ANALYZER_LLM_PROVIDER=openai
# OPENAI_API_KEY and EODHD_API_KEY from parent .env or set here
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:3000/company/DECK → Moonstocks AI → **Trigger Analysis** (~3 min for a real OpenAI run).

## Local dev (Docker)

Requires Docker Desktop.

```bash
cp .env.moonstocks.example .env
# Edit .env: EODHD_API_KEY, OPENAI_API_KEY, optional ANALYZER_API_KEY

docker compose -f docker-compose.moonstocks.yml up --build
```

- Equity OS: http://localhost:3000  
- Analyzer: http://localhost:8000 (`ANALYZER_LLM_PROVIDER=openai` in compose)  
- Trigger: http://localhost:3000/company/DECK  

## Tests

From `companyData` root (venv recommended):

```bash
pip install -r web/requirements.txt tzdata
pip install openai   # if running analyzer tests that import moonstocks-ai-analyzer

# Full unit suite
python -m unittest discover -s tests -p "test_*.py" -v

# Moonstocks API + provider selection
python -m unittest tests.test_moonstocks_api tests.test_analyzer_provider -v

# E2E smoke (mock analyzer, no OpenAI/Claude spend)
python scripts/e2e_moonstocks_local.py --start-server
```

## AWS rollout checklist

1. **Deploy equity-os** to ECS — `Dockerfile`, `deploy/aws/equity-os-task-definition.json`.
2. **RDS Postgres**: `MOONSTOCKS_DATABASE_URL` from Secrets Manager (`deploy/aws/rds-moonstocks.yaml`).
3. **Analyzer task def**: `ANALYSIS_API_BASE_URL=http://equity-os-prod:3000`; add `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`) and `ANALYZER_LLM_PROVIDER` to secrets/env.
4. **Point moonstocks-app** API URL to equity-os LB (`MOONSTOCKS_API_URL` on equity-os for “View on Moonstocks” links).
5. **Scale down** `moonstocks-api` ECS service.
6. Smoke: trigger `DECK.US`, confirm DB row and company page section.

## Storage

- **Production / ECS / local dev:** Postgres via `MOONSTOCKS_DATABASE_URL` only.
- **Unit/E2E tests:** temporary SQLite via `MOONSTOCKS_DB_PATH` (not used by `run_server.py`).
- **Local host:** `docker compose … up -d postgres` + `@127.0.0.1:5432` in `.env` (see `.env.native.example`).

## Status

- [x] Flask endpoints + SQLite in `companyData`
- [x] Company page Moonstocks section
- [x] Analyzer → `/api/analysis/{ticker}` with optional `X-API-Key`
- [x] OpenAI + Anthropic provider switch
- [x] Docker Compose local stack
- [x] Production `Dockerfile` + `web/gunicorn.conf.py`
- [x] ECS template `deploy/aws/equity-os-task-definition.json`
- [x] Unit + E2E tests (`test_moonstocks_api`, `test_analyzer_provider`, `scripts/e2e_moonstocks_local.py`)
- [x] Postgres store (`web/moonstocks_store.py`) + RDS CloudFormation
- [x] Deploy scripts (`deploy/aws/README.md`, `scripts/deploy_moonstocks_ecr.ps1`)
- [ ] Run `deploy/aws` stack + ECR push on AWS account
- [ ] equity-os ECS service live
- [ ] moonstocks-app API URL cutover
- [ ] Deprecate moonstocks-api in AWS
