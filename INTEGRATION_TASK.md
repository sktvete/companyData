# Moonstocks integration

**Full plan:** [docs/moonstocks-integration.md](docs/moonstocks-integration.md)

## Quick start (local, OpenAI — no Docker)

Uses root `.env` (`OPENAI_API_KEY`, `EODHD_API_KEY`).

```bash
# Terminal 1
set MOONSTOCKS_ANALYZER_URL=http://127.0.0.1:8000
python run_server.py

# Terminal 2
cd moonstocks-ai-analyzer
pip install -r requirements.txt
set ANALYSIS_API_BASE_URL=http://127.0.0.1:3000
set ANALYZER_LLM_PROVIDER=openai
uvicorn main:app --port 8000
```

http://localhost:3000/company/DECK → **Trigger Analysis**  
http://localhost:8000/health → `"llm_provider": "openai"`

## Quick start (Docker)

```bash
cp .env.moonstocks.example .env
# Set EODHD_API_KEY, OPENAI_API_KEY, optional ANALYZER_API_KEY (same value in both services)

docker compose -f docker-compose.moonstocks.yml up --build
```

## Tests (run all)

```bash
.\.venv\Scripts\pip install -r web\requirements.txt
.\.venv\Scripts\pip install openai
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe scripts\e2e_moonstocks_local.py --start-server
```

## Docker Desktop

Docker is installed but needs **WSL2** (not just BIOS virtualization).

**If you see “Virtualization support not detected”:** firmware is usually fine; WSL/VM Platform is missing.

1. Open **PowerShell as Administrator**
2. Run: `Set-ExecutionPolicy Bypass -Scope Process -Force; .\scripts\enable-docker-wsl.ps1`
3. **Reboot**
4. Start **Docker Desktop**, wait for “Engine running”
5. `docker compose -f docker-compose.moonstocks.yml up --build`

**Without Docker** (same stack, native Windows):

```bash
# Terminal 1 — equity-os (SQLite, no Postgres required)
python run_server.py

# Terminal 2 — analyzer
cd moonstocks-ai-analyzer
pip install -r requirements.txt
set ANALYSIS_API_BASE_URL=http://127.0.0.1:3000
set ANALYZER_LLM_PROVIDER=openai
uvicorn main:app --port 8000
```

Optional Postgres locally: install [PostgreSQL](https://www.postgresql.org/download/windows/) and set  
`MOONSTOCKS_DATABASE_URL=postgresql://user:pass@localhost:5432/moonstocks`

## AWS next steps (needs AWS CLI on a machine with credentials)

See `deploy/aws/README.md`. Summary:

1. `aws cloudformation deploy` — `deploy/aws/rds-moonstocks.yaml`
2. `scripts/deploy_moonstocks_ecr.ps1` — build/push images
3. Register ECS task defs; create/update `equity-os-prod` service
4. Cut over moonstocks-app API URL; scale down C# `moonstocks-api`
