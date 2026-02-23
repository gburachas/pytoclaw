"""Credential storage — manages OAuth tokens and API keys on disk."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from pytoclaw.auth.openai_oauth import OAuthCredentials, refresh_token

logger = logging.getLogger(__name__)


@dataclass
class StoredCredential:
    auth_type: str  # "api_key" | "oauth"
    provider: str
    api_key: str = ""
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0
    account_id: str = ""

    def is_expired(self, buffer_seconds: int = 300) -> bool:
        if self.auth_type != "oauth":
            return False
        return time.time() >= (self.expires_at - buffer_seconds)

    def get_api_key(self) -> str:
        """Return the usable API key/token."""
        if self.auth_type == "api_key":
            return self.api_key
        return self.access_token


class CredentialStore:
    """Manages credential storage at ~/.pytoclaw/credentials.json."""

    def __init__(self, config_dir: str | None = None) -> None:
        self._config_dir = config_dir or str(Path.home() / ".pytoclaw")
        self._cred_file = os.path.join(self._config_dir, "credentials.json")
        self._credentials: dict[str, StoredCredential] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.isfile(self._cred_file):
            return
        try:
            with open(self._cred_file) as f:
                data = json.load(f)
            for key, val in data.items():
                self._credentials[key] = StoredCredential(**val)
        except (json.JSONDecodeError, TypeError, KeyError):
            logger.warning("Failed to load credentials, starting fresh")

    def _save(self) -> None:
        os.makedirs(self._config_dir, exist_ok=True)
        data = {k: asdict(v) for k, v in self._credentials.items()}
        tmp = self._cred_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self._cred_file)
        # Secure file permissions
        try:
            os.chmod(self._cred_file, 0o600)
        except OSError:
            pass

    def store_api_key(self, provider: str, api_key: str) -> None:
        self._credentials[provider] = StoredCredential(
            auth_type="api_key",
            provider=provider,
            api_key=api_key,
        )
        self._save()

    def store_oauth(self, provider: str, creds: OAuthCredentials) -> None:
        self._credentials[provider] = StoredCredential(
            auth_type="oauth",
            provider=provider,
            access_token=creds.access_token,
            refresh_token=creds.refresh_token,
            expires_at=creds.expires_at,
            account_id=creds.account_id,
        )
        self._save()

    def get(self, provider: str) -> StoredCredential | None:
        return self._credentials.get(provider)

    async def get_valid_token(self, provider: str) -> str | None:
        """Get a valid API key/token, refreshing OAuth if needed."""
        cred = self._credentials.get(provider)
        if cred is None:
            return None

        if cred.auth_type == "api_key":
            return cred.api_key

        # OAuth — check expiry
        if not cred.is_expired():
            return cred.access_token

        # Refresh
        logger.info("Refreshing OAuth token for %s", provider)
        new_creds = await refresh_token(cred.refresh_token)
        if new_creds is None:
            logger.error("Failed to refresh token for %s", provider)
            return None

        self.store_oauth(provider, new_creds)
        return new_creds.access_token

    def remove(self, provider: str) -> bool:
        if provider in self._credentials:
            del self._credentials[provider]
            self._save()
            return True
        return False

    def list_providers(self) -> list[str]:
        return list(self._credentials.keys())
