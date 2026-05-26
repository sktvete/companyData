"""
Tracker Research Agent — LangGraph investor research loop.

Discovers affiliations, maps them to the right SEC filing types, and fills
the tracker live via add_transaction / remove_transaction.

Streaming protocol:
  {"type": "status",       "text": "..."}
  {"type": "think",        "title": "...", "text": "..."}
  {"type": "tool",         "tool": "...", "detail": "...", "symbol": "", "url": ""}
  {"type": "tool_result",  "tool": "...", "summary": "...", "urls": [...]}
  {"type": "txn_added",    "txn": {...}}
  {"type": "txn_removed",  "txn_id": "..."}
  {"type": "token",        "text": "..."}
  {"type": "done",         "total_found": N}
  {"type": "error",        "text": "..."}
"""
from __future__ import annotations

import json
import logging
import operator
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Annotated, Callable, Generator, TypedDict
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_EDGAR_HEADERS = {
    "User-Agent": os.getenv("SEC_EDGAR_USER_AGENT", "moonstocks research@moonstocks.ai"),
    "Accept-Encoding": "gzip, deflate",
}
_EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"
_EDGAR_BASE = "https://www.sec.gov"
_EDGAR_BROWSE = "https://www.sec.gov/cgi-bin/browse-edgar"


def _abs_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urljoin(_EDGAR_BASE, href)


