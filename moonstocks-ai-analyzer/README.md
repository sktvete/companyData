# moonstocks-ai-analyzer

Async stock analysis worker for [Equity OS](../docs/moonstocks-integration.md). Triggered via `POST /{TICKER.EX}`; writes JSON to equity-os `POST /api/analysis/{TICKER.EX}`.

## Providers

| Provider | Env | Notes |
|----------|-----|--------|
| **OpenAI** | `OPENAI_API_KEY`, `ANALYZER_LLM_PROVIDER=openai` | EODHD REST + stock-analysis skill (default if only OpenAI key is set) |
| **Anthropic** | `ANTHROPIC_API_KEY` | Claude Agent SDK + EODHD MCP |

Loads `.env` here and parent `companyData/.env`.

## Run locally

```bash
pip install -r requirements.txt
set ANALYSIS_API_BASE_URL=http://127.0.0.1:3000
set ANALYZER_LLM_PROVIDER=openai
uvicorn main:app --port 8000
```

Health: http://127.0.0.1:8000/health
