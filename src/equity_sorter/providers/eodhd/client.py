from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import requests


BASE_URL = "https://eodhd.com/api"


@dataclass(frozen=True)
class EODHDRequest:
    endpoint: str
    params: dict[str, Any]


class EODHDClient:
    def __init__(self, api_key: str, session: requests.Session | None = None) -> None:
        self.api_key = api_key
        self.session = session or requests.Session()

    def get_json(self, request: EODHDRequest) -> Any:
        params = dict(request.params)
        params["api_token"] = self.api_key
        params.setdefault("fmt", "json")
        response = self.session.get(f"{BASE_URL}/{request.endpoint}", params=params, timeout=60)
        response.raise_for_status()
        return response.json()
