"""ClawHub registry client — implements SkillRegistry for clawhub.ai."""

from __future__ import annotations

import io
import logging
import os
import tempfile
import zipfile
from urllib.parse import quote as url_quote, urlencode

import httpx

from pyclaw.skills.models import InstallResult, SearchResult, SkillMeta
from pyclaw.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0  # seconds
DEFAULT_MAX_ZIP_SIZE = 50 * 1024 * 1024  # 50 MB
DEFAULT_MAX_RESPONSE_SIZE = 2 * 1024 * 1024  # 2 MB


class ClawHubConfig:
    """Configuration for the ClawHub registry."""

    def __init__(
        self,
        base_url: str = "https://clawhub.ai",
        auth_token: str = "",
        search_path: str = "/api/v1/search",
        skills_path: str = "/api/v1/skills",
        download_path: str = "/api/v1/download",
        timeout: float = DEFAULT_TIMEOUT,
        max_zip_size: int = DEFAULT_MAX_ZIP_SIZE,
        max_response_size: int = DEFAULT_MAX_RESPONSE_SIZE,
    ) -> None:
        self.base_url = base_url
        self.auth_token = auth_token
        self.search_path = search_path
        self.skills_path = skills_path
        self.download_path = download_path
        self.timeout = timeout
        self.max_zip_size = max_zip_size
        self.max_response_size = max_response_size


class ClawHubRegistry(SkillRegistry):
    """SkillRegistry implementation for the ClawHub platform."""

    def __init__(self, config: ClawHubConfig | None = None) -> None:
        cfg = config or ClawHubConfig()
        self._base_url = cfg.base_url.rstrip("/")
        self._auth_token = cfg.auth_token
        self._search_path = cfg.search_path
        self._skills_path = cfg.skills_path
        self._download_path = cfg.download_path
        self._max_zip_size = cfg.max_zip_size
        self._max_response_size = cfg.max_response_size
        self._client = httpx.AsyncClient(
            timeout=cfg.timeout,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=5),
        )

    def name(self) -> str:
        return "clawhub"

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        return headers

    async def _do_get(self, url: str) -> bytes:
        """GET with response-size cap."""
        resp = await self._client.get(url, headers=self._headers())
        resp.raise_for_status()
        body = resp.content
        if len(body) > self._max_response_size:
            raise ValueError(f"Response exceeds {self._max_response_size} byte limit")
        return body

    # --- Search ---

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        params = {"q": query}
        if limit > 0:
            params["limit"] = str(limit)
        url = f"{self._base_url}{self._search_path}?{urlencode(params)}"

        body = await self._do_get(url)
        import json

        data = json.loads(body)

        results: list[SearchResult] = []
        for r in data.get("results", []):
            slug = r.get("slug", "")
            summary = r.get("summary", "")
            if not slug or not summary:
                continue
            results.append(SearchResult(
                score=r.get("score", 0.0),
                slug=slug,
                display_name=r.get("displayName", slug),
                summary=summary,
                version=r.get("version", ""),
                registry_name=self.name(),
            ))
        return results

    # --- GetSkillMeta ---

    async def get_skill_meta(self, slug: str) -> SkillMeta | None:
        url = f"{self._base_url}{self._skills_path}/{url_quote(slug, safe='')}"
        body = await self._do_get(url)
        import json

        data = json.loads(body)

        meta = SkillMeta(
            slug=data.get("slug", ""),
            display_name=data.get("displayName", ""),
            summary=data.get("summary", ""),
            registry_name=self.name(),
        )
        latest = data.get("latestVersion")
        if isinstance(latest, dict):
            meta.latest_version = latest.get("version", "")
        moderation = data.get("moderation")
        if isinstance(moderation, dict):
            meta.is_malware_blocked = moderation.get("isMalwareBlocked", False)
            meta.is_suspicious = moderation.get("isSuspicious", False)
        return meta

    # --- DownloadAndInstall ---

    async def download_and_install(
        self, slug: str, version: str, target_dir: str,
    ) -> InstallResult:
        result = InstallResult()

        # Step 1: Fetch metadata (with fallback).
        try:
            meta = await self.get_skill_meta(slug)
        except Exception:
            meta = None

        if meta:
            result.is_malware_blocked = meta.is_malware_blocked
            result.is_suspicious = meta.is_suspicious
            result.summary = meta.summary

        # Step 2: Resolve version.
        install_version = version
        if not install_version and meta:
            install_version = meta.latest_version
        if not install_version:
            install_version = "latest"
        result.version = install_version

        # Step 3: Download ZIP.
        params: dict[str, str] = {"slug": slug}
        if install_version != "latest":
            params["version"] = install_version
        url = f"{self._base_url}{self._download_path}?{urlencode(params)}"

        headers: dict[str, str] = {}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        async with self._client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > self._max_zip_size:
                    raise ValueError(f"ZIP exceeds {self._max_zip_size} byte limit")
                chunks.append(chunk)

        zip_data = b"".join(chunks)

        # Step 4: Extract ZIP to target_dir.
        os.makedirs(target_dir, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            zf.extractall(target_dir)

        return result
