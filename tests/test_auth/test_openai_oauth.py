"""Tests for OpenAI OAuth utilities."""

from pytoclaw.auth.openai_oauth import (
    _decode_jwt_payload,
    _extract_account_id,
    _parse_auth_input,
)

import base64
import json


def _make_jwt(payload: dict) -> str:
    """Create a fake JWT for testing."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(b"fake_sig").rstrip(b"=").decode()
    return f"{header}.{body}.{sig}"


def test_decode_jwt_payload():
    token = _make_jwt({"sub": "user123", "email": "test@test.com"})
    payload = _decode_jwt_payload(token)
    assert payload is not None
    assert payload["sub"] == "user123"


def test_decode_jwt_invalid():
    assert _decode_jwt_payload("not.a.valid.jwt") is None
    assert _decode_jwt_payload("") is None


def test_extract_account_id():
    token = _make_jwt({
        "https://api.openai.com/auth": {
            "chatgpt_account_id": "acc_abc123"
        }
    })
    assert _extract_account_id(token) == "acc_abc123"


def test_extract_account_id_missing():
    token = _make_jwt({"sub": "user123"})
    assert _extract_account_id(token) is None


def test_parse_auth_input_url():
    state = "abc123"
    url = f"http://localhost:1455/auth/callback?code=mycode&state={state}"
    code = _parse_auth_input(url, state)
    assert code == "mycode"


def test_parse_auth_input_state_mismatch():
    code = _parse_auth_input("http://localhost/callback?code=x&state=wrong", "expected")
    assert code is None


def test_parse_auth_input_raw_code():
    code = _parse_auth_input("myrawcode", "anystate")
    assert code == "myrawcode"


def test_parse_auth_input_code_hash_state():
    code = _parse_auth_input("mycode#mystate", "mystate")
    assert code == "mycode"


def test_parse_auth_input_empty():
    assert _parse_auth_input("", "state") is None
