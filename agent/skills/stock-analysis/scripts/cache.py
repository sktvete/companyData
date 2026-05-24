"""Disk-based JSON cache for EODHD API responses.

Stores responses as JSON files keyed by endpoint+params hash.
Configurable TTL prevents stale data from being reused.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "stock-analysis"
DEFAULT_TTL_SECONDS = 6 * 3600  # 6 hours


class DiskCache:
    """Simple disk-based cache with TTL expiration."""

    def __init__(
        self,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_seconds
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key_hash(self, key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()[:24]

    def _entry_path(self, key: str) -> Path:
        return self.cache_dir / f"{self._key_hash(key)}.json"

    def get(self, key: str) -> Any | None:
        """Return cached value if exists and not expired, else None."""
        path = self._entry_path(key)
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if time.time() - entry.get("ts", 0) > self.ttl_seconds:
            path.unlink(missing_ok=True)
            return None
        return entry.get("data")

    def set(self, key: str, data: Any) -> None:
        """Store value with current timestamp."""
        entry = {"ts": time.time(), "key": key, "data": data}
        path = self._entry_path(key)
        path.write_text(json.dumps(entry, default=str), encoding="utf-8")

    def make_key(self, endpoint: str, params: dict[str, Any]) -> str:
        """Build a deterministic cache key from endpoint and params."""
        sorted_params = json.dumps(params, sort_keys=True, default=str)
        return f"{endpoint}|{sorted_params}"

    def clear(self) -> int:
        """Remove all cached files. Returns count of files removed."""
        count = 0
        for f in self.cache_dir.glob("*.json"):
            f.unlink(missing_ok=True)
            count += 1
        return count

    def clear_expired(self) -> int:
        """Remove only expired entries. Returns count removed."""
        count = 0
        now = time.time()
        for f in self.cache_dir.glob("*.json"):
            try:
                entry = json.loads(f.read_text(encoding="utf-8"))
                if now - entry.get("ts", 0) > self.ttl_seconds:
                    f.unlink(missing_ok=True)
                    count += 1
            except (json.JSONDecodeError, OSError):
                f.unlink(missing_ok=True)
                count += 1
        return count
