"""
LangGraph-based stock analyst agent.

The agent follows a proper research loop:
  1. Calls EODHD tools (fundamentals, price history, news)
  2. After 3+ individual tool calls, injects a mandatory reflection step
  3. Decides autonomously whether to do follow-up research or write the report
  4. Produces a structured JSON report

Streaming protocol (same as local_analyzer.py):
  {"type": "status",     "text": "..."}
  {"type": "tool",       "tool": "...", "symbol": "..."}
  {"type": "token",      "text": "..."}       ← each text chunk from the final write
  {"type": "tool_sites", "sites": [...]}      ← domains from news tool
  {"type": "done",       "report": {...}}
  {"type": "error",      "text": "..."}
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Generator, Sequence, TypedDict, Annotated

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-use skill/prompt helpers from local_analyzer
# ---------------------------------------------------------------------------
from local_analyzer import (
    build_system_prompt,
    _make_tool_executor,
    _extract_news_sites,
    parse_json_report,
    EODHD_BASE,
    _eodhd_key,
    _trim_financials,
)

# ---------------------------------------------------------------------------
# LangGraph imports
# ---------------------------------------------------------------------------
from langchain_core.messages import (
    BaseMessage, SystemMessage, HumanMessage, AIMessage, ToolMessage
)
from langchain_core.tools import tool as lc_tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
import operator

# ---------------------------------------------------------------------------
# Agent state
# ---------------------------------------------------------------------------

class AnalystState(TypedDict):
    messages:          Annotated[Sequence[BaseMessage], operator.add]
    tool_calls_total:  int
    reflection_done:   bool
    ticker:            str

# ---------------------------------------------------------------------------
# EODHD LangChain tools (closures so default_symbol is baked in)
# ---------------------------------------------------------------------------

REFLECTION_PROMPT = (
    "You have completed your initial data gathering. "
    "Before writing the report, take a moment to reflect:\n"
    "1. What do you know with high confidence?\n"
    "2. Is there anything unusual, ambiguous, or incomplete — "
    "a margin move, debt level, earnings miss, guidance cut, acquisition, or valuation outlier "
    "— that you should verify or dig into further?\n"
    "3. If YES: call the relevant tool now to investigate. "
    "If NO: proceed directly to outputting the JSON report."
)


def _make_lc_tools(default_symbol: str):
    """Return LangChain tool objects for the given ticker."""
    raw_executor = _make_tool_executor(default_symbol)

    @lc_tool
    def eodhd_fundamentals(symbol: str = default_symbol) -> str:
        """Fetch full company fundamentals from EODHD: income statement, balance sheet,
        cash flow (last 4 years / 6 quarters), analyst ratings, earnings history."""
        return raw_executor("eodhd_fundamentals", {"symbol": symbol or default_symbol})

    @lc_tool
    def eodhd_price_history(symbol: str = default_symbol) -> str:
        """Fetch daily OHLCV price history for the past 365 days."""
        return raw_executor("eodhd_price_history", {"symbol": symbol or default_symbol})

    @lc_tool
    def eodhd_news(symbol: str = default_symbol) -> str:
        """Fetch the 15 most recent news articles for the company."""
        return raw_executor("eodhd_news", {"symbol": symbol or default_symbol})

    return [eodhd_fundamentals, eodhd_price_history, eodhd_news]


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def _build_graph(tools: list, llm: ChatOpenAI):
    """Compile and return the LangGraph state machine."""
    llm_with_tools = llm.bind_tools(tools)
    tool_node = ToolNode(tools)

    # --- nodes ---------------------------------------------------------------

    def analyst_node(state: AnalystState) -> dict:
        """Call the LLM; it may produce tool calls or write the final report."""
        # Keep context lean: trim tool message content after 3+ calls to avoid TPM limits
        msgs = list(state["messages"])
        if state.get("tool_calls_total", 0) >= 3:
            trimmed = []
            for m in msgs:
                if isinstance(m, ToolMessage) and len(m.content or "") > 2000:
                    trimmed.append(ToolMessage(
                        content=m.content[:2000] + "\n[trimmed for context length]",
                        tool_call_id=m.tool_call_id,
                        name=m.name,
                    ))
                else:
                    trimmed.append(m)
            msgs = trimmed
        response = llm_with_tools.invoke(msgs)
        return {"messages": [response]}

    def execute_tools_node(state: AnalystState) -> dict:
        """Run all pending tool calls; update the total tool call counter."""
        last_msg = state["messages"][-1]
        n = len(last_msg.tool_calls) if getattr(last_msg, "tool_calls", None) else 0
        result = tool_node.invoke({"messages": state["messages"]})
        return {
            "messages": result["messages"],
            "tool_calls_total": state.get("tool_calls_total", 0) + n,
        }

    def reflection_node(state: AnalystState) -> dict:
        """Inject a mandatory reflection message once after initial research."""
        return {
            "messages": [HumanMessage(content=REFLECTION_PROMPT)],
            "reflection_done": True,
        }

    # --- routing -------------------------------------------------------------

    def route_after_analyst(state: AnalystState) -> str:
        """Decide what to do after the analyst node runs."""
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "tools"
        return END  # no tool calls → model wrote the report

    def route_after_tools(state: AnalystState) -> str:
        """After executing tools, maybe reflect, then loop back."""
        total = state.get("tool_calls_total", 0)
        reflected = state.get("reflection_done", False)
        if total >= 3 and not reflected:
            return "reflect"
        return "analyst"

    # --- assemble graph ------------------------------------------------------
    g = StateGraph(AnalystState)
    g.add_node("analyst",  analyst_node)
    g.add_node("tools",    execute_tools_node)
    g.add_node("reflect",  reflection_node)

    g.add_edge(START, "analyst")
    g.add_conditional_edges("analyst", route_after_analyst, {"tools": "tools", END: END})
    g.add_conditional_edges("tools",   route_after_tools,   {"reflect": "reflect", "analyst": "analyst"})
    g.add_edge("reflect", "analyst")

    return g.compile()


# ---------------------------------------------------------------------------
# Public streaming entry-point (API-key path)
# ---------------------------------------------------------------------------

def analyze_stream_langgraph(
    ticker_exchange: str,
    openai_api_key: str,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> Generator[dict, None, None]:
    """
    Drop-in replacement for local_analyzer.analyze_stream using LangGraph.
    Yields the same event dicts as the original.
    """
    model = model or os.getenv("OPENAI_MODEL") or "gpt-4.1"
    effort_label = f" (reasoning: {reasoning_effort})" if reasoning_effort else ""
    yield {"type": "status", "text": f"Starting LangGraph analysis{effort_label}…\n\n"}

    # Build LLM
    llm_kwargs: dict = {"model": model, "api_key": openai_api_key, "streaming": False}
    if reasoning_effort:
        llm_kwargs["reasoning_effort"] = reasoning_effort
    else:
        llm_kwargs["temperature"] = 0.2
    try:
        llm = ChatOpenAI(**llm_kwargs)
    except Exception as exc:
        yield {"type": "error", "text": f"OpenAI init failed: {exc}"}
        return

    tools = _make_lc_tools(ticker_exchange)
    app   = _build_graph(tools, llm)

    system_prompt = build_system_prompt()
    user_msg = (
        f"Analyze {ticker_exchange}.\n"
        f"analysis_date: {date.today().isoformat()}\n"
        f"time_horizon: long_term_1y_plus\n"
        "Follow the research workflow: call eodhd_fundamentals, eodhd_price_history, "
        "eodhd_news, then reflect and do at least one follow-up before writing the JSON report."
    )

    initial_state: AnalystState = {
        "messages":         [SystemMessage(content=system_prompt), HumanMessage(content=user_msg)],
        "tool_calls_total": 0,
        "reflection_done":  False,
        "ticker":           ticker_exchange,
    }

    final_ai_text = ""

    try:
        for step, state_update in enumerate(app.stream(initial_state, stream_mode="updates")):
            node_name = next(iter(state_update))
            node_out  = state_update[node_name]
            msgs       = node_out.get("messages", [])

            if node_name == "tools":
                # Emit tool events for each ToolMessage result
                for msg in msgs:
                    if not isinstance(msg, ToolMessage):
                        continue
                    tool_name = msg.name or ""
                    evt: dict = {"type": "tool", "tool": tool_name, "symbol": ticker_exchange}
                    if tool_name == "eodhd_news":
                        sites = _extract_news_sites(msg.content or "[]")
                        if sites:
                            evt["sites"] = sites
                    yield evt

            elif node_name == "reflect":
                yield {"type": "status", "text": "Reflecting on research…"}

            elif node_name == "analyst":
                # The final analyst response (after all tools + reflection) is the JSON report
                for msg in msgs:
                    if isinstance(msg, AIMessage) and msg.content:
                        text = msg.content if isinstance(msg.content, str) else str(msg.content)
                        # Only stream tokens if it looks like the final JSON output
                        if not getattr(msg, "tool_calls", None):
                            # Emit in chunks for live display
                            chunk_size = 64
                            for i in range(0, len(text), chunk_size):
                                chunk = text[i:i + chunk_size]
                                final_ai_text += chunk
                                yield {"type": "token", "text": chunk}
                        elif step == 0:
                            yield {"type": "status", "text": "Researching…"}

    except Exception as exc:
        yield {"type": "error", "text": f"LangGraph agent failed: {exc}"}
        return

    if not final_ai_text:
        yield {"type": "error", "text": "Agent produced no output."}
        return

    yield {"type": "status", "text": "\n\nParsing and saving report…"}
    try:
        report = parse_json_report(final_ai_text)
        report.setdefault("ticker",   ticker_exchange.split(".")[0])
        report.setdefault("exchange", (ticker_exchange.split(".", 1) + ["US"])[1])
        report["_model"] = f"{model} [langgraph]"
        yield {"type": "done", "report": report, "raw": final_ai_text}
    except Exception as exc:
        yield {"type": "error", "text": f"JSON parse failed: {exc}\n\nRaw:\n{final_ai_text[:800]}"}
