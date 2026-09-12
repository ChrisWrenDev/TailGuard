"""Authentication, session management, and CSRF protection."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status

from tailhedge.config import Secrets

_ph = PasswordHasher()

# ---------------------------------------------------------------------------
# Password hashing (Argon2id)
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Return an Argon2id hash of the password."""
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return True if password matches the hash."""
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


# ---------------------------------------------------------------------------
# Session management (signed cookie-based)
# ---------------------------------------------------------------------------

_SESSION_COOKIE = "tailhedge_session"
_CSRF_HEADER = "x-csrf-token"


def _get_session_secret() -> str:
    secrets_obj = Secrets()
    return secrets_obj.session_secret.get_secret_value()


def _sign_session(session_id: str, expires_at: int) -> str:
    """Return an HMAC signature for the session cookie value."""
    secret = _get_session_secret()
    payload = f"{session_id}:{expires_at}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_session_cookie(session_id: str, max_age: int) -> tuple[str, str]:
    """Return (cookie_value, set-cookie-header) for a new session."""
    expires_at = int(time.time() + max_age)
    sig = _sign_session(session_id, expires_at)
    value = f"{session_id}:{expires_at}:{sig}"
    return session_id, value


def _parse_session_value(value: str) -> tuple[str, float, str] | None:
    """Parse 'session_id:expires_at:signature' or return None."""
    parts = value.split(":", 2)
    if len(parts) != 3:
        return None
    try:
        session_id = parts[0]
        expires_at = float(parts[1])
        sig = parts[2]
    except (ValueError, IndexError):
        return None
    return session_id, expires_at, sig


def validate_session(value: str) -> str | None:
    """Return the session_id if valid and not expired, else None."""
    parsed = _parse_session_value(value)
    if parsed is None:
        return None
    session_id, expires_at, sig = parsed
    if time.time() > expires_at:
        return None
    expected = _sign_session(session_id, int(expires_at))
    if not hmac.compare_digest(sig, expected):
        return None
    return session_id


def generate_session_id() -> str:
    """Generate a cryptographically random session ID."""
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# CSRF protection
# ---------------------------------------------------------------------------


def generate_csrf_token(session_id: str) -> str:
    """Generate a CSRF token bound to the session."""
    secret = _get_session_secret()
    payload = f"csrf:{session_id}:{int(time.time())}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def validate_csrf_token(session_id: str, token: str) -> bool:
    """Validate a CSRF token (allows 1-hour window)."""
    secret = _get_session_secret()
    now = int(time.time())
    # Check current and previous hour to avoid edge issues
    for offset in (0, 1):
        ts = now - offset * 3600
        payload = f"csrf:{session_id}:{ts}"
        expected = hmac.new(
            secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()[:32]
        if hmac.compare_digest(token, expected):
            return True
    return False


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


async def get_current_session_id(
    request: Request,
) -> str:
    """Extract and validate the session ID from the cookie.

    Raises HTTP 303 redirect to /auth/login if invalid.
    """
    session_cookie = request.cookies.get(_SESSION_COOKIE)
    if session_cookie is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"},
        )
    session_id = validate_session(session_cookie)
    if session_id is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"},
        )
    return session_id


async def require_csrf(
    request: Request,
    session_id: Annotated[str, Depends(get_current_session_id)],
) -> str:
    """Require a valid CSRF token for state-changing requests.

    Accepts the token from header or form body.
    """
    token: str | None = request.headers.get(_CSRF_HEADER)
    if token is None and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        form = await request.form()
        token = form.get("csrf_token")  # type: ignore[assignment]
    if not token or not validate_csrf_token(session_id, token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token.",
        )
    return session_id


def require_auth(
    session_id: Annotated[str, Depends(get_current_session_id)],
) -> str:
    """Simple dependency requiring a valid session."""
    return session_id
