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
_TICKER_CIK_CACHE: dict[str, dict] = {}
_BLOCKED_URL_RE = re.compile(
    r"pornhub|xvideos|xvideo|xxx\b|/r/pornhub|onlyfans",
    re.I,
)
_TRUSTED_FINANCE_DOMAINS = (
    "sec.gov", "efts.sec.gov", "oge.gov", "ethics.gov", "congress.gov",
    "senate.gov", "house.gov", "reuters.com", "bloomberg.com", "wsj.com",
    "ft.com", "cnbc.com", "apnews.com", "finance.yahoo.com",
)


def _json_dumps(obj) -> str:
    """JSON encode tool results; coerce httpx URLs and other non-serializable values."""
    def _default(v):
        if hasattr(v, "__str__") and type(v).__name__ in ("URL", "HttpUrl"):
            return str(v)
        raise TypeError(f"Object of type {type(v).__name__} is not JSON serializable")

    return json.dumps(obj, default=_default)


_KNOWN_FILING_ENTITIES: dict[str, str | None] = {
    "leopold aschenbrenner": "Situational Awareness LP",
    "cathie wood": "ARK Investment Management LLC",
    "brad gerstner": "Altimeter Capital Management, LP",
    "philippe laffont": "Coatue Management LLC",
    "dan sundheim": "D1 Capital Partners LP",
    "warren buffett": "BERKSHIRE HATHAWAY INC",
    "warren buffet": "BERKSHIRE HATHAWAY INC",
}


