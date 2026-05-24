# Docker — quick fix

**Hung / `500` / `docker ps` fails**
```powershell
.\scripts\repair-docker-engine.ps1
```

**Native Flask + Postgres in Docker** (two terminals)
```powershell
docker compose -f docker-compose.moonstocks.yml up -d postgres
# .env: MOONSTOCKS_DATABASE_URL=@127.0.0.1:5432, MOONSTOCKS_ANALYZER_URL=http://127.0.0.1:8000
.\scripts\start-local-analyzer.ps1   # terminal 1
python run_server.py                 # terminal 2
```
`analyzer` / `postgres` hostnames only work **inside** full `docker compose up`, not for native `run_server.py`.

**Full stack**
```powershell
docker compose -f docker-compose.moonstocks.yml up -d --build
```

**Stay fast:** leave Docker in the system tray; cold boot is slow, warm is ~20s.

**Still broken:** Docker Desktop → Troubleshoot → Restart → then Clean/Purge data.
