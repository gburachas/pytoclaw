"""LRU search cache with trigram-based similarity matching."""

from __future__ import annotations

import threading
import time

from pyclaw.skills.models import SearchResult

SIMILARITY_THRESHOLD = 0.7


class SearchCache:
    """Lightweight LRU cache for skill search results.

    Uses trigram Jaccard similarity to match similar queries, avoiding
    redundant API calls. Thread-safe.
    """

    def __init__(
        self,
        max_entries: int = 50,
        ttl_seconds: float = 300.0,
    ) -> None:
        self._max_entries = max(max_entries, 1)
        self._ttl = ttl_seconds
        self._entries: dict[str, _CacheEntry] = {}
        self._order: list[str] = []  # LRU order: oldest first
        self._lock = threading.Lock()

    def get(self, query: str) -> tuple[list[SearchResult] | None, bool]:
        """Look up results for a query.

        Returns (results, True) on hit (exact or similar), (None, False) on miss.
        """
        normalized = _normalize(query)
        if not normalized:
            return None, False

        with self._lock:
            # Exact match first.
            entry = self._entries.get(normalized)
            if entry is not None and not self._is_expired(entry):
                self._move_to_end(normalized)
                return _copy_results(entry.results), True

            # Similarity match.
            query_trigrams = _build_trigrams(normalized)
            best_entry: _CacheEntry | None = None
            best_sim = 0.0

            for e in self._entries.values():
                if self._is_expired(e):
                    continue
                sim = _jaccard_similarity(query_trigrams, e.trigrams)
                if sim > best_sim:
                    best_sim = sim
                    best_entry = e

            if best_sim >= SIMILARITY_THRESHOLD and best_entry is not None:
                self._move_to_end(best_entry.query)
                return _copy_results(best_entry.results), True

        return None, False

    def put(self, query: str, results: list[SearchResult]) -> None:
        """Store results for a query. Evicts oldest entry if at capacity."""
        normalized = _normalize(query)
        if not normalized:
            return

        with self._lock:
            # Evict expired entries first.
            self._evict_expired()

            # Update existing.
            if normalized in self._entries:
                self._entries[normalized] = _CacheEntry(
                    query=normalized,
                    trigrams=_build_trigrams(normalized),
                    results=_copy_results(results),
                    created_at=time.monotonic(),
                )
                self._move_to_end(normalized)
                return

            # Evict LRU if at capacity.
            while len(self._entries) >= self._max_entries and self._order:
                oldest = self._order.pop(0)
                self._entries.pop(oldest, None)

            # Insert new entry.
            self._entries[normalized] = _CacheEntry(
                query=normalized,
                trigrams=_build_trigrams(normalized),
                results=_copy_results(results),
                created_at=time.monotonic(),
            )
            self._order.append(normalized)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    # --- internal ---

    def _is_expired(self, entry: _CacheEntry) -> bool:
        return (time.monotonic() - entry.created_at) >= self._ttl

    def _evict_expired(self) -> None:
        new_order: list[str] = []
        for key in self._order:
            entry = self._entries.get(key)
            if entry is None or self._is_expired(entry):
                self._entries.pop(key, None)
            else:
                new_order.append(key)
        self._order = new_order

    def _move_to_end(self, key: str) -> None:
        try:
            self._order.remove(key)
        except ValueError:
            pass
        self._order.append(key)


class _CacheEntry:
    __slots__ = ("query", "trigrams", "results", "created_at")

    def __init__(
        self,
        query: str,
        trigrams: list[int],
        results: list[SearchResult],
        created_at: float,
    ) -> None:
        self.query = query
        self.trigrams = trigrams
        self.results = results
        self.created_at = created_at


def _normalize(query: str) -> str:
    return query.strip().lower()


def _build_trigrams(s: str) -> list[int]:
    """Build sorted, deduplicated trigram hashes from a string."""
    if len(s) < 3:
        return []
    trigrams: list[int] = []
    for i in range(len(s) - 2):
        trigrams.append(ord(s[i]) << 16 | ord(s[i + 1]) << 8 | ord(s[i + 2]))

    trigrams.sort()
    # Deduplicate.
    deduped = [trigrams[0]]
    for i in range(1, len(trigrams)):
        if trigrams[i] != trigrams[i - 1]:
            deduped.append(trigrams[i])
    return deduped


def _jaccard_similarity(a: list[int], b: list[int]) -> float:
    """Compute |A ∩ B| / |A ∪ B| on sorted integer arrays."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0

    i = j = 0
    intersection = 0

    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            intersection += 1
            i += 1
            j += 1
        elif a[i] < b[j]:
            i += 1
        else:
            j += 1

    union = len(a) + len(b) - intersection
    return intersection / union if union else 0.0


def _copy_results(results: list[SearchResult]) -> list[SearchResult]:
    return [r.model_copy() for r in results]
