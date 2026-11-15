"""Credential helpers: constant-time comparison, PIN hashing and log redaction."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Any

SENSITIVE_KEYS = {
    "access_code", "pin", "password", "passcode", "otp", "token", "api_key", "api_token",
    "authorization", "secret", "x-admin-key",
}
REDACTED = "[REDACTED]"
# Free-text fields are stored in the audit trail only as a length, never verbatim.
FREE_TEXT_KEYS = {"body", "notes", "content"}


def new_salt() -> str:
    return secrets.token_hex(16)


def hash_pin(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 120_000).hex()


def verify_pin(pin: str, salt: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_pin(pin, salt), expected_hash)


def keys_equal(provided: str | None, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


def normalise_code(value: Any) -> str:
    """Keep only digits from a spoken access code ("4 8 2-9 1 6" -> "482916")."""
    return re.sub(r"\D", "", str(value or ""))


def redact(value: Any) -> Any:
    """Recursively redact secrets and bulky free text before logging/auditing."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            key = str(k).lower()
            if key in SENSITIVE_KEYS:
                out[k] = REDACTED
            elif key in FREE_TEXT_KEYS and isinstance(v, str):
                out[k] = f"[{len(v)} chars]"
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str) and len(value) > 300:
        return value[:300] + "…"
    return value
