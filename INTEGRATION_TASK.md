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

Installed via `scripts/install-docker-desktop.ps1`. **Start Docker Desktop** from the Start menu, wait for “Engine running”, then:

```bash
docker compose -f docker-compose.moonstocks.yml up --build
```

## AWS next steps (needs AWS CLI on a machine with credentials)

See `deploy/aws/README.md`. Summary:

1. `aws cloudformation deploy` — `deploy/aws/rds-moonstocks.yaml`
2. `scripts/deploy_moonstocks_ecr.ps1` — build/push images
3. Register ECS task defs; create/update `equity-os-prod` service
4. Cut over moonstocks-app API URL; scale down C# `moonstocks-api`
