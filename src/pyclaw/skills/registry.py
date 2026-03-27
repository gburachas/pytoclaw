"""Registry interface and manager for skill registries."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

from pyclaw.skills.models import InstallResult, SearchResult, SkillMeta

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENT = 2


class SkillRegistry(ABC):
    """Abstract interface that all skill registries must implement."""

    @abstractmethod
    def name(self) -> str:
        """Unique name of this registry (e.g. 'clawhub')."""
        ...

    @abstractmethod
    async def search(self, query: str, limit: int) -> list[SearchResult]:
        """Search the registry for skills matching the query."""
        ...

    @abstractmethod
    async def get_skill_meta(self, slug: str) -> SkillMeta | None:
        """Retrieve metadata for a specific skill by slug."""
        ...

    @abstractmethod
    async def download_and_install(
        self, slug: str, version: str, target_dir: str,
    ) -> InstallResult:
        """Download and install a skill to target_dir."""
        ...


class RegistryManager:
    """Coordinates multiple skill registries with fan-out search."""

    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT) -> None:
        self._registries: list[SkillRegistry] = []
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def add_registry(self, registry: SkillRegistry) -> None:
        self._registries.append(registry)

    def get_registry(self, name: str) -> SkillRegistry | None:
        for r in self._registries:
            if r.name() == name:
                return r
        return None

    async def search_all(self, query: str, limit: int) -> list[SearchResult]:
        """Fan-out search to all registries, merge by score descending, clamp to limit."""
        if not self._registries:
            return []

        async def _search_one(reg: SkillRegistry) -> list[SearchResult]:
            async with self._semaphore:
                try:
                    return await asyncio.wait_for(reg.search(query, limit), timeout=60.0)
                except Exception as e:
                    logger.warning("Registry search failed: registry=%s error=%s", reg.name(), e)
                    return []

        tasks = [_search_one(r) for r in self._registries]
        results_lists = await asyncio.gather(*tasks)

        merged: list[SearchResult] = []
        for results in results_lists:
            merged.extend(results)

        # Sort by score descending.
        merged.sort(key=lambda r: r.score, reverse=True)

        if limit > 0 and len(merged) > limit:
            merged = merged[:limit]

        return merged
