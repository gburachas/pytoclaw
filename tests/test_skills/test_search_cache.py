"""Tests for the search cache with trigram similarity."""

import time

import pytest

from pyclaw.skills.models import SearchResult
from pyclaw.skills.search_cache import (
    SearchCache,
    _build_trigrams,
    _jaccard_similarity,
    _normalize,
)


def _make_result(slug: str, score: float = 1.0) -> SearchResult:
    return SearchResult(slug=slug, score=score, display_name=slug, summary="test")


class TestSearchCache:
    def test_exact_match(self):
        cache = SearchCache()
        results = [_make_result("skill-a")]
        cache.put("weather tool", results)

        cached, hit = cache.get("weather tool")
        assert hit is True
        assert cached is not None
        assert len(cached) == 1
        assert cached[0].slug == "skill-a"

    def test_miss(self):
        cache = SearchCache()
        cached, hit = cache.get("nonexistent query")
        assert hit is False
        assert cached is None

    def test_case_insensitive(self):
        cache = SearchCache()
        cache.put("Weather Tool", [_make_result("skill-a")])
        cached, hit = cache.get("weather tool")
        assert hit is True

    def test_similar_query_match(self):
        cache = SearchCache()
        cache.put("weather forecast tool", [_make_result("skill-a")])

        # Similar query should match
        cached, hit = cache.get("weather forecast tools")
        assert hit is True

    def test_dissimilar_query_miss(self):
        cache = SearchCache()
        cache.put("weather forecast tool", [_make_result("skill-a")])

        cached, hit = cache.get("completely different query about cooking")
        assert hit is False

    def test_ttl_expiration(self):
        cache = SearchCache(ttl_seconds=0.01)  # 10ms TTL
        cache.put("test query", [_make_result("skill-a")])

        time.sleep(0.02)  # Wait for expiration

        cached, hit = cache.get("test query")
        assert hit is False

    def test_lru_eviction(self):
        cache = SearchCache(max_entries=2)
        cache.put("query one", [_make_result("a")])
        cache.put("query two", [_make_result("b")])
        cache.put("query three", [_make_result("c")])

        # "query one" should have been evicted
        _, hit = cache.get("query one")
        assert hit is False

        # "query two" and "query three" should remain
        _, hit2 = cache.get("query two")
        _, hit3 = cache.get("query three")
        assert hit2 is True
        assert hit3 is True

    def test_lru_access_refreshes(self):
        cache = SearchCache(max_entries=2)
        cache.put("query one", [_make_result("a")])
        cache.put("query two", [_make_result("b")])

        # Access "query one" to refresh it
        cache.get("query one")

        # Add a third — should evict "query two" (least recently used)
        cache.put("query three", [_make_result("c")])

        _, hit1 = cache.get("query one")
        _, hit2 = cache.get("query two")
        assert hit1 is True
        assert hit2 is False

    def test_update_existing(self):
        cache = SearchCache()
        cache.put("test query", [_make_result("old")])
        cache.put("test query", [_make_result("new")])

        cached, hit = cache.get("test query")
        assert hit is True
        assert cached[0].slug == "new"

    def test_empty_query_ignored(self):
        cache = SearchCache()
        cache.put("", [_make_result("a")])
        assert len(cache) == 0

    def test_len(self):
        cache = SearchCache()
        assert len(cache) == 0
        cache.put("query a", [_make_result("a")])
        assert len(cache) == 1
        cache.put("query b", [_make_result("b")])
        assert len(cache) == 2


class TestTrigrams:
    def test_short_string(self):
        assert _build_trigrams("ab") == []

    def test_basic_trigrams(self):
        trigrams = _build_trigrams("abc")
        assert len(trigrams) == 1

    def test_deduplication(self):
        trigrams = _build_trigrams("aaaa")
        # "aaa" appears twice, should be deduped
        assert len(trigrams) == 1

    def test_jaccard_identical(self):
        a = _build_trigrams("hello world")
        assert _jaccard_similarity(a, a) == 1.0

    def test_jaccard_empty(self):
        assert _jaccard_similarity([], []) == 1.0
        assert _jaccard_similarity([1, 2], []) == 0.0

    def test_jaccard_similar(self):
        a = _build_trigrams("weather forecast")
        b = _build_trigrams("weather forecasts")
        sim = _jaccard_similarity(a, b)
        assert sim > 0.7  # Should be very similar

    def test_jaccard_dissimilar(self):
        a = _build_trigrams("weather forecast")
        b = _build_trigrams("cooking recipe")
        sim = _jaccard_similarity(a, b)
        assert sim < 0.3


class TestNormalize:
    def test_basic(self):
        assert _normalize("  Hello World  ") == "hello world"

    def test_empty(self):
        assert _normalize("") == ""
