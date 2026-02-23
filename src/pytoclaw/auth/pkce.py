"""PKCE (Proof Key for Code Exchange) utilities."""

import base64
import hashlib
import secrets


def generate_pkce() -> tuple[str, str]:
    """Generate PKCE code verifier and challenge.

    Returns:
        (verifier, challenge) tuple.
    """
    verifier_bytes = secrets.token_bytes(32)
    verifier = _base64url_encode(verifier_bytes)

    challenge_bytes = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = _base64url_encode(challenge_bytes)

    return verifier, challenge


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
