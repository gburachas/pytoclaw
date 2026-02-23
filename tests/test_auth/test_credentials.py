"""Tests for credential storage."""

import time
import pytest

from pytoclaw.auth.credentials import CredentialStore, StoredCredential
from pytoclaw.auth.openai_oauth import OAuthCredentials


def test_store_and_get_api_key(tmp_path):
    store = CredentialStore(str(tmp_path))
    store.store_api_key("openai", "sk-test-123")

    cred = store.get("openai")
    assert cred is not None
    assert cred.auth_type == "api_key"
    assert cred.get_api_key() == "sk-test-123"


def test_store_and_get_oauth(tmp_path):
    store = CredentialStore(str(tmp_path))
    creds = OAuthCredentials(
        access_token="eyJ...",
        refresh_token="rt_...",
        expires_at=time.time() + 3600,
        account_id="acc_123",
    )
    store.store_oauth("openai-codex", creds)

    cred = store.get("openai-codex")
    assert cred is not None
    assert cred.auth_type == "oauth"
    assert cred.access_token == "eyJ..."
    assert cred.account_id == "acc_123"


def test_persistence(tmp_path):
    store1 = CredentialStore(str(tmp_path))
    store1.store_api_key("test", "key123")

    store2 = CredentialStore(str(tmp_path))
    assert store2.get("test") is not None
    assert store2.get("test").get_api_key() == "key123"


def test_remove(tmp_path):
    store = CredentialStore(str(tmp_path))
    store.store_api_key("test", "key")
    assert store.remove("test") is True
    assert store.get("test") is None


def test_is_expired():
    cred = StoredCredential(
        auth_type="oauth",
        provider="test",
        expires_at=time.time() - 100,
    )
    assert cred.is_expired() is True

    cred2 = StoredCredential(
        auth_type="oauth",
        provider="test",
        expires_at=time.time() + 3600,
    )
    assert cred2.is_expired() is False


def test_api_key_never_expires():
    cred = StoredCredential(auth_type="api_key", provider="test", api_key="sk-123")
    assert cred.is_expired() is False


def test_list_providers(tmp_path):
    store = CredentialStore(str(tmp_path))
    store.store_api_key("openai", "key1")
    store.store_api_key("anthropic", "key2")
    providers = store.list_providers()
    assert set(providers) == {"openai", "anthropic"}
