"""Lazily built, process-wide view of the documentation.

Parsing and indexing cost a fraction of a second, but they are pure CPU work, so
they run in a worker thread and only once per refresh. Nothing is fetched at
import time: the server starts instantly and reaches the network on first use.
"""

from __future__ import annotations

import time
from typing import Any

import anyio
from anyio import to_thread

from .config import Config
from .corpus import Corpus, build_corpus
from .fetcher import cache_state, ensure_cached, load_sources, refresh
from .search import SearchIndex


class DocsStore:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._corpus: Corpus | None = None
        self._index: SearchIndex | None = None
        self._last_sync: dict[str, Any] = {}
        self._last_refresh_at: float | None = None
        self._lock = anyio.Lock()

    def status(self) -> dict[str, Any]:
        """Local state only; makes no network request."""
        state = cache_state(self.cfg)
        state["loaded"] = self._corpus is not None
        state["pages_loaded"] = len(self._corpus.pages) if self._corpus else 0
        state["base_url"] = self.cfg.base_url
        state["last_sync"] = {
            k: v for k, v in self._last_sync.items() if k in {"refreshed", "changed", "fetch_failed"}
        }
        return state

    def _seconds_since_refresh(self) -> float | None:
        if self._last_refresh_at is None:
            return None
        return time.monotonic() - self._last_refresh_at

    def _build(self) -> None:
        full_text, index_text = load_sources(self.cfg)
        corpus = build_corpus(full_text, index_text, self.cfg.base_url)
        self._corpus = corpus
        self._index = SearchIndex(corpus)

    async def ready(self) -> Corpus:
        async with self._lock:
            if self._corpus is None:
                self._last_sync = await ensure_cached(self.cfg)
                # The docs are current as of now, so the refresh floor starts here
                # rather than on the first explicit refresh.
                self._last_refresh_at = time.monotonic()
                await to_thread.run_sync(self._build)
            assert self._corpus is not None
            return self._corpus

    async def searcher(self) -> SearchIndex:
        await self.ready()
        assert self._index is not None
        return self._index

    async def refresh(self, *, force: bool = False) -> dict[str, Any]:
        async with self._lock:
            waited = self._seconds_since_refresh()
            floor = self.cfg.min_refresh_seconds
            if waited is not None and waited < floor:
                return {
                    "refreshed": False,
                    "throttled": True,
                    "retry_after_seconds": round(floor - waited),
                    "reason": (
                        f"the docs were refreshed {round(waited)}s ago; "
                        f"refreshes are limited to one per {floor}s"
                    ),
                    "cache": cache_state(self.cfg),
                }
            report = await refresh(self.cfg, force=force)
            self._last_refresh_at = time.monotonic()
            self._last_sync = report
            await to_thread.run_sync(self._build)
            corpus = self._corpus
            report["pages"] = len(corpus.pages) if corpus else 0
            report["chunks"] = len(corpus.chunks) if corpus else 0
            return report