def _edgar_fulltext_search(query: str, form_types: str = "4", max_hits: int = 15) -> list[dict]:
    try:
        resp = httpx.get(
            _EDGAR_SEARCH,
            params={
                "q": query,
                "forms": form_types,
                "dateRange": "custom",
                "startdt": "2015-01-01",
                "enddt": datetime.now().strftime("%Y-%m-%d"),
                "from": "0",
            },
            headers=_EDGAR_HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        out = []
        for h in hits[:max_hits]:
            s = h.get("_source", {})
            accession = s.get("adsh") or h.get("_id", "")
            cik = str(s.get("cik") or "").lstrip("0")
            index_url = ""
            if cik and accession:
                acc_no_dash = accession.replace("-", "")
                index_url = f"{_EDGAR_BASE}/Archives/edgar/data/{cik}/{acc_no_dash}/{accession}-index.htm"
            out.append({
                "form": s.get("form_type", ""),
                "entity": s.get("entity_name", ""),
                "filed": s.get("file_date", ""),
                "period": s.get("period_of_report", ""),
                "cik": cik,
                "accession": accession,
                "index_url": index_url,
            })
        return out
    except Exception as e:
        logger.warning("EDGAR fulltext search error: %s", e)
        return []


def _edgar_resolve_entities(name: str, form_type: str = "") -> list[dict]:
    """Resolve EDGAR registrants matching a name."""
    try:
        params = {
            "action": "getcompany",
            "company": name,
            "owner": "include",
            "count": "40",
        }
        if form_type:
            params["type"] = form_type
        resp = httpx.get(_EDGAR_BROWSE, params=params, headers=_EDGAR_HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Multiple company matches (search results page)
        company_table = soup.find("table", class_="tableFile2")
        if company_table:
            rows = company_table.find_all("tr")
            if rows and "CIK" in rows[0].get_text():
                entities = []
                for row in rows[1:]:
                    cells = row.find_all("td")
                    if len(cells) < 2:
                        continue
                    link = cells[0].find("a")
                    if not link:
                        continue
                    href = link.get("href", "")
                    cik_match = re.search(r"CIK=(\d+)", href)
                    cik = cik_match.group(1) if cik_match else link.text.strip()
                    entities.append({
                        "cik": cik.lstrip("0") or cik,
                        "name": cells[1].get_text(" ", strip=True),
                        "filings_url": _abs_url(href),
                    })
                if entities:
                    return entities[:10]

        # Single company page — extract CIK from header
        cik_el = soup.find("span", class_="companyName")
        cik = ""
        entity_name = name
        if cik_el:
            entity_name = cik_el.get_text(" ", strip=True)
            m = re.search(r"CIK=(\d+)", str(cik_el))
            if m:
                cik = m.group(1).lstrip("0") or m.group(1)
        if not cik:
            m = re.search(r"CIK[:\s#]*(\d+)", soup.get_text(" ", strip=True), re.I)
            cik = m.group(1).lstrip("0") if m else ""
        if cik:
            return [{"cik": cik, "name": entity_name, "filings_url": resp.url}]
        return []
    except Exception as e:
        logger.warning("EDGAR entity resolve error: %s", e)
        return []


def _edgar_list_filings(cik: str, form_type: str = "13F-HR", limit: int = 5) -> list[dict]:
    """Return recent filing index URLs for a CIK."""
    try:
        resp = httpx.get(
            _EDGAR_BROWSE,
            params={
                "action": "getcompany",
                "CIK": cik,
                "type": form_type,
                "owner": "include",
                "count": str(max(limit, 5)),
            },
            headers=_EDGAR_HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.find("table", class_="tableFile2")
        if not table:
            return []
        filings = []
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            doc_link = cells[1].find("a")
            if not doc_link:
                continue
            href = doc_link.get("href", "")
            filings.append({
                "form": cells[0].get_text(" ", strip=True),
                "description": cells[1].get_text(" ", strip=True),
                "filed": cells[3].get_text(" ", strip=True),
                "index_url": _abs_url(href),
            })
            if len(filings) >= limit:
                break
        return filings
    except Exception as e:
        logger.warning("EDGAR list filings error: %s", e)
        return []


def _edgar_entity_filings(entity_name: str, form_type: str = "13F-HR", limit: int = 3) -> dict:
    """Resolve entity → CIK → recent filings with index URLs."""
    entities = _edgar_resolve_entities(entity_name, form_type=form_type)
    if not entities:
        return {"found": 0, "message": f"No EDGAR registrant matched '{entity_name}'"}
    primary = entities[0]
    filings = _edgar_list_filings(primary["cik"], form_type=form_type, limit=limit)
    return {
        "found": len(filings),
        "entity": primary,
        "alternate_matches": entities[1:5],
        "filings": filings,
    }


def _xml_ns(root: ET.Element) -> dict:
    if "}" in root.tag:
        return {"ns": root.tag.split("}")[0].lstrip("{")}
    return {}


def _xml_text(el: ET.Element | None, *tags: str, ns: dict | None = None) -> str:
    if el is None:
        return ""
    for tag in tags:
        child = el.find(tag, ns or {})
        if child is None and ns:
            child = el.find(f"ns:{tag}", ns)
        if child is None:
            child = el.find(f".//{tag}")
        if child is not None and child.text:
            return child.text.strip()
    return ""


def _edgar_filing_xml(filing_index_url: str) -> list[dict]:
    transactions = []
    try:
        idx_resp = httpx.get(filing_index_url, headers=_EDGAR_HEADERS, timeout=20, follow_redirects=True)
        idx_resp.raise_for_status()
        soup = BeautifulSoup(idx_resp.text, "lxml")
        xml_url = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.endswith(".xml") and "xsd" not in href.lower():
                xml_url = _abs_url(href)
                break
        if not xml_url:
            return []

        xml_resp = httpx.get(xml_url, headers=_EDGAR_HEADERS, timeout=20)
        xml_resp.raise_for_status()
        root = ET.fromstring(xml_resp.text)
        owner = _xml_text(root, ".//rptOwnerName") or _xml_text(root.find(".//rptOwnerName"))
        ticker = (_xml_text(root, ".//issuerTradingSymbol") or "").upper()

        for txn in root.findall(".//nonDerivativeTransaction"):
            code = _xml_text(txn, ".//transactionCoding/transactionCode")
            date = _xml_text(txn, ".//transactionDate/value")[:10]
            shares_raw = _xml_text(txn, ".//transactionAmounts/transactionShares/value")
            price_raw = _xml_text(txn, ".//transactionAmounts/transactionPricePerShare/value")
            disp = _xml_text(txn, ".//transactionAmounts/transactionAcquiredDisposedCode/value")
            if not ticker or not date:
                continue
            if code in ("P", "A") or disp == "A":
                action = "buy"
            elif code in ("S", "D") or disp == "D":
                action = "sell"
            else:
                continue
            transactions.append({
                "symbol": ticker,
                "action": action,
                "date": date,
                "shares": float(shares_raw) if shares_raw else None,
                "price": float(price_raw) if price_raw else None,
                "notes": f"SEC Form 4 — {owner or 'insider filing'}",
            })
    except Exception as e:
        logger.warning("Form 4 parse error: %s", e)
    return transactions


def _pick_13f_xml_url(soup: BeautifulSoup) -> str:
    candidates: list[tuple[int, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.lower().endswith(".xml"):
            continue
        lower = href.lower()
        if "xsd" in lower or "primary_doc" in lower or "/xsl" in lower:
            continue
        score = 0
        if "infotable" in lower:
            score += 5
        if "13f" in lower:
            score += 4
        if "form13f" in lower.replace("-", ""):
            score += 3
        if score == 0:
            continue
        candidates.append((score, _abs_url(href)))
    if not candidates:
        return ""
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]


def _edgar_13f_holdings(filing_index_url: str) -> list[dict]:
    holdings = []
    try:
        idx_resp = httpx.get(filing_index_url, headers=_EDGAR_HEADERS, timeout=20, follow_redirects=True)
        idx_resp.raise_for_status()
        soup = BeautifulSoup(idx_resp.text, "lxml")
        xml_url = _pick_13f_xml_url(soup)
        if not xml_url:
            return []

        xml_resp = httpx.get(xml_url, headers=_EDGAR_HEADERS, timeout=20)
        xml_resp.raise_for_status()
        root = ET.fromstring(xml_resp.text)
        ns_uri = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
        ns = {"ns": ns_uri} if ns_uri else {}

        for info in root.findall(".//ns:infoTable", ns) or root.findall(".//infoTable"):
            issuer = _xml_text(info, "nameOfIssuer", ns=ns)
            cusip = _xml_text(info, "cusip", ns=ns)
            value = _xml_text(info, "value", ns=ns)
            shares = _xml_text(info, "sshPrnamt", ns=ns)
            if not shares:
                amt = info.find("ns:shrsOrPrnAmt", ns) or info.find("shrsOrPrnAmt")
                if amt is not None:
                    shares = _xml_text(amt, "sshPrnamt", ns=ns)
            put_call = _xml_text(info, "putCall", ns=ns) or "Long"
            if not issuer:
                continue
            holdings.append({
                "issuer": issuer,
                "cusip": cusip,
                "value_thousands_usd": value,
                "shares": shares,
                "put_call": put_call,
            })
        return holdings[:80]
    except Exception as e:
        logger.warning("13F parse error: %s", e)
        return []


def _web_search(query: str, max_results: int = 8) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "body": r.get("body", ""),
                })
        return results
    except Exception as e:
        logger.warning("Web search error: %s", e)
        return []


def _scrape_url(url: str, max_chars: int = 6000) -> str:
    try:
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ", strip=True).split())
        return text[:max_chars]
    except Exception as e:
        return f"[scrape error: {e}]"


def _guess_ticker(issuer_or_name: str) -> str:
    """Best-effort ticker resolution from issuer name."""
    upper = issuer_or_name.upper()
    hints = [
        ("BLOOM ENERGY", "BE"), ("NVIDIA", "NVDA"), ("MICRON", "MU"), ("TAIWAN SEMICONDUCTOR", "TSM"),
        ("ADVANCED MICRO DEVICES", "AMD"), ("BROADCOM", "AVGO"), ("ORACLE", "ORCL"), ("INTEL", "INTC"),
        ("COREWEAVE", "CRWV"), ("SANDISK", "SNDK"), ("ASML", "ASML"), ("CORNING", "GLW"),
        ("VANECK", "SMH"), ("SEMICONDUCTOR ETF", "SMH"), ("BLOOM ENERGY CORP", "BE"),
        ("CORE SCIENTIFIC", "CORZ"), ("RIOT PLATFORMS", "RIOT"), ("CLEANSPARK", "CLSK"),
        ("APPLIED DIGITAL", "APLD"), ("IREN", "IREN"), ("BITDEER", "BTDR"), ("BITFARMS", "BITF"),
        ("HIVE DIGITAL", "HIVE"), ("INFOSYS", "INFY"), ("LUMENTUM", "LITE"), ("COHERENT", "COHR"),
    ]
    for needle, ticker in hints:
        if needle in upper:
            return ticker
    cleaned = re.sub(r"\s+(INC|CORP|CORPORATION|LTD|LLC|LP|PLC|HOLDINGS|CO\.?).*$", "", upper, flags=re.I).strip()
    if re.fullmatch(r"[A-Z]{1,5}", cleaned):
        return cleaned
    try:
        hits = _web_search(f"{issuer_or_name} stock ticker symbol", max_results=3)
        for hit in hits:
            blob = f"{hit.get('title','')} {hit.get('body','')}"
            m = re.search(r"\b([A-Z]{1,5})\b(?:\s*\(?(?:NYSE|NASDAQ|AMEX)\)?|\s+stock)", blob)
            if m:
                return m.group(1)
    except Exception:
        pass
    return ""


def _resolve_tickers_batch(issuers: list[str]) -> dict[str, str]:
    """Batch-resolve issuer names to tickers via LLM (falls back to heuristics)."""
    unique = list(dict.fromkeys(i for i in issuers if i))[:45]
    if not unique:
        return {}

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if api_key:
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage, SystemMessage
            llm = ChatOpenAI(model=os.getenv("OPENAI_MODEL_MINI") or "gpt-4o-mini", api_key=api_key, temperature=0)
            resp = llm.invoke([
                SystemMessage(content=(
                    "Map company/issuer names from SEC 13F filings to US stock ticker symbols. "
                    "Reply ONLY with JSON object: {\"ISSUER NAME\": \"TICKER\", ...}. "
                    "Use null for unknown. Prefer primary listing tickers."
                )),
                HumanMessage(content=json.dumps(unique)),
            ])
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                data = json.loads(match.group(0))
                return {k: (v.upper() if isinstance(v, str) else "") for k, v in data.items() if v}
        except Exception as e:
            logger.warning("Batch ticker LLM resolve failed: %s", e)

    return {issuer: _guess_ticker(issuer) for issuer in unique}


def _fetch_institutional_holdings(entity_name: str, quarters: int = 1) -> dict:
    """Resolve entity, parse recent 13F-HR filings, resolve tickers."""
    base = _edgar_entity_filings(entity_name, form_type="13F-HR", limit=max(1, min(quarters, 3)))
    if not base.get("filings"):
        return {"found": 0, "message": base.get("message") or f"No 13F filings for '{entity_name}'", "entity": base.get("entity")}

    entity = base.get("entity", {})
    all_positions: list[dict] = []

    for filing in base["filings"][:quarters]:
        holdings = _edgar_13f_holdings(filing.get("index_url", ""))
        filed = filing.get("filed", "")
        # 13F reports quarter-end holdings; filing date is ~45d later — use filed date as fallback
        as_of = filed[:10] if filed else datetime.now().strftime("%Y-%m-%d")
        for h in holdings:
            issuer = h.get("issuer", "")
            put_call = (h.get("put_call") or "Long").strip()
            pc = put_call.lower()
            if pc == "put":
                action = "sell"
                position_type = "put"
            elif pc == "call":
                action = "buy"
                position_type = "call"
            else:
                action = "buy"
                position_type = "long"
            shares_raw = h.get("shares") or ""
            try:
                shares = float(shares_raw.replace(",", "")) if shares_raw else None
            except ValueError:
                shares = None
            val_raw = h.get("value_thousands_usd") or ""
            try:
                value_usd = float(str(val_raw).replace(",", "")) * 1000 if val_raw else None
            except ValueError:
                value_usd = None
            price = round(value_usd / shares, 2) if value_usd and shares and shares > 0 else None
            pos = {
                "issuer": issuer,
                "symbol": None,
                "action": action,
                "date": as_of,
                "shares": shares,
                "price": price,
                "put_call": put_call,
                "position_type": position_type,
                "value_usd": value_usd,
                "source": f"13F-HR filed {filed} — {entity.get('name', entity_name)}",
            }
            all_positions.append(pos)

    # Sort by value descending; resolve tickers for the largest positions only (avoid 40+ web lookups)
    def _val(p: dict) -> float:
        try:
            return float(str(p.get("value_usd") or 0))
        except ValueError:
            return 0.0

    all_positions.sort(key=lambda p: -_val(p))
    ticker_map = _resolve_tickers_batch([p["issuer"] for p in all_positions[:25]])
    for p in all_positions:
        if not p.get("symbol"):
            sym = ticker_map.get(p["issuer"]) or _guess_ticker(p["issuer"])
            p["symbol"] = sym or None

    resolved = [p for p in all_positions if p.get("symbol")]
    unresolved = [p for p in all_positions if not p.get("symbol")][:10]

    return {
        "found": len(all_positions),
        "entity": entity,
        "filings": base.get("filings", []),
        "positions": resolved[:40],
        "unresolved_issuers": [{"issuer": p["issuer"], "action": p["action"], "shares": p["shares"]} for p in unresolved],
        "instruction": "Call add_transaction() for each position in 'positions' that is not already tracked.",
    }


def _fetch_insider_trades(person_name: str, max_filings: int = 5) -> dict:
    """Search Form 4 filings by person name and parse transactions."""
    filings = _edgar_fulltext_search(f'"{person_name}"', form_types="4", max_hits=max_filings)
    if not filings:
        return {"found": 0, "filings_checked": 0, "transactions": []}

    txns: list[dict] = []
    seen: set[tuple] = set()
    for f in filings:
        url = f.get("index_url")
        if not url:
            continue
        for t in _edgar_filing_xml(url):
            key = (t["symbol"], t["date"], t["action"])
            if key in seen:
                continue
            seen.add(key)
            txns.append(t)

    return {
        "found": len(txns),
        "filings_checked": len(filings),
        "filings": filings,
        "transactions": txns,
        "instruction": "Call add_transaction() for each confirmed transaction not already tracked.",
    }


def _web_search_cached(query: str, max_results: int = 8, cache: dict | None = None) -> list[dict]:
    key = f"{query}|{max_results}"
    if cache is not None:
        if key in cache:
            return cache[key]
        results = _web_search(query, max_results=max_results)
        cache[key] = results
        return results
    return _web_search(query, max_results=max_results)


SYSTEM_PROMPT = """You are a senior financial intelligence analyst building a verified transaction ledger for a public figure or investor.

Your job is to discover every publicly documented equity position or trade attributable to the subject, with evidence. Work like an investigative researcher, not a keyword bot.

## How SEC disclosures actually work
- Form 4: insider trades by individuals at public companies (personal name usually appears).
- 13F-HR: quarterly institutional holdings — filed by the legal entity (fund, advisor, trust), NOT the manager's personal name.
- SC 13D / 13G: activist/passive stakes — may be person or entity.
- Congressional / STOCK Act disclosures: separate from EDGAR for members of Congress.
- News articles often summarize 13F holdings with tickers; primary sources are EDGAR index pages.

## Critical reasoning rules
1. **Identify the subject first.** Determine their role (insider, fund manager, politician, angel, etc.) and which legal entities file on their behalf. The filing entity is often different from the person's name.
2. **Match source to role.** Pick filing types that fit the role. If personal-name EDGAR searches return nothing, that is a signal — pivot to affiliated entities you discovered via web research.
3. **Resolve tickers.** 13F XML gives issuer names, not tickers. Use resolve_ticker() or corroborate via scraped articles before add_transaction().
4. **Write as you go.** Call add_transaction() the moment a position is confirmed with a source. Never batch until the end.
5. **Self-correct.** Use list_tracker_transactions() and remove_transaction() for duplicates or mistakes.
6. **Evidence in notes.** Every add must cite the source (form type, filing date, article title, etc.).
7. **Interpret position type:**
   - Long equity → action "buy", position_type "long"
   - Call options → action "buy", position_type "call"
   - Put options / bearish hedges → action "sell", position_type "put"
   - Full exits / disclosed sales of long stock → action "sell", position_type "exit"
   - Pass position_type on every add_transaction() so the UI can distinguish puts from real sales.
   - Use the filing period end date or filing date when exact trade date is unknown.

## Quality bar
- Prefer primary SEC filings over secondary articles when both exist.
- Do not invent tickers, dates, or share counts.
- If only quarterly 13F snapshot exists, use period-end date and note it is a quarter-end holding snapshot.
- When fetch_institutional_holdings or fetch_insider_trades return rows, add them immediately — do not keep searching without recording findings.
- Avoid repeating the same web search query; use scrape_url on promising URLs instead."""


PLAN_PROMPT = """Before using any tools, produce a concise research plan for the subject below.

Reply with ONLY valid JSON (no markdown):
{
  "subject_profile": "1-2 sentences: who they are and why they might appear in public market disclosures",
  "likely_roles": ["fund_manager", "corporate_insider", "politician", "activist_investor", "other"],
  "filing_entities_to_check": ["names of funds, firms, trusts, employers — empty array if unknown yet"],
  "form_types_to_prioritize": ["13F-HR", "4", "SC 13D", "SC 13G", "other"],
  "research_angles": ["3-6 concrete angles, phrased generally — no copy-paste search queries"],
  "risk_of_name_mismatch": "explain whether filings may appear under a different legal name than the subject"
}"""


REFLECTION_PROMPT = """Pause and assess your investigation so far.

Answer internally, then continue with tools:
1. Did you identify all legal entities that might file on the subject's behalf?
2. Are you searching the right SEC form types for this subject's role?
3. If personal-name EDGAR searches were empty, did you pivot to affiliated entities?
4. Have you parsed primary filings (not just snippets) for the most recent quarters?
5. Any duplicates to remove or tickers still unresolved?
6. What is the single highest-value next action?

Do not write a final essay — take that next action or finish if coverage is sufficient."""


def _txn_key(txn: dict) -> tuple[str, str, str]:
    return (
        (txn.get("symbol") or "").upper().strip(),
        (txn.get("action") or "buy").lower().strip(),
        (txn.get("date") or "")[:10],
    )


def _find_duplicate_txn(transactions: list[dict], candidate: dict) -> dict | None:
    key = _txn_key(candidate)
    if not key[0] or not key[2]:
        return None
    for t in transactions:
        if _txn_key(t) == key:
            return t
    return None


def _tool_call_detail(name: str, args: dict | None) -> str:
    args = args or {}
    if name == "search_web":
        return f'web search: "{args.get("query", "")}"'
    if name == "scrape_url":
        return args.get("url", "page")
    if name == "find_edgar_entity":
        return f'EDGAR entity "{args.get("entity_name", "")}" ({args.get("form_type", "13F-HR")})'
    if name == "search_edgar_fulltext":
        return f'EDGAR fulltext "{args.get("query", "")}" [{args.get("form_types", "")}]'
    if name == "fetch_insider_trades":
        return f'insider Form 4 for "{args.get("person_name", "")}"'
    if name == "fetch_institutional_holdings":
        return f'13F holdings for "{args.get("entity_name", "")}"'
    if name == "parse_form4_filing":
        return args.get("filing_index_url", "Form 4 filing")
    if name == "parse_13f_filing":
        return args.get("filing_index_url", "13F filing")
    if name == "resolve_ticker":
        return f'resolve ticker for "{args.get("issuer_or_company", "")}"'
    if name == "add_transaction":
        return f'{args.get("action", "buy")} {args.get("symbol", "")} on {args.get("date", "")}'
    if name == "remove_transaction":
        return f'remove txn {args.get("transaction_id", "")}'
    if name == "list_tracker_transactions":
        return "review saved transactions"
    parts = [f"{k}={v}" for k, v in args.items() if v not in (None, "", [])][:3]
    return f"{name}({', '.join(parts)})" if parts else name


def _format_plan_think(plan_text: str) -> str:
    try:
        match = re.search(r"\{[\s\S]*\}", plan_text)
        if match:
            plan = json.loads(match.group(0))
            lines: list[str] = []
            if plan.get("subject_profile"):
                lines.append(f"Profile: {plan['subject_profile']}")
            roles = plan.get("likely_roles") or []
            if roles:
                lines.append(f"Likely roles: {', '.join(roles)}")
            entities = [e for e in (plan.get("filing_entities_to_check") or []) if e]
            if entities:
                lines.append(f"Entities to check: {', '.join(entities[:6])}")
            forms = plan.get("form_types_to_prioritize") or []
            if forms:
                lines.append(f"Filing types: {', '.join(forms)}")
            angles = plan.get("research_angles") or []
            if angles:
                lines.append("Research angles:")
                for angle in angles[:6]:
                    lines.append(f"  • {angle}")
            if plan.get("risk_of_name_mismatch"):
                lines.append(f"Name mismatch risk: {plan['risk_of_name_mismatch']}")
            if lines:
                return "\n".join(lines)
    except Exception:
        pass
    cleaned = plan_text.strip()
    return cleaned[:1200] if len(cleaned) > 1200 else cleaned


def _summarize_tool_result(name: str, content: str) -> tuple[str, list[str]]:
    urls: list[str] = []
    text = content or ""

    if name == "scrape_url":
        if text.startswith("[scrape error"):
            return text[:160], urls
        return f"Read {len(text):,} chars from page", urls

    try:
        data = json.loads(text)
    except Exception:
        snippet = text[:140] + ("…" if len(text) > 140 else "")
        return snippet, re.findall(r"https?://[^\s\]'\"<>]+", text)[:6]

    if name == "search_web":
        results = data.get("results") or []
        urls = [r.get("url") for r in results if r.get("url")][:6]
        titles = [r.get("title", "")[:55] for r in results[:3] if r.get("title")]
        summary = f"{data.get('found', len(results))} web results"
        if titles:
            summary += " — " + "; ".join(titles)
        return summary, urls

    if name in ("find_edgar_entity", "search_edgar_fulltext"):
        filings = data.get("filings") or []
        urls = [f.get("index_url") for f in filings if f.get("index_url")][:6]
        entity = (data.get("entity") or {}).get("name") or data.get("message", "")
        count = data.get("found", len(filings))
        summary = f"{count} EDGAR filing(s)"
        if entity and isinstance(entity, str):
            summary += f" — {entity[:80]}"
        return summary, urls

    if name == "fetch_institutional_holdings":
        positions = data.get("positions") or []
        syms = sorted({p.get("symbol") for p in positions if p.get("symbol")})[:8]
        urls = [f.get("index_url") for f in (data.get("filings") or []) if f.get("index_url")][:4]
        summary = f"{data.get('found', len(positions))} 13F positions"
        if syms:
            summary += f" ({', '.join(syms)})"
        elif data.get("message"):
            summary = str(data["message"])[:160]
        return summary, urls

    if name == "fetch_insider_trades":
        txns = data.get("transactions") or []
        syms = sorted({t.get("symbol") for t in txns if t.get("symbol")})[:8]
        urls = [f.get("index_url") for f in (data.get("filings") or []) if f.get("index_url")][:4]
        summary = f"{data.get('found', len(txns))} insider trade(s)"
        if syms:
            summary += f" ({', '.join(syms)})"
        elif data.get("message"):
            summary = str(data["message"])[:160]
        return summary, urls

    if name == "parse_form4_filing":
        txns = data.get("transactions") or []
        syms = sorted({t.get("symbol") for t in txns if t.get("symbol")})[:8]
        return f"Parsed {data.get('found', len(txns))} Form 4 row(s)" + (f" ({', '.join(syms)})" if syms else ""), urls

    if name == "parse_13f_filing":
        holdings = data.get("holdings") or []
        issuers = [h.get("issuer", "")[:30] for h in holdings[:3] if h.get("issuer")]
        summary = f"Parsed {data.get('found', len(holdings))} 13F holding(s)"
        if issuers:
            summary += " — " + ", ".join(issuers)
        return summary, urls

    if name == "resolve_ticker":
        ticker = data.get("ticker")
        issuer = data.get("issuer", "")
        if ticker:
            return f"{issuer} → {ticker}", urls
        return data.get("message") or f"Could not resolve {issuer}", urls

    if name == "add_transaction":
        if data.get("ok"):
            txn = data.get("transaction") or {}
            return f"Saved {txn.get('action', 'buy')} {txn.get('symbol', '')} on {txn.get('date', '')}", urls
        return data.get("message") or "Duplicate or rejected", urls

    if name == "remove_transaction":
        if data.get("ok"):
            return f"Removed transaction {data.get('removed', '')}", urls
        return data.get("error") or "Remove failed", urls

    if name == "list_tracker_transactions":
        return f"{data.get('count', 0)} transactions already tracked", urls

    if data.get("message"):
        return str(data["message"])[:160], urls
    if "found" in data:
        return f"{data.get('found')} result(s)", urls
    return text[:140] + ("…" if len(text) > 140 else ""), urls


class ResearchState(TypedDict):
    messages: Annotated[list, operator.add]
    tool_calls_total: int
    reflection_count: int


def research_stream(
    investor_name: str,
    inv_id: str,
    existing_transactions: list[dict],
    on_add_txn: Callable[[dict], dict],
    on_remove_txn: Callable[[str], bool],
    model: str | None = None,
    project_root=None,
    openai_api_key: str | None = None,
) -> Generator[dict, None, None]:
    from pathlib import Path

    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from langchain_core.tools import tool as lc_tool
    from langchain_openai import ChatOpenAI
    from langgraph.graph import END, START, StateGraph

    api_key = (openai_api_key or os.getenv("OPENAI_API_KEY") or "").strip()
    provider_pref = (os.getenv("TRACKER_LLM_PROVIDER") or "auto").strip().lower()
    codex_ok = False
    if project_root is not None:
        try:
            import codex_chat as _cc
            codex_ok = bool(_cc.auth_status(Path(project_root)).get("authenticated"))
        except Exception:
            codex_ok = False

    has_api_key = bool(api_key and api_key.startswith("sk-"))
    if provider_pref == "codex":
        use_codex = codex_ok
    elif provider_pref == "openai":
        use_codex = False
    else:
        # Match company analyzer: prefer API key when both are available.
        use_codex = codex_ok and not has_api_key

    if use_codex:
        llm_model = model or os.getenv("CODEX_CHAT_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.5"
    else:
        llm_model = model or os.getenv("OPENAI_MODEL") or "gpt-5.5"

    if use_codex and not codex_ok:
        yield {"type": "error", "text": "ChatGPT not signed in — open Ask AI and sign in, or set OPENAI_API_KEY (sk-...)."}
        return
    if not use_codex and not has_api_key:
        yield {"type": "error", "text": "OPENAI_API_KEY not set — add sk-... to .env or sign in with ChatGPT (Ask AI panel)."}
        return

    if use_codex:
        try:
            from web.langgraph_analyzer import CodexChatModel
        except ImportError:
            from langgraph_analyzer import CodexChatModel
        llm = CodexChatModel(project_root=Path(project_root), model_name=llm_model)
        yield {"type": "status", "text": f"Using ChatGPT subscription ({llm_model})…"}
    else:
        llm = ChatOpenAI(model=llm_model, api_key=api_key, temperature=0.15)
        yield {"type": "status", "text": f"Using OpenAI API ({llm_model})…"}

    existing_summary = [
        {
            "id": t.get("id"),
            "symbol": t.get("symbol"),
            "action": t.get("action"),
            "date": t.get("date"),
            "notes": (t.get("notes") or "")[:80],
        }
        for t in existing_transactions[:40]
    ]
    _search_cache: dict[str, list] = {}

    @lc_tool
    def fetch_institutional_holdings(entity_name: str, quarters: int = 1) -> str:
        """Fetch and parse recent 13F-HR holdings for a legal entity (fund, advisor, trust).
        Returns resolved positions with symbol/action/date/shares — ready for add_transaction."""
        return json.dumps(_fetch_institutional_holdings(entity_name, quarters=quarters))

    @lc_tool
    def fetch_insider_trades(person_name: str, max_filings: int = 5) -> str:
        """Search and parse Form 4 insider filings for a person. Returns transactions ready to add."""
        return json.dumps(_fetch_insider_trades(person_name, max_filings=max_filings))

    @lc_tool
    def search_edgar_fulltext(query: str, form_types: str = "4,13F-HR,SC 13D,SC 13G") -> str:
        """Full-text search across SEC EDGAR filings. Use quoted phrases for exact names.
        form_types: comma-separated, e.g. '4', '13F-HR', 'SC 13D,SC 13G'."""
        results = _edgar_fulltext_search(query, form_types)
        if not results:
            return json.dumps({"found": 0})
        return json.dumps({"found": len(results), "filings": results})

    @lc_tool
    def find_edgar_entity(entity_name: str, form_type: str = "13F-HR") -> str:
        """Find a registrant on EDGAR by legal entity name and list its recent filings.
        Use for funds, advisors, trusts, or companies — not just personal names."""
        payload = _edgar_entity_filings(entity_name, form_type=form_type, limit=4)
        return json.dumps(payload)

    @lc_tool
    def parse_form4_filing(filing_index_url: str) -> str:
        """Parse a Form 4 filing index URL into insider transactions (symbol/action/date/shares/price)."""
        txns = _edgar_filing_xml(filing_index_url)
        if not txns:
            return json.dumps({"found": 0})
        return json.dumps({"found": len(txns), "transactions": txns})

    @lc_tool
    def parse_13f_filing(filing_index_url: str) -> str:
        """Parse a 13F-HR filing index URL into holdings (issuer/cusip/shares/value/put_call)."""
        holdings = _edgar_13f_holdings(filing_index_url)
        if not holdings:
            return json.dumps({"found": 0})
        return json.dumps({"found": len(holdings), "holdings": holdings})

    @lc_tool
    def resolve_ticker(issuer_or_company: str) -> str:
        """Resolve a company/issuer name to a US stock ticker symbol."""
        ticker = _guess_ticker(issuer_or_company)
        if ticker:
            return json.dumps({"ticker": ticker, "issuer": issuer_or_company})
        return json.dumps({"ticker": None, "issuer": issuer_or_company, "message": "Could not resolve — try web search"})

    @lc_tool
    def search_web(query: str) -> str:
        """Search the public web for portfolio coverage, filings, interviews, disclosures."""
        results = _web_search_cached(query, max_results=8, cache=_search_cache)
        return json.dumps({"found": len(results), "results": results})

    @lc_tool
    def scrape_url(url: str) -> str:
        """Fetch and extract readable text from a URL for detailed parsing."""
        return _scrape_url(url)

    @lc_tool
    def list_tracker_transactions() -> str:
        """Return transactions already saved for this subject (includes ids for remove_transaction)."""
        return json.dumps({"count": len(existing_transactions), "transactions": existing_summary})

    @lc_tool
    def add_transaction(
        symbol: str,
        action: str,
        date: str,
        shares: float = None,
        price: float = None,
        notes: str = "",
        position_type: str = "",
    ) -> str:
        """Add a confirmed transaction immediately. action: buy or sell. position_type: long, call, put, exit."""
        sym = (symbol or "").upper().strip()
        act = (action or "").lower().strip()
        if not sym or not date or act not in ("buy", "sell"):
            return json.dumps({"error": "symbol, date, and action (buy/sell) required"})
        dup = _find_duplicate_txn(existing_transactions, {
            "symbol": sym, "action": act, "date": date[:10],
        })
        if dup:
            return json.dumps({"ok": False, "duplicate": True, "existing": dup,
                               "message": f"{act} {sym} on {date[:10]} already tracked"})
        body = {
            "symbol": sym,
            "action": act,
            "date": date[:10],
            "shares": shares,
            "price": price,
            "notes": notes,
        }
        pt = (position_type or "").strip().lower()
        if pt:
            body["position_type"] = pt
        saved = on_add_txn(body)
        if any(t.get("id") == saved.get("id") for t in existing_transactions):
            return json.dumps({"ok": False, "duplicate": True, "existing": saved,
                               "message": f"{act} {sym} on {date[:10]} already tracked"})
        existing_transactions.append(saved)
        existing_summary.append({
            "id": saved.get("id"),
            "symbol": saved.get("symbol"),
            "action": saved.get("action"),
            "date": saved.get("date"),
            "notes": (saved.get("notes") or "")[:80],
        })
        return json.dumps({"ok": True, "transaction": saved})

    @lc_tool
    def remove_transaction(transaction_id: str) -> str:
        """Remove a saved transaction by id."""
        ok = on_remove_txn(transaction_id)
        if ok:
            existing_transactions[:] = [t for t in existing_transactions if t.get("id") != transaction_id]
            existing_summary[:] = [t for t in existing_summary if t.get("id") != transaction_id]
            return json.dumps({"ok": True, "removed": transaction_id})
        return json.dumps({"ok": False, "error": "not found"})

    tools = [
        fetch_institutional_holdings, fetch_insider_trades,
        search_edgar_fulltext, find_edgar_entity, parse_form4_filing, parse_13f_filing,
        resolve_ticker, search_web, scrape_url, list_tracker_transactions,
        add_transaction, remove_transaction,
    ]

    firecrawl_key = (os.getenv("FIRECRAWL_API_KEY") or "").strip()
    if firecrawl_key:
        try:
            from firecrawl import Firecrawl as _FC

            @lc_tool
            def firecrawl_search(query: str) -> str:
                """Alternative web search with richer page extraction."""
                fc = _FC(api_key=firecrawl_key)
                results = fc.search(query, limit=5)
                return json.dumps(results if isinstance(results, (list, dict)) else {"result": str(results)})

            tools.append(firecrawl_search)
        except ImportError:
            pass

    llm_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    context_block = f"""Subject: {investor_name}
Already tracked: {len(existing_transactions)} transactions
Sample existing symbols: {sorted({t.get('symbol','') for t in existing_transactions if t.get('symbol')})[:20] or 'none'}"""

    def plan_node(_state: ResearchState) -> dict:
        resp = llm.invoke([
            SystemMessage(content=PLAN_PROMPT),
            HumanMessage(content=context_block),
        ])
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        follow_up = ""
        try:
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                plan = json.loads(match.group(0))
                entities = [e for e in (plan.get("filing_entities_to_check") or []) if e]
                if entities:
                    follow_up = (
                        "\nBegin execution with fetch_institutional_holdings() and/or fetch_insider_trades() "
                        f"for the entities/roles you identified: {', '.join(entities[:5])}."
                    )
        except Exception:
            pass
        return {"messages": [HumanMessage(content=f"Research plan:\n{content}{follow_up}\n\nExecute the plan using tools.")]}

    def analyst_node(state: ResearchState) -> dict:
        msgs = list(state["messages"])
        if state.get("tool_calls_total", 0) >= 6:
            trimmed = []
            for m in msgs:
                if isinstance(m, ToolMessage) and len(m.content or "") > 2500:
                    trimmed.append(ToolMessage(
                        content=(m.content or "")[:2500] + "\n[truncated]",
                        tool_call_id=m.tool_call_id,
                        name=getattr(m, "name", None),
                    ))
                else:
                    trimmed.append(m)
            msgs = trimmed
        response = llm_tools.invoke([SystemMessage(content=SYSTEM_PROMPT), *msgs])
        return {"messages": [response]}

    def execute_tools_node(state: ResearchState) -> dict:
        last = state["messages"][-1]
        results = []
        total = state["tool_calls_total"]
        for tc in last.tool_calls:
            fn = tool_map.get(tc["name"])
            try:
                out = fn.invoke(tc["args"]) if fn else f"[unknown tool: {tc['name']}]"
            except Exception as e:
                out = f"[tool error: {e}]"
            results.append(ToolMessage(content=str(out), tool_call_id=tc["id"], name=tc["name"]))
            total += 1
        return {"messages": results, "tool_calls_total": total}

    def reflection_node(state: ResearchState) -> dict:
        return {
            "messages": [HumanMessage(content=REFLECTION_PROMPT)],
            "reflection_count": state.get("reflection_count", 0) + 1,
        }

    def route_after_analyst(state: ResearchState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "tools"
        return END

    def route_after_tools(state: ResearchState) -> str:
        total = state.get("tool_calls_total", 0)
        reflections = state.get("reflection_count", 0)
        if total >= 5 and reflections < 2 and (total >= 8 or (total >= 5 and reflections == 0)):
            return "reflect"
        if total >= 24:
            return END
        return "analyst"

    g = StateGraph(ResearchState)
    g.add_node("plan", plan_node)
    g.add_node("analyst", analyst_node)
    g.add_node("tools", execute_tools_node)
    g.add_node("reflect", reflection_node)
    g.add_edge(START, "plan")
    g.add_edge("plan", "analyst")
    g.add_conditional_edges("analyst", route_after_analyst, {"tools": "tools", END: END})
    g.add_conditional_edges("tools", route_after_tools, {"reflect": "reflect", "analyst": "analyst", END: END})
    g.add_edge("reflect", "analyst")
    graph = g.compile()

    init: ResearchState = {
        "messages": [HumanMessage(content=f"Build a verified transaction ledger for: {investor_name}")],
        "tool_calls_total": 0,
        "reflection_count": 0,
    }

    yield {"type": "status", "text": f"Starting research on {investor_name}…"}
    total_added = 0

    try:
        for chunk in graph.stream(init, stream_mode="updates"):
            for node_name, node_update in chunk.items():
                msgs = node_update.get("messages", [])
                if node_name == "plan":
                    yield {"type": "status", "text": "Planning research approach…"}
                    for msg in msgs:
                        content = getattr(msg, "content", "") or ""
                        if isinstance(content, str) and "Research plan:" in content:
                            plan_body = content.split("Research plan:\n", 1)[-1].split("\n\nExecute")[0]
                            yield {
                                "type": "think",
                                "title": "Research plan",
                                "text": _format_plan_think(plan_body),
                            }
                elif node_name == "reflect":
                    yield {"type": "status", "text": "Reflecting on research coverage…"}
                    yield {
                        "type": "think",
                        "title": "Reflection",
                        "text": (
                            "Checking whether the right entities and filing types were covered, "
                            "whether to pivot away from empty personal-name searches, and what to do next."
                        ),
                    }
                for msg in msgs:
                    if node_name == "analyst" and isinstance(msg, AIMessage):
                        if getattr(msg, "tool_calls", None):
                            for tc in msg.tool_calls:
                                args = tc.get("args") or {}
                                url = args.get("url") or args.get("filing_index_url") or ""
                                yield {
                                    "type": "tool",
                                    "tool": tc["name"],
                                    "detail": _tool_call_detail(tc["name"], args),
                                    "symbol": args.get("symbol", ""),
                                    "url": url,
                                }
                        elif msg.content:
                            text = msg.content if isinstance(msg.content, str) else str(msg.content)
                            if text.strip():
                                yield {
                                    "type": "think",
                                    "title": "Reasoning",
                                    "text": text.strip()[:2000],
                                }
                    elif node_name == "tools" and isinstance(msg, ToolMessage):
                        name = getattr(msg, "name", "") or ""
                        summary, urls = _summarize_tool_result(name, msg.content or "")
                        if summary or urls:
                            yield {
                                "type": "tool_result",
                                "tool": name,
                                "summary": summary,
                                "urls": urls,
                            }
                        if name == "add_transaction":
                            try:
                                result = json.loads(msg.content or "")
                                if result.get("ok") and result.get("transaction"):
                                    total_added += 1
                                    yield {"type": "txn_added", "txn": result["transaction"]}
                            except Exception:
                                pass
                        elif name == "remove_transaction":
                            try:
                                result = json.loads(msg.content or "")
                                if result.get("ok"):
                                    total_added = max(0, total_added - 1)
                                    yield {"type": "txn_removed", "txn_id": result["removed"]}
                            except Exception:
                                pass
    except Exception as e:
        yield {"type": "error", "text": f"Agent error: {e}"}
        return

    yield {"type": "done", "total_found": total_added}
