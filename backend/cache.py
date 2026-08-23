"""
Result Cache — diskcache-backed persistent cache for pipeline results.

Why: identical source code should never hit the API twice.
     diskcache stores results on disk across server restarts.

Cache key: SHA256(source_code + target_function + run_mutation)
TTL: 24 hours (results are deterministic for a given input)

This is what separates a demo tool from a real developer tool.
"""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from typing import Optional

import diskcache

CACHE_DIR = Path(os.environ.get("TESTGEN_CACHE_DIR", "/tmp/testgen_cache"))
CACHE_TTL = 60 * 60 * 24  # 24 hours


class ResultCache:
    """
    Persistent disk cache for PipelineResult API responses.

    Stores the JSON-serialised ResultsResponse dict.
    The pipeline never knows about the cache — it lives in the API layer.

    Usage:
        cache = ResultCache()
        key = cache.make_key(source_code, target_function, run_mutation)
        hit = cache.get(key)
        if hit:
            return hit
        result = pipeline.run(...)
        cache.set(key, result_dict)
    """

    def __init__(self, cache_dir: Path = CACHE_DIR, ttl: int = CACHE_TTL):
        self._cache = diskcache.Cache(str(cache_dir))
        self._ttl = ttl

    def make_key(
        self,
        source_code: str,
        target_function: Optional[str],
        run_mutation: bool,
    ) -> str:
        payload = json.dumps({
            "source": source_code.strip(),
            "target": target_function or "",
            "mutation": run_mutation,
        }, sort_keys=True)
        return "v1:" + hashlib.sha256(payload.encode()).hexdigest()

    def get(self, key: str) -> Optional[dict]:
        try:
            return self._cache.get(key)
        except Exception:
            return None

    def set(self, key: str, value: dict) -> None:
        try:
            self._cache.set(key, value, expire=self._ttl)
        except Exception:
            pass  # cache miss is recoverable — don't crash the pipeline

    def invalidate(self, key: str) -> None:
        try:
            self._cache.delete(key)
        except Exception:
            pass

    def clear(self) -> int:
        """Clear all cache entries. Returns count cleared."""
        try:
            n = len(self._cache)
            self._cache.clear()
            return n
        except Exception:
            return 0

    def stats(self) -> dict:
        try:
            return {
                "size": len(self._cache),
                "dir": str(CACHE_DIR),
                "ttl_hours": self._ttl // 3600,
            }
        except Exception:
            return {}