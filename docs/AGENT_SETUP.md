# Agent setup — Moonstocks × Equity OS (compressed)

## What this repo is

- **equity-os** (`companyData`): Flask app :3000 — screener, company pages, **Moonstocks API** (replaces C# `moonstocks-api`).
- **moonstocks-ai-analyzer/** (in-repo): FastAPI :8000 — LLM analysis → `POST` equity-os `/api/analysis/{TICKER.EX}`.
- **moonstocks-app** (external): point API URL at equity-os when deployed.

Storage: **Postgres** (`MOONSTOCKS_DATABASE_URL`) in Docker/prod; **SQLite** (`MOONSTOCKS_DB_PATH`) for local quick dev.

---

## One-time machine setup

```powershell
# Python 3.12+ venv at repo root
python -m venv .venv
.\.venv\Scripts\pip install -r web\requirements.txt
.\.venv\Scripts\pip install openai   # analyzer OpenAI path
.\.venv\Scripts\pip install -r moonstocks-ai-analyzer\requirements.txt
```

**`.env` at repo root** (copy from `.env.moonstocks.example`):

| Var | Required |
|-----|----------|
| `EODHD_API_KEY` | yes |
| `OPENAI_API_KEY` | yes (analyzer default) |
| `ANALYZER_LLM_PROVIDER=openai` | recommended |
| `OPENAI_MODEL=gpt-4o` | optional |
| `MOONSTOCKS_ANALYZER_URL=http://127.0.0.1:8000` | native dev |
| `MOONSTOCKS_DB_PATH=outputs/moonstocks_analyses.db` | native SQLite |
| `ANALYZER_API_KEY` | optional shared secret |

**Windows:** `tzdata` in `web/requirements.txt` (ZoneInfo). No Docker required for dev.

---

## Run locally (preferred — no Docker)

```powershell
# T1 — equity-os
cd companyData
.\.venv\Scripts\python run_server.py
# → http://localhost:3000

# T2 — analyzer
cd moonstocks-ai-analyzer
$env:ANALYSIS_API_BASE_URL="http://127.0.0.1:3000"
$env:ANALYZER_LLM_PROVIDER="openai"
..\companyData\.venv\Scripts\uvicorn main:app --port 8000
# → http://localhost:8000/health  → llm_provider: openai
```

Smoke: http://localhost:3000/company/DECK → Moonstocks → **Trigger** (~3 min real OpenAI).

---

## Docker (optional, prod-like Postgres)

**Prereqs:** WSL2 + Docker Desktop (engine must show **Running**). First engine start can take several minutes on Win11 Home.

```powershell
# Admin once if WSL missing:
.\scripts\enable-docker-wsl-elevated.ps1   # reboot

# Install Docker Desktop (if missing):
.\scripts\install-docker-desktop.ps1
```

**`.env` for compose** — use Postgres URL, not SQLite path:

```
MOONSTOCKS_DATABASE_URL=postgresql://moonstocks:moonstocks@postgres:5432/moonstocks
MOONSTOCKS_ANALYZER_URL=http://analyzer:8000
```

```powershell
docker compose -f docker-compose.moonstocks.yml up -d --build
python scripts\test_docker_stack.py
```

Services: `postgres:5432`, `equity-os:3000`, `analyzer:8000`.  
**Note:** `MOONSTOCKS_DB_PATH` overrides Postgres URL when set (for local/e2e SQLite).

---

## Verify (agent must run)

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -p "test_*.py" -q
.\.venv\Scripts\python scripts\e2e_moonstocks_local.py --start-server
```

E2E uses mock analyzer :8765; no OpenAI spend.

---

## Key code paths

| Piece | Path |
|-------|------|
| Moonstocks store | `web/moonstocks_store.py` |
| API routes | `web/app_enhanced.py` (`/api/moonstocks/*`, `/api/analysis/*`, `/health`) |
| Analyzer router | `moonstocks-ai-analyzer/main.py` |
| OpenAI path | `analyzer_openai.py` + `eodhd_fetch.py` |
| Claude path | `analyzer_claude.py` (needs `ANTHROPIC_API_KEY`) |
| Provider pick | `analyzer_provider.py` — OpenAI if only `OPENAI_API_KEY` set |

---

## AWS (not automated from dev laptop)

1. `deploy/aws/rds-moonstocks.yaml` → RDS + `moonstocks/rds/database_url` secret  
2. `scripts/deploy_moonstocks_ecr.ps1` → push `equity-os-prod`, `moonstocks-ai-analyzer-prod` images  
3. `deploy/aws/equity-os-task-definition.json` + `moonstocks-ai-analyzer/.aws/task-definition.json`  
4. ECS services; cut over moonstocks-app; retire C# `moonstocks-api`  

Details: `deploy/aws/README.md`, `docs/moonstocks-integration.md`.

---

## Installed on original dev PC (reference)

| Item | How |
|------|-----|
| Python deps | `web/requirements.txt` (+ `psycopg[binary]`, `tzdata` win) |
| Analyzer deps | `moonstocks-ai-analyzer/requirements.txt` (+ `openai`) |
| WSL2 | `scripts/enable-docker-wsl-elevated.ps1` (admin + reboot) |
| Docker Desktop 4.73 | `scripts/install-docker-desktop.ps1` (winget) |
| Git | `moonstocks-ai-analyzer` converted from broken submodule → normal folder in repo |

---

## Common failures

| Symptom | Fix |
|---------|-----|
| `ZoneInfo` / `tzdata` | `pip install tzdata` |
| Tests import fail `postgres` host | Unset `MOONSTOCKS_DATABASE_URL` or set `MOONSTOCKS_DB_PATH` for SQLite |
| Docker “virtualization” | Install WSL2, not BIOS (usually already on) |
| Docker engine slow / 500 | Wait for green engine; restart Docker Desktop |
| Analyzer container exit | `Path` vs `PathParam` in `main.py` (fixed in repo) |
| equity-os unhealthy in compose | `start_period: 300s` (slow `load_data`) |
