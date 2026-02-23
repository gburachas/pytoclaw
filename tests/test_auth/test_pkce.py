"""Tests for PKCE utilities."""

import base64
import hashlib

from pytoclaw.auth.pkce import generate_pkce


def test_pkce_generates_different_values():
    v1, c1 = generate_pkce()
    v2, c2 = generate_pkce()
    assert v1 != v2
    assert c1 != c2


def test_pkce_challenge_matches_verifier():
    verifier, challenge = generate_pkce()
    # Recompute challenge from verifier
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    assert challenge == expected


def test_pkce_verifier_length():
    verifier, _ = generate_pkce()
    # 32 bytes → 43 chars in base64url (no padding)
    assert len(verifier) == 43


def test_pkce_no_padding_chars():
    verifier, challenge = generate_pkce()
    assert "=" not in verifier
    assert "=" not in challenge