def _known_filing_entity(investor_name: str) -> str | None:
    return _KNOWN_FILING_ENTITIES.get((investor_name or "").strip().lower())


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
            accession = s.get("adsh") or (h.get("_id", "").split(":")[0] if h.get("_id") else "")
            ciks = s.get("ciks") or []
            cik_raw = ciks[0] if ciks else s.get("cik") or ""
            cik = str(cik_raw).lstrip("0")
            index_url = ""
            if cik and accession:
                acc_no_dash = accession.replace("-", "")
                index_url = f"{_EDGAR_BASE}/Archives/edgar/data/{cik}/{acc_no_dash}/{accession}-index.htm"
            display_names = s.get("display_names") or []
            entity = s.get("entity_name") or (display_names[0] if display_names else "")
            out.append({
                "form": s.get("form") or s.get("file_type") or s.get("form_type") or "",
                "entity": entity,
                "filed": s.get("file_date") or s.get("filed") or "",
                "period": s.get("period_of_report") or s.get("period_ending") or "",
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
            return [{"cik": cik, "name": entity_name, "filings_url": str(resp.url)}]
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


def _edgar_cik_from_ticker(ticker: str) -> dict:
    """Resolve a US ticker to CIK + company name via SEC company_tickers.json."""
    sym = (ticker or "").upper().strip()
    if not sym or not re.fullmatch(r"[A-Z]{1,5}", sym):
        return {}
    if sym in _TICKER_CIK_CACHE:
        return _TICKER_CIK_CACHE[sym]
    try:
        resp = httpx.get(
            f"{_EDGAR_BASE}/files/company_tickers.json",
            headers=_EDGAR_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        for entry in resp.json().values():
            if (entry.get("ticker") or "").upper() == sym:
                cik = str(entry.get("cik_str", "")).lstrip("0") or str(entry.get("cik_str", ""))
                info = {"cik": cik, "name": entry.get("title", ""), "ticker": sym}
                _TICKER_CIK_CACHE[sym] = info
                return info
    except Exception as e:
        logger.warning("Ticker CIK lookup error: %s", e)
    return {}


def _edgar_entity_filings(entity_name: str, form_type: str = "13F-HR", limit: int = 3) -> dict:
    """Resolve entity → CIK → recent filings with index URLs."""
    entities = _edgar_resolve_entities(entity_name, form_type=form_type)
    cik_only = re.fullmatch(r"\d{1,10}", (entity_name or "").strip())
    if not entities and cik_only:
        cik = cik_only.group(0).lstrip("0") or cik_only.group(0)
        entities = [{
            "cik": cik,
            "name": entity_name,
            "filings_url": f"{_EDGAR_BROWSE}?action=getcompany&CIK={cik}",
        }]
    if not entities and re.fullmatch(r"[A-Z]{1,5}", (entity_name or "").upper().strip()):
        info = _edgar_cik_from_ticker(entity_name)
        if info:
            entities = [{
                "cik": info["cik"],
                "name": info["name"],
                "ticker": info.get("ticker"),
                "filings_url": f"{_EDGAR_BROWSE}?action=getcompany&CIK={info['cik']}",
            }]
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
            code = (_xml_text(txn, ".//transactionCoding/transactionCode") or "").upper()
            date = _xml_text(txn, ".//transactionDate/value")[:10]
            shares_raw = _xml_text(txn, ".//transactionAmounts/transactionShares/value")
            price_raw = _xml_text(txn, ".//transactionAmounts/transactionPricePerShare/value")
            disp = (_xml_text(txn, ".//transactionAmounts/transactionAcquiredDisposedCode/value") or "").upper()
            if not ticker or not date:
                continue
            try:
                price = float(price_raw) if price_raw else None
            except ValueError:
                price = None
            try:
                shares = float(shares_raw.replace(",", "")) if shares_raw else None
            except ValueError:
                shares = None

            # Only record economic open-market trades. Skip grants, gifts, and
            # trust transfers that Form 4 codes as A/D with $0 price.
            if code in ("P", "M"):
                action = "buy"
            elif code == "S":
                action = "sell"
            elif code == "A" and price and price > 0:
                action = "buy"
            elif code in ("D",) and disp == "D" and price and price > 0:
                action = "sell"
            else:
                continue

            transactions.append({
                "symbol": ticker,
                "action": action,
                "date": date,
                "shares": shares,
                "price": price,
                "notes": f"SEC Form 4 ({code}) — {owner or 'insider filing'}",
            })
    except Exception as e:
        logger.warning("Form 4 parse error: %s", e)
    return transactions


def _pick_13f_xml_url(soup: BeautifulSoup) -> str:
    """Pick the info-table XML from a 13F filing index (not primary_doc.xml)."""
    candidates: list[tuple[int, str]] = []
    fallback: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.lower().endswith(".xml"):
            continue
        lower = href.lower()
        if "xsd" in lower or "primary_doc" in lower or "/xsl" in lower:
            continue
        abs_url = _abs_url(href)
        score = 0
        if "infotable" in lower:
            score += 5
        if "13f" in lower:
            score += 4
        if "form13f" in lower.replace("-", ""):
            score += 3
        # Berkshire and others use numeric filenames (e.g. 53405.xml) for info tables.
        if score == 0 and re.search(r"/\d+\.xml$", lower):
            score = 2
        if score > 0:
            candidates.append((score, abs_url))
        else:
            fallback.append(abs_url)
    if candidates:
        candidates.sort(key=lambda x: -x[0])
        return candidates[0][1]
    return fallback[0] if fallback else ""


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
                amt = info.find("ns:shrsOrPrnAmt", ns)
                if amt is None:
                    amt = info.find("shrsOrPrnAmt")
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


def _normalize_search_query(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return q
    ql = q.lower()
    if re.search(r"\d{10}-\d{2}-\d{6}", q) or re.search(r"\b(form\s*[34]|13[dfg]|edgar|sec filing)\b", ql):
        if "site:sec.gov" not in ql:
            q = f"site:sec.gov {q}"
    elif re.search(r"\b(oge form 278|financial disclosure|periodic transaction report|stock act)\b", ql):
        if "site:oge.gov" not in ql and "site:sec.gov" not in ql:
            q = f"(site:oge.gov OR site:sec.gov OR site:ethics.gov) {q}"
    return q


def _filter_web_results(results: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for r in results:
        url = r.get("url") or ""
        blob = f"{url} {r.get('title', '')} {r.get('body', '')}"
        if _BLOCKED_URL_RE.search(blob):
            continue
        kept.append(r)

    def _rank(r: dict) -> tuple[int, str]:
        url = (r.get("url") or "").lower()
        trusted = any(d in url for d in _TRUSTED_FINANCE_DOMAINS)
        return (0 if trusted else 1, url)

    kept.sort(key=_rank)
    return kept


def _web_search(query: str, max_results: int = 8) -> list[dict]:
    query = _normalize_search_query(query)
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max(max_results * 2, 12)):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "body": r.get("body", ""),
                })
        return _filter_web_results(results)[:max_results]
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


def _guess_ticker(issuer_or_name: str, allow_web: bool = False) -> str:
    """Best-effort ticker resolution from issuer name."""
    upper = issuer_or_name.upper()
    hints = [
        ("TESLA", "TSLA"), ("BLOCK INC", "XYZ"), ("SQUARE INC", "XYZ"), ("SQUARE", "XYZ"),
        ("EATON CORP", "ETN"), ("EATON", "ETN"), ("ROBINHOOD", "HOOD"), ("PALANTIR", "PLTR"),
        ("BLOOM ENERGY", "BE"), ("NVIDIA", "NVDA"), ("MICRON", "MU"), ("TAIWAN SEMICONDUCTOR", "TSM"),
        ("ADVANCED MICRO DEVICES", "AMD"), ("BROADCOM", "AVGO"), ("ORACLE", "ORCL"), ("INTEL", "INTC"),
        ("COREWEAVE", "CRWV"), ("SANDISK", "SNDK"), ("ASML", "ASML"), ("CORNING", "GLW"),
        ("VANECK", "SMH"), ("SEMICONDUCTOR ETF", "SMH"), ("BLOOM ENERGY CORP", "BE"),
        ("CORE SCIENTIFIC", "CORZ"), ("RIOT PLATFORMS", "RIOT"), ("CLEANSPARK", "CLSK"),
        ("APPLIED DIGITAL", "APLD"), ("IREN", "IREN"), ("BITDEER", "BTDR"), ("BITFARMS", "BITF"),
        ("HIVE DIGITAL", "HIVE"), ("INFOSYS", "INFY"), ("LUMENTUM", "LITE"), ("COHERENT", "COHR"),
        ("ARM HOLDINGS", "ARM"), ("SOFTBANK GROUP", "SFTBY"), ("META PLATFORMS", "META"),
        ("ALPHABET", "GOOGL"), ("AMAZON COM", "AMZN"), ("MICROSOFT", "MSFT"), ("APPLE INC", "AAPL"),
        ("CERUS CORP", "CERS"), ("ROKU INC", "ROKU"), ("COINBASE", "COIN"), ("SUPER MICRO", "SMCI"),
        ("COCA COLA", "KO"), ("COCA-COLA", "KO"), ("COCA COLA CO", "KO"),
        ("AMERICAN EXPRESS", "AXP"), ("BANK OF AMERICA", "BAC"), ("CHEVRON", "CVX"),
        ("HEICO CORP", "HEI"), ("HEICO", "HEI"), ("MOOG INC", "MOG"), ("MOOG", "MOG"),
        ("HEWLETT PACKARD", "HPE"), ("HP INC", "HPQ"), ("SEA LTD", "SE"), ("NOVA LTD", "NVT"),
        ("NICE LTD", "NICE"), ("JFROG LTD", "FROG"), ("JFROG", "FROG"),
    ]
    for needle, ticker in hints:
        if needle in upper:
            return ticker
    cleaned = re.sub(r"\s+(INC|CORP|CORPORATION|LTD|LLC|LP|PLC|HOLDINGS|CO\.?).*$", "", upper, flags=re.I).strip()
    if re.fullmatch(r"[A-Z]{1,5}", cleaned):
        return cleaned
    if not allow_web:
        return ""
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


def _parse_13f_position_value(val_raw: str, shares: float | None) -> tuple[float | None, float | None]:
    """Return (value_usd, price_per_share) from a 13F info-table value field.

    SEC spec says value is in thousands of USD, but some filers (e.g. Berkshire 2026)
    report full USD. Pick the interpretation whose implied price is plausible.
    """
    if not val_raw:
        return None, None
    try:
        raw = float(str(val_raw).replace(",", ""))
    except ValueError:
        return None, None
    if not shares or shares <= 0:
        return raw * 1000, None

    price_as_dollars = raw / shares
    price_as_thousands = (raw * 1000) / shares

    def _plausible(p: float) -> bool:
        return 0.01 < p < 50_000

    if _plausible(price_as_dollars):
        return raw, round(price_as_dollars, 2)
    if _plausible(price_as_thousands):
        return raw * 1000, round(price_as_thousands, 2)
    return raw * 1000, round(price_as_thousands, 2)


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
            value_usd, price = _parse_13f_position_value(val_raw, shares)
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

    def _val(p: dict) -> float:
        try:
            return float(str(p.get("value_usd") or 0))
        except ValueError:
            return 0.0

    def _issuer_key(name: str) -> str:
        return re.sub(r"\s+", " ", (name or "").upper()).strip()

    # One row per issuer (13F can repeat the same name with different share classes).
    by_issuer: dict[str, dict] = {}
    for p in all_positions:
        key = _issuer_key(p.get("issuer", ""))
        if not key:
            continue
        if key not in by_issuer or _val(p) > _val(by_issuer[key]):
            by_issuer[key] = p
    all_positions = list(by_issuer.values())

    # Sort by value descending; resolve tickers for the largest positions only (avoid 40+ web lookups)
    all_positions.sort(key=lambda p: -_val(p))
    ticker_map = _resolve_tickers_batch([p["issuer"] for p in all_positions[:25]])
    for p in all_positions:
        if not p.get("symbol"):
            sym = ticker_map.get(p["issuer"]) or _guess_ticker(p["issuer"])
            if sym and not _edgar_cik_from_ticker(sym):
                sym = _guess_ticker(p["issuer"]) or sym
            p["symbol"] = sym or None

    by_symbol: dict[str, dict] = {}
    for p in all_positions:
        sym = (p.get("symbol") or "").upper()
        if not sym or not _edgar_cik_from_ticker(sym):
            continue
        if sym not in by_symbol or _val(p) > _val(by_symbol[sym]):
            by_symbol[sym] = p
    resolved = list(by_symbol.values())
    resolved.sort(key=lambda p: -_val(p))
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


_ROMAN_NUMERAL_TICKERS = frozenset({"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"})


def _extract_ticker_hint(text: str) -> str:
    m = re.search(r"\(([A-Z]{1,5}),\s*[A-Z]{1,5}\)", text or "", re.I)
    if m:
        return m.group(1).upper()
    m = re.search(r"(?:Trading Symbol|Ticker Symbol)[:\s]+([A-Z]{1,5})\b", text or "", re.I)
    if m:
        return m.group(1).upper()
    for m in re.finditer(r"\(([A-Z]{2,5})\)", text or "", re.I):
        cand = m.group(1).upper()
        if cand not in _ROMAN_NUMERAL_TICKERS:
            return cand
    return ""


def _extract_ownership_shares(text: str) -> float | None:
    for pat in (
        r"beneficially owned by the Reporting Person.*?([\d,]+)\s+shares",
        r"Reporting Person beneficially owns.*?([\d,]+)\s+shares",
        r"aggregate amount of ([\d,]+) shares of (?:Class [A-Z] )?Common Stock beneficially owned by the Reporting Person",
        r"aggregate amount of ([\d,]+) shares of (?:Class [A-Z] )?Common Stock beneficially owned",
        r"beneficially own[s]? (?:approximately )?([\d,]+) shares of (?:Class [A-Z] )?Common Stock",
        r"([\d,]+)\s+shares of (?:Class [A-Z] )?Common Stock.*?beneficially owned",
    ):
        m = re.search(pat, text, re.I | re.S)
        if not m:
            continue
        try:
            val = float(m.group(1).replace(",", ""))
            if val >= 1000:
                return val
        except ValueError:
            continue
    return None


def _parse_filing_date(text: str, fallback: str = "") -> str:
    for pat in (
        r"(?:Date of Event Which Requires Filing|Event Date|Date of Event)[:\s]+([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        r"(?:Date of Event Which Requires Filing|Event Date|Date of Event)[:\s]+(\d{4}-\d{2}-\d{2})",
        r"(?:Filed|Filing Date)[:\s]+([A-Za-z]+\s+\d{1,2},\s+\d{4})",
    ):
        m = re.search(pat, text, re.I)
        if not m:
            continue
        raw = m.group(1).strip()
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return fallback


def _edgar_ownership_snapshots(filing_index_url: str, ticker_hint: str = "") -> list[dict]:
    """Parse SC 13D/13G/13D/A filings into beneficial ownership snapshots."""
    snapshots: list[dict] = []
    try:
        idx_resp = httpx.get(filing_index_url, headers=_EDGAR_HEADERS, timeout=20, follow_redirects=True)
        idx_resp.raise_for_status()
        soup = BeautifulSoup(idx_resp.text, "lxml")
        index_text = soup.get_text(" ", strip=True)

        ticker = (ticker_hint or "").upper().strip()
        if not ticker:
            ticker = _extract_ticker_hint(index_text)

        doc_url = ""
        candidates: list[tuple[int, str]] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            hl = href.lower()
            if not hl.endswith((".htm", ".html", ".txt")):
                continue
            if "index" in hl or "/xsl/" in hl or "companysearch" in hl:
                continue
            score = 0
            if "sc13" in hl or "13d" in hl or "13g" in hl:
                score += 5
            if hl.endswith(".txt") and "sc13" in hl:
                score += 4
            if hl.endswith(".htm"):
                score += 2
            candidates.append((score, _abs_url(href)))
        if candidates:
            candidates.sort(key=lambda x: -x[0])
            doc_url = candidates[0][1]
        if not doc_url:
            return []

        doc_resp = httpx.get(doc_url, headers=_EDGAR_HEADERS, timeout=20)
        doc_resp.raise_for_status()
        text = BeautifulSoup(doc_resp.text, "lxml").get_text(" ", strip=True)

        if not ticker:
            ticker = _extract_ticker_hint(text)

        shares = _extract_ownership_shares(text)

        pct = None
        m = re.search(r"(?:represent[s]?|constitute[s]?)\s+(?:approximately\s+)?([\d.]+)\s*%", text, re.I)
        if m:
            try:
                pct = float(m.group(1))
            except ValueError:
                pct = None

        reporting = ""
        m = re.search(
            r"Name of Reporting Person[s]?[:\s]+(.{4,100}?)(?:\s+(?:Address|Check|Citizenship)|\s{2,})",
            text,
            re.I,
        )
        if m:
            reporting = m.group(1).strip()

        filed_match = re.search(r"Filing Date[:\s]+(\d{4}-\d{2}-\d{2})", index_text, re.I)
        filed = filed_match.group(1) if filed_match else ""
        event_date = _parse_filing_date(text, filed or datetime.now().strftime("%Y-%m-%d"))

        if ticker and shares:
            note_parts = ["SEC beneficial ownership filing (SC 13D/13G)"]
            if reporting:
                note_parts.append(reporting[:80])
            if pct is not None:
                note_parts.append(f"{pct}% stake")
            note_parts.append("Snapshot of beneficial ownership, not necessarily an open-market purchase.")
            snapshots.append({
                "symbol": ticker,
                "action": "buy",
                "date": event_date,
                "shares": shares,
                "price": None,
                "position_type": "long",
                "notes": " — ".join(note_parts[:3]),
            })
    except Exception as e:
        logger.warning("Ownership filing parse error: %s", e)
    return snapshots


def _fetch_ownership_stakes(person_name: str, ticker: str = "", max_filings: int = 6) -> dict:
    """Search SC 13D/13G filings naming a person and parse ownership snapshots."""
    forms = "SC 13D,SC 13D/A,SC 13G,SC 13G/A"
    queries = [f'"{person_name}"']
    sym = (ticker or "").upper().strip()
    if sym:
        queries.append(f'"{person_name}" {sym}')

    seen_acc: set[str] = set()
    filings: list[dict] = []
    for q in queries:
        for f in _edgar_fulltext_search(q, form_types=forms, max_hits=max_filings):
            acc = f.get("accession") or ""
            if acc and acc in seen_acc:
                continue
            if acc:
                seen_acc.add(acc)
            filings.append(f)

    txns: list[dict] = []
    seen_keys: set[tuple] = set()
    for f in filings:
        url = f.get("index_url")
        if not url:
            continue
        entity = f.get("entity") or ""
        hint = sym or _extract_ticker_hint(entity)
        for t in _edgar_ownership_snapshots(url, ticker_hint=hint):
            if sym and t.get("symbol") != sym:
                continue
            key = (t["symbol"], t["date"], t.get("shares"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            t["notes"] = f"{t.get('notes', '')} Filed {f.get('filed', '')}.".strip()
            txns.append(t)

    return {
        "found": len(txns),
        "filings_checked": len(filings),
        "filings": filings,
        "transactions": txns,
        "instruction": (
            "These are beneficial ownership snapshots from SC 13D/13G filings — use action=buy, "
            "position_type=long, and note they are ownership stakes not open-market trades."
        ),
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

## How disclosures actually work (match tool to role)
| Role | Primary sources | Tools to use |
|------|-----------------|--------------|
| Fund manager / hedge fund | 13F-HR filed by the fund entity | fetch_institutional_holdings(entity=fund name) |
| Corporate insider / officer / director | Form 4 at the company; SC 13D if large stake | fetch_insider_trades; fetch_ownership_stakes; parse_form4_filing |
| Activist / controlling shareholder | SC 13D / SC 13D/A | fetch_ownership_stakes; search_edgar_fulltext; parse_ownership_filing |
| Passive 5%+ holder | SC 13G / SC 13G/A | fetch_ownership_stakes; parse_ownership_filing |
| U.S. President / VP / executive branch | OGE Form 278 & 278-T (NOT EDGAR) | search_web + scrape_url on oge.gov / news summaries |
| Member of Congress | STOCK Act / House & Senate disclosures | search_web + scrape_url (separate from EDGAR) |

## Critical reasoning rules
1. **Identify the subject's role first.** The filing entity is often NOT the person's personal name.
2. **Do NOT call fetch_institutional_holdings on trusts, LLCs, or revocable trusts** unless they are registered investment advisers that file 13F. Personal trusts do not file 13F.
3. **If personal-name Form 4 search returns 0**, pivot immediately to:
   - fetch_ownership_stakes(person_name, ticker=...) for SC 13D/13G stakes
   - find_edgar_entity(company name) or lookup_edgar_ticker(DJT) for the issuer company
   - search_edgar_fulltext with quoted name + form types SC 13D, SC 13G
4. **Use search_edgar_fulltext results directly** — parse filing index URLs with parse_ownership_filing or parse_form4_filing. Do NOT web-search raw accession numbers.
5. **Form 4 vs ownership filings:** Form 4 = insider trades (P/S open market). SC 13D/13G = beneficial ownership snapshots (record as buy/long with note). Do not treat $0 grant/transfer Form 4 rows as sales.
6. **Resolve tickers** before add_transaction. Use lookup_edgar_ticker or resolve_ticker.
7. **Write as you go** — add_transaction immediately when confirmed. list_tracker_transactions / remove_transaction for deduping.
8. **Evidence in notes** — cite form type, filing date, source URL.

## Quality bar
- Prefer primary SEC filings over secondary articles when both exist.
- Do not invent tickers, dates, or share counts.
- 13F rows are quarter-end snapshots; SC 13D rows are ownership snapshots — say so in notes.
- When fetch_* tools return ready-made transactions, add them — do not keep searching without recording findings.
- Avoid repeating failed queries; pivot strategy instead."""


PLAN_PROMPT = """Before using any tools, produce a concise research plan for the subject below.

Reply with ONLY valid JSON (no markdown):
{
  "subject_profile": "1-2 sentences: who they are and why they might appear in public market disclosures",
  "likely_roles": ["fund_manager", "corporate_insider", "politician", "activist_investor", "controlling_shareholder", "other"],
  "filing_entities_to_check": ["ONLY legal entities that actually file (fund names, public companies) — NOT personal trusts/LLCs unless known 13F filers"],
  "form_types_to_prioritize": ["13F-HR", "4", "SC 13D", "SC 13G", "OGE-278", "STOCK-act", "other"],
  "research_angles": ["3-6 concrete angles matched to the subject's role"],
  "risk_of_name_mismatch": "explain whether filings may appear under a different legal name than the subject"
}"""


REFLECTION_PROMPT = """Pause and assess your investigation so far.

Answer internally, then continue with tools:
1. Did you match filing types to the subject's role (13F for funds, SC 13D for control stakes, OGE 278 for President/VP, Form 4 for insiders)?
2. If personal-name Form 4 returned 0, did you try fetch_ownership_stakes and search_edgar_fulltext for SC 13D/13G?
3. Did you avoid wasting calls on trusts/LLCs that don't file 13F?
4. Are you parsing primary EDGAR index URLs instead of web-searching accession numbers?
5. Any duplicates to remove, or Form 4 rows that are grants/transfers misclassified as trades?
6. For politicians/President: did you search OGE Form 278-T disclosures via web?

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
    if name == "fetch_ownership_stakes":
        ticker = args.get("ticker") or ""
        extra = f", ticker={ticker}" if ticker else ""
        return f'ownership SC 13D/13G for "{args.get("person_name", "")}"{extra}'
    if name == "lookup_edgar_ticker":
        return f'CIK lookup for ticker "{args.get("ticker", "")}"'
    if name == "parse_ownership_filing":
        return args.get("filing_index_url", "ownership filing")
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

    if name in ("fetch_ownership_stakes", "parse_ownership_filing"):
        txns = data.get("transactions") or []
        syms = sorted({t.get("symbol") for t in txns if t.get("symbol")})[:8]
        urls = [f.get("index_url") for f in (data.get("filings") or []) if f.get("index_url")][:4]
        if not urls and data.get("filing_index_url"):
            urls = [data["filing_index_url"]]
        summary = f"{data.get('found', len(txns))} ownership snapshot(s)"
        if syms:
            summary += f" ({', '.join(syms)})"
        elif data.get("message"):
            summary = str(data["message"])[:160]
        return summary, urls

    if name == "lookup_edgar_ticker":
        if data.get("cik"):
            return f"{data.get('ticker', '')} → CIK {data['cik']} ({data.get('name', '')[:50]})", urls
        return data.get("message") or "Ticker not found on EDGAR", urls

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
        return _json_dumps(_fetch_institutional_holdings(entity_name, quarters=quarters))

    @lc_tool
    def fetch_insider_trades(person_name: str, max_filings: int = 5) -> str:
        """Search and parse Form 4 insider filings for a person. Returns transactions ready to add."""
        return _json_dumps(_fetch_insider_trades(person_name, max_filings=max_filings))

    @lc_tool
    def fetch_ownership_stakes(person_name: str, ticker: str = "", max_filings: int = 6) -> str:
        """Search SC 13D/13G beneficial ownership filings for a person. Best for controlling shareholders
        and corporate insiders where Form 4 personal-name search fails. Optional ticker filters results."""
        return _json_dumps(_fetch_ownership_stakes(person_name, ticker=ticker, max_filings=max_filings))

    @lc_tool
    def lookup_edgar_ticker(ticker: str) -> str:
        """Resolve a US stock ticker to EDGAR CIK and company name. Use before find_edgar_entity when you know the ticker."""
        info = _edgar_cik_from_ticker(ticker)
        if not info:
            return _json_dumps({"found": 0, "message": f"No EDGAR company for ticker {ticker.upper()}"})
        filings = _edgar_list_filings(info["cik"], form_type="SC 13D/A", limit=3)
        if not filings:
            filings = _edgar_list_filings(info["cik"], form_type="4", limit=3)
        return _json_dumps({"found": 1, **info, "recent_filings": filings})

    @lc_tool
    def search_edgar_fulltext(query: str, form_types: str = "4,13F-HR,SC 13D,SC 13G") -> str:
        """Full-text search across SEC EDGAR filings. Use quoted phrases for exact names.
        form_types: comma-separated, e.g. '4', '13F-HR', 'SC 13D,SC 13G'."""
        results = _edgar_fulltext_search(query, form_types)
        if not results:
            return _json_dumps({"found": 0})
        return _json_dumps({"found": len(results), "filings": results})

    @lc_tool
    def find_edgar_entity(entity_name: str, form_type: str = "13F-HR") -> str:
        """Find a registrant on EDGAR by legal entity name and list its recent filings.
        Use for funds, advisors, trusts, or companies — not just personal names."""
        payload = _edgar_entity_filings(entity_name, form_type=form_type, limit=4)
        return _json_dumps(payload)

    @lc_tool
    def parse_form4_filing(filing_index_url: str) -> str:
        """Parse a Form 4 filing index URL into insider transactions (symbol/action/date/shares/price)."""
        txns = _edgar_filing_xml(filing_index_url)
        if not txns:
            return _json_dumps({"found": 0})
        return _json_dumps({"found": len(txns), "transactions": txns})

    @lc_tool
    def parse_ownership_filing(filing_index_url: str, ticker: str = "") -> str:
        """Parse an SC 13D/13G/13D/A filing index URL into beneficial ownership snapshots."""
        txns = _edgar_ownership_snapshots(filing_index_url, ticker_hint=ticker)
        if not txns:
            return _json_dumps({"found": 0})
        return _json_dumps({"found": len(txns), "transactions": txns, "filing_index_url": filing_index_url})

    @lc_tool
    def parse_13f_filing(filing_index_url: str) -> str:
        """Parse a 13F-HR filing index URL into holdings (issuer/cusip/shares/value/put_call)."""
        holdings = _edgar_13f_holdings(filing_index_url)
        if not holdings:
            return _json_dumps({"found": 0})
        return _json_dumps({"found": len(holdings), "holdings": holdings})

    @lc_tool
    def resolve_ticker(issuer_or_company: str) -> str:
        """Resolve a company/issuer name to a US stock ticker symbol."""
        ticker = _guess_ticker(issuer_or_company, allow_web=True)
        if ticker:
            return _json_dumps({"ticker": ticker, "issuer": issuer_or_company})
        return _json_dumps({"ticker": None, "issuer": issuer_or_company, "message": "Could not resolve — try web search"})

    @lc_tool
    def search_web(query: str) -> str:
        """Search the public web for portfolio coverage, filings, interviews, disclosures."""
        results = _web_search_cached(query, max_results=8, cache=_search_cache)
        return _json_dumps({"found": len(results), "results": results})

    @lc_tool
    def scrape_url(url: str) -> str:
        """Fetch and extract readable text from a URL for detailed parsing."""
        return _scrape_url(url)

    @lc_tool
    def list_tracker_transactions() -> str:
        """Return transactions already saved for this subject (includes ids for remove_transaction)."""
        return _json_dumps({"count": len(existing_transactions), "transactions": existing_summary})

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
            return _json_dumps({"error": "symbol, date, and action (buy/sell) required"})
        dup = _find_duplicate_txn(existing_transactions, {
            "symbol": sym, "action": act, "date": date[:10],
        })
        if dup:
            return _json_dumps({"ok": False, "duplicate": True, "existing": dup,
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
            return _json_dumps({"ok": False, "duplicate": True, "existing": saved,
                               "message": f"{act} {sym} on {date[:10]} already tracked"})
        existing_transactions.append(saved)
        existing_summary.append({
            "id": saved.get("id"),
            "symbol": saved.get("symbol"),
            "action": saved.get("action"),
            "date": saved.get("date"),
            "notes": (saved.get("notes") or "")[:80],
        })
        return _json_dumps({"ok": True, "transaction": saved})

    @lc_tool
    def remove_transaction(transaction_id: str) -> str:
        """Remove a saved transaction by id."""
        ok = on_remove_txn(transaction_id)
        if ok:
            existing_transactions[:] = [t for t in existing_transactions if t.get("id") != transaction_id]
            existing_summary[:] = [t for t in existing_summary if t.get("id") != transaction_id]
            return _json_dumps({"ok": True, "removed": transaction_id})
        return _json_dumps({"ok": False, "error": "not found"})

    tools = [
        fetch_institutional_holdings, fetch_insider_trades, fetch_ownership_stakes,
        lookup_edgar_ticker, search_edgar_fulltext, find_edgar_entity,
        parse_form4_filing, parse_ownership_filing, parse_13f_filing,
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
                return _json_dumps(results if isinstance(results, (list, dict)) else {"result": str(results)})

            tools.append(firecrawl_search)
        except ImportError:
            pass

    llm_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    context_block = f"""Subject: {investor_name}
Already tracked: {len(existing_transactions)} transactions
Sample existing symbols: {sorted({t.get('symbol','') for t in existing_transactions if t.get('symbol')})[:20] or 'none'}"""
    known_entity = _known_filing_entity(investor_name)
    if known_entity:
        context_block += f"\nKnown 13F filing entity (use fetch_institutional_holdings first): {known_entity}"

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
                roles = [r for r in (plan.get("likely_roles") or []) if r]
                entities = [e for e in (plan.get("filing_entities_to_check") or []) if e]
                hints: list[str] = []
                if any(r in roles for r in ("controlling_shareholder", "corporate_insider", "activist_investor")):
                    hints.append("fetch_ownership_stakes(person_name) for SC 13D/13G stakes")
                if "fund_manager" in roles and entities:
                    hints.append(f"fetch_institutional_holdings for fund entities: {', '.join(entities[:3])}")
                if "politician" in roles:
                    hints.append("search_web for OGE Form 278-T / STOCK Act disclosures (not EDGAR)")
                if hints:
                    follow_up = "\nBegin execution prioritized by role: " + "; ".join(hints) + "."
                elif entities:
                    follow_up = (
                        "\nBegin execution with the filing types matched to the subject's role — "
                        f"not blind 13F lookups on: {', '.join(entities[:5])}."
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
