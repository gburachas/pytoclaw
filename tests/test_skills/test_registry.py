"""Tests for the registry interface and manager."""

import asyncio

import pytest

from pyclaw.skills.models import InstallResult, SearchResult, SkillMeta
from pyclaw.skills.registry import RegistryManager, SkillRegistry


class MockRegistry(SkillRegistry):
    """Minimal mock registry for testing."""

    def __init__(
        self,
        registry_name: str = "mock",
        results: list[SearchResult] | None = None,
        raise_on_search: Exception | None = None,
    ):
        self._name = registry_name
        self._results = results or []
        self._raise_on_search = raise_on_search

    def name(self) -> str:
        return self._name

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if self._raise_on_search:
            raise self._raise_on_search
        return self._results[:limit]

    async def get_skill_meta(self, slug: str) -> SkillMeta | None:
        return None

    async def download_and_install(
        self, slug: str, version: str, target_dir: str,
    ) -> InstallResult:
        return InstallResult(version="1.0.0")


class TestRegistryManager:
    def test_empty_manager(self):
        mgr = RegistryManager()
        results = asyncio.get_event_loop().run_until_complete(
            mgr.search_all("test", 5)
        )
        assert results == []

    def test_add_and_get_registry(self):
        mgr = RegistryManager()
        reg = MockRegistry("test-reg")
        mgr.add_registry(reg)
        assert mgr.get_registry("test-reg") is reg
        assert mgr.get_registry("unknown") is None

    def test_search_all_merges_results(self):
        mgr = RegistryManager()
        mgr.add_registry(MockRegistry(
            "reg-a",
            [SearchResult(slug="a", score=0.9, display_name="A", summary="s")],
        ))
        mgr.add_registry(MockRegistry(
            "reg-b",
            [SearchResult(slug="b", score=0.8, display_name="B", summary="s")],
        ))

        results = asyncio.get_event_loop().run_until_complete(
            mgr.search_all("test", 10)
        )
        assert len(results) == 2
        # Should be sorted by score descending
        assert results[0].slug == "a"
        assert results[1].slug == "b"

    def test_search_all_clamps_to_limit(self):
        mgr = RegistryManager()
        mgr.add_registry(MockRegistry(
            "reg-a",
            [
                SearchResult(slug="a1", score=0.9, display_name="A1", summary="s"),
                SearchResult(slug="a2", score=0.8, display_name="A2", summary="s"),
            ],
        ))
        mgr.add_registry(MockRegistry(
            "reg-b",
            [
                SearchResult(slug="b1", score=0.7, display_name="B1", summary="s"),
            ],
        ))

        results = asyncio.get_event_loop().run_until_complete(
            mgr.search_all("test", 2)
        )
        assert len(results) == 2

    def test_partial_failure_handling(self):
        """If one registry fails, results from others still returned."""
        mgr = RegistryManager()
        mgr.add_registry(MockRegistry(
            "good",
            [SearchResult(slug="ok", score=1.0, display_name="OK", summary="s")],
        ))
        mgr.add_registry(MockRegistry(
            "bad",
            raise_on_search=RuntimeError("network error"),
        ))

        results = asyncio.get_event_loop().run_until_complete(
            mgr.search_all("test", 10)
        )
        assert len(results) == 1
        assert results[0].slug == "ok"

    def test_all_fail_returns_empty(self):
        mgr = RegistryManager()
        mgr.add_registry(MockRegistry(
            "bad1",
            raise_on_search=RuntimeError("fail"),
        ))

        results = asyncio.get_event_loop().run_until_complete(
            mgr.search_all("test", 10)
        )
        assert results == []
