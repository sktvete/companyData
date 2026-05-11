from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import requests


SEC_DATA_BASE = "https://data.sec.gov"
SEC_WWW_BASE = "https://www.sec.gov"


@dataclass(frozen=True)
class SECRequest:
    path: str
    base_url: str = SEC_DATA_BASE


class SECClient:
    def __init__(self, user_agent: str = "equity-sorter research@example.com", session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})

    def get_json(self, request: SECRequest) -> Any:
        base_url = request.base_url.rstrip("/")
        response = self.session.get(f"{base_url}{request.path}", timeout=60)
        response.raise_for_status()
        return response.json()
