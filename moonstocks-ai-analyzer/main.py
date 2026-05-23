import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Path

from analyzer import run_analysis
from analyzer_provider import resolve_llm_provider

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")
load_dotenv(_ROOT.parent / ".env")

app = FastAPI()


@app.get("/health", status_code=200)
async def health():
    return {"status": "ok", "llm_provider": resolve_llm_provider()}


@app.post("/{ticker_exchange}", status_code=202)
async def create_analysis(
    background_tasks: BackgroundTasks,
    ticker_exchange: str = Path(..., pattern=r"^[A-Za-z0-9-]+\.[A-Za-z]+$"),
    x_api_key: str | None = Header(default=None),
):
    expected = os.environ.get("ANALYZER_API_KEY", "")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")
    background_tasks.add_task(run_analysis, ticker_exchange)
    return {"status": "accepted", "ticker_exchange": ticker_exchange}
