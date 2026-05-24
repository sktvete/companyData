"""Dispatch Moonstocks analysis to Claude or OpenAI."""
from __future__ import annotations

import asyncio
import logging

from analyzer_claude import run_analysis_claude
from analyzer_openai import run_analysis_openai
from analyzer_provider import resolve_llm_provider

logger = logging.getLogger(__name__)


async def run_analysis(ticker_exchange: str) -> None:
    provider = resolve_llm_provider()
    logger.info("Running analysis for %s via %s", ticker_exchange, provider)
    if provider == "openai":
        # Sync OpenAI client blocks the event loop — run off-thread so /health and 202 stay fast.
        await asyncio.to_thread(run_analysis_openai, ticker_exchange)
    else:
        await run_analysis_claude(ticker_exchange)
