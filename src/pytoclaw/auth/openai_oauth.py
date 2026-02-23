"""OpenAI Codex OAuth — browser-based login for ChatGPT Pro/Plus accounts.

Ported from OpenClaw's openai-codex-oauth flow. Uses PKCE authorization code
flow with a localhost callback server on port 1455.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
import webbrowser
from dataclasses import dataclass
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from typing import Any
from urllib.parse import urlencode, urlparse, parse_qs

import httpx

from pytoclaw.auth.pkce import generate_pkce

logger = logging.getLogger(__name__)

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
REDIRECT_URI = "http://localhost:1455/auth/callback"
SCOPE = "openid profile email offline_access"
JWT_CLAIM_PATH = "https://api.openai.com/auth"

SUCCESS_HTML = b"""<!doctype html>
<html><head><title>Authentication successful</title></head>
<body><p>Authentication successful. Return to your terminal to continue.</p></body>
</html>"""


@dataclass
class OAuthCredentials:
    access_token: str
    refresh_token: str
    expires_at: float  # epoch seconds
    account_id: str


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    """Decode JWT payload without verification (we only need the account ID)."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        # Add padding
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return None


def _extract_account_id(access_token: str) -> str | None:
    payload = _decode_jwt_payload(access_token)
    if payload is None:
        return None
    auth = payload.get(JWT_CLAIM_PATH)
    if isinstance(auth, dict):
        account_id = auth.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id:
            return account_id
    return None


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler that captures the OAuth callback code."""

    code: str | None = None
    expected_state: str = ""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/auth/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        params = parse_qs(parsed.query)
        state = params.get("state", [""])[0]
        if state != self.expected_state:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"State mismatch")
            return

        code = params.get("code", [""])[0]
        if not code:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing authorization code")
            return

        _OAuthCallbackHandler.code = code
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(SUCCESS_HTML)

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default HTTP server logging
        pass


async def _exchange_code(code: str, verifier: str) -> dict[str, Any] | None:
    """Exchange authorization code for tokens."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            logger.error("Token exchange failed: %s %s", resp.status_code, resp.text)
            return None
        return resp.json()


async def refresh_token(refresh: str) -> OAuthCredentials | None:
    """Refresh an OAuth access token."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": CLIENT_ID,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            logger.error("Token refresh failed: %s %s", resp.status_code, resp.text)
            return None

        data = resp.json()
        access = data.get("access_token")
        new_refresh = data.get("refresh_token")
        expires_in = data.get("expires_in", 3600)

        if not access or not new_refresh:
            return None

        account_id = _extract_account_id(access)
        if not account_id:
            return None

        import time
        return OAuthCredentials(
            access_token=access,
            refresh_token=new_refresh,
            expires_at=time.time() + expires_in,
            account_id=account_id,
        )


async def login_openai_oauth(manual_mode: bool = False) -> OAuthCredentials | None:
    """Run the OpenAI Codex OAuth login flow.

    Args:
        manual_mode: If True, print the URL for manual opening instead of
                     launching a browser (for SSH/headless environments).

    Returns:
        OAuthCredentials on success, None on failure.
    """
    import time

    verifier, challenge = generate_pkce()
    state = secrets.token_hex(16)

    # Build authorization URL
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": "pytoclaw",
    }
    auth_url = f"{AUTHORIZE_URL}?{urlencode(params)}"

    # Set up callback server
    _OAuthCallbackHandler.code = None
    _OAuthCallbackHandler.expected_state = state

    try:
        server = HTTPServer(("127.0.0.1", 1455), _OAuthCallbackHandler)
    except OSError as e:
        logger.error("Failed to bind port 1455: %s", e)
        logger.info("Falling back to manual mode")
        manual_mode = True
        server = None

    code = None

    if server:
        server_thread = Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

    try:
        if manual_mode:
            print(f"\nOpen this URL in your browser:\n\n{auth_url}\n")
            code_input = input("Paste the redirect URL or authorization code: ").strip()
            code = _parse_auth_input(code_input, state)
        else:
            print("Opening browser for OpenAI authentication...")
            webbrowser.open(auth_url)

            # Wait for callback (up to 60 seconds)
            for _ in range(600):
                if _OAuthCallbackHandler.code:
                    code = _OAuthCallbackHandler.code
                    break
                await asyncio.sleep(0.1)

            if not code:
                # Fallback to manual paste
                print("\nBrowser callback not received.")
                code_input = input("Paste the redirect URL or authorization code: ").strip()
                code = _parse_auth_input(code_input, state)
    finally:
        if server:
            server.shutdown()

    if not code:
        logger.error("No authorization code received")
        return None

    # Exchange code for tokens
    token_data = await _exchange_code(code, verifier)
    if not token_data:
        return None

    access = token_data.get("access_token")
    refresh = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)

    if not access or not refresh:
        logger.error("Token response missing required fields")
        return None

    account_id = _extract_account_id(access)
    if not account_id:
        logger.error("Failed to extract accountId from token")
        return None

    return OAuthCredentials(
        access_token=access,
        refresh_token=refresh,
        expires_at=time.time() + expires_in,
        account_id=account_id,
    )


def _parse_auth_input(value: str, expected_state: str) -> str | None:
    """Parse user input that could be a URL, code, or code#state."""
    if not value:
        return None

    # Try as URL
    try:
        parsed = urlparse(value)
        params = parse_qs(parsed.query)
        state = params.get("state", [""])[0]
        if state and state != expected_state:
            logger.error("State mismatch")
            return None
        code = params.get("code", [""])[0]
        if code:
            return code
    except Exception:
        pass

    # Try as code#state
    if "#" in value:
        parts = value.split("#", 1)
        return parts[0]

    # Treat as raw code
    return value
