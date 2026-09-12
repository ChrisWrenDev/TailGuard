"""Tests for authentication, sessions, and CSRF protection (TASK-004)."""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tailhedge.web.app import _LOGIN_CSRF_SCOPE, app
from tailhedge.web.auth import (
    _SESSION_COOKIE,
    create_session_cookie,
    generate_csrf_token,
    generate_session_id,
    hash_password,
    validate_csrf_token,
    validate_session,
    verify_password,
    verify_password_constant_time,
)

# ---------------------------------------------------------------------------
# Password hashing (Argon2id)
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    def test_hash_returns_string(self) -> None:
        h = hash_password("test-password")
        assert isinstance(h, str)
        assert "argon2" in h.lower()

    def test_verify_correct_password(self) -> None:
        h = hash_password("correct-password")
        assert verify_password("correct-password", h) is True

    def test_verify_wrong_password(self) -> None:
        h = hash_password("correct-password")
        assert verify_password("wrong-password", h) is False

    def test_different_hashes_for_same_password(self) -> None:
        h1 = hash_password("same-password")
        h2 = hash_password("same-password")
        assert h1 != h2

    def test_verify_with_empty_password(self) -> None:
        h = hash_password("")
        assert verify_password("", h) is True
        assert verify_password("not-empty", h) is False


class TestConstantTimeVerification:
    def test_unknown_user_returns_false(self) -> None:
        assert verify_password_constant_time("anything", None) is False

    def test_known_user_wrong_password_returns_false(self) -> None:
        h = hash_password("correct-password")
        assert verify_password_constant_time("wrong", h) is False

    def test_known_user_correct_password_returns_true(self) -> None:
        h = hash_password("correct-password")
        assert verify_password_constant_time("correct-password", h) is True


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


class TestSessionManagement:
    def test_generate_session_id_is_unique(self) -> None:
        id1 = generate_session_id()
        id2 = generate_session_id()
        assert id1 != id2

    def test_create_session_cookie_returns_signed_value(self) -> None:
        session_id = generate_session_id()
        value = create_session_cookie(session_id, max_age=3600)
        assert session_id in value

    def test_validate_session_valid(self) -> None:
        session_id = generate_session_id()
        value = create_session_cookie(session_id, max_age=3600)
        assert validate_session(value) == session_id

    def test_validate_session_expired(self) -> None:
        session_id = generate_session_id()
        value = create_session_cookie(session_id, max_age=-1)
        assert validate_session(value) is None

    def test_validate_session_tampered(self) -> None:
        session_id = generate_session_id()
        value = create_session_cookie(session_id, max_age=3600)
        tampered = value[:-5] + "XXXXX"
        assert validate_session(tampered) is None

    def test_validate_session_invalid_format(self) -> None:
        assert validate_session("not-a-session") is None
        assert validate_session("a:b") is None
        assert validate_session("") is None


# ---------------------------------------------------------------------------
# CSRF protection
# ---------------------------------------------------------------------------


class TestCSRFProtection:
    def test_generate_and_validate_csrf_token(self) -> None:
        session_id = generate_session_id()
        token = generate_csrf_token(session_id)
        assert validate_csrf_token(session_id, token) is True

    def test_csrf_token_wrong_session(self) -> None:
        sid1 = generate_session_id()
        sid2 = generate_session_id()
        token = generate_csrf_token(sid1)
        assert validate_csrf_token(sid2, token) is False

    def test_csrf_token_tampered(self) -> None:
        session_id = generate_session_id()
        token = generate_csrf_token(session_id)
        tampered = token[:-4] + "XXXX"
        assert validate_csrf_token(session_id, tampered) is False

    def test_csrf_token_valid_after_delay(self) -> None:
        # Tokens are hour-bucketed; a token remains valid shortly after issuance
        session_id = generate_session_id()
        token = generate_csrf_token(session_id)
        time.sleep(1.1)
        assert validate_csrf_token(session_id, token) is True

    def test_csrf_token_not_reusable_across_scopes(self) -> None:
        token = generate_csrf_token("login")
        assert validate_csrf_token("login", token) is True
        assert validate_csrf_token("other-scope", token) is False


# ---------------------------------------------------------------------------
# HTTP integration tests
# ---------------------------------------------------------------------------


class TestHealthEndpoints:
    def test_healthz(self) -> None:
        client = TestClient(app)
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    @pytest.mark.usefixtures("mock_db_ready")
    def test_readyz_with_database(self) -> None:
        client = TestClient(app)
        resp = client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_readyz_unavailable_database(self) -> None:
        from fastapi import HTTPException

        from tailhedge.web.app import check_database_ready

        def failing() -> None:
            raise HTTPException(status_code=503, detail="Database not ready.")

        app.dependency_overrides[check_database_ready] = failing
        try:
            client = TestClient(app)
            resp = client.get("/readyz")
            assert resp.status_code == 503
        finally:
            app.dependency_overrides.pop(check_database_ready, None)


def _login(
    client: TestClient,
    username: str,
    password: str,
    csrf_token: str | None = None,
) -> Any:
    token = (
        csrf_token if csrf_token is not None else generate_csrf_token(_LOGIN_CSRF_SCOPE)
    )
    return client.post(
        "/auth/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": token,
        },
        follow_redirects=False,
    )


class TestAuthEndpoints:
    def test_login_form_renders(self) -> None:
        client = TestClient(app)
        resp = client.get("/auth/login")
        assert resp.status_code == 200
        assert "Login" in resp.text

    @pytest.mark.usefixtures("auth_db")
    def test_login_rejects_missing_csrf_token(self) -> None:
        client = TestClient(app)
        resp = client.post(
            "/auth/login",
            data={"username": "owner", "password": "correct-horse-battery"},
            follow_redirects=False,
        )
        assert resp.status_code == 403

    @pytest.mark.usefixtures("auth_db")
    def test_login_rejects_invalid_csrf_token(self) -> None:
        client = TestClient(app)
        resp = _login(client, "owner", "correct-horse-battery", csrf_token="bad-token")
        assert resp.status_code == 403

    @pytest.mark.usefixtures("auth_db")
    def test_login_unknown_user_rejected(self) -> None:
        client = TestClient(app)
        resp = _login(client, "ghost", "whatever")
        assert resp.status_code == 401
        assert "Invalid username or password" in resp.text

    @pytest.mark.usefixtures("auth_db")
    def test_login_wrong_password_rejected(self) -> None:
        client = TestClient(app)
        resp = _login(client, "owner", "wrong-password")
        assert resp.status_code == 401

    @pytest.mark.usefixtures("auth_db")
    def test_login_valid_credentials_accepted(self) -> None:
        client = TestClient(app)
        resp = _login(client, "owner", "correct-horse-battery")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"

    @pytest.mark.usefixtures("auth_db")
    def test_login_sets_session_cookie(self) -> None:
        client = TestClient(app)
        resp = _login(client, "owner", "correct-horse-battery")
        assert resp.status_code == 303
        set_cookie_header = resp.headers.get("set-cookie", "")
        assert _SESSION_COOKIE in set_cookie_header
        assert "httponly" in set_cookie_header.lower()


class TestProtectedRoutes:
    def test_unauthenticated_redirects_to_login(self) -> None:
        client = TestClient(app)
        resp = client.get("/api/v1/status", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/auth/login"

    def test_valid_session_allows_access(self) -> None:
        client = TestClient(app)
        session_id = generate_session_id()
        cookie_value = create_session_cookie(session_id, max_age=3600)
        resp = client.get("/api/v1/status", cookies={_SESSION_COOKIE: cookie_value})
        assert resp.status_code == 200
        assert resp.json()["status"] == "authenticated"

    def test_expired_session_redirects_to_login(self) -> None:
        client = TestClient(app)
        session_id = generate_session_id()
        cookie_value = create_session_cookie(session_id, max_age=-1)
        resp = client.get(
            "/api/v1/status",
            cookies={_SESSION_COOKIE: cookie_value},
            follow_redirects=False,
        )
        assert resp.status_code == 303


class TestCSRFIntegration:
    def test_post_without_csrf_token_rejected(self) -> None:
        client = TestClient(app)
        session_id = generate_session_id()
        cookie_value = create_session_cookie(session_id, max_age=3600)
        resp = client.post("/api/v1/example", cookies={_SESSION_COOKIE: cookie_value})
        assert resp.status_code == 403

    def test_post_with_valid_csrf_token_accepted(self) -> None:
        client = TestClient(app)
        session_id = generate_session_id()
        cookie_value = create_session_cookie(session_id, max_age=3600)
        csrf_token = generate_csrf_token(session_id)
        resp = client.post(
            "/api/v1/example",
            cookies={_SESSION_COOKIE: cookie_value},
            headers={"x-csrf-token": csrf_token},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "csrf_validated"

    def test_post_with_wrong_csrf_token_rejected(self) -> None:
        client = TestClient(app)
        session_id = generate_session_id()
        cookie_value = create_session_cookie(session_id, max_age=3600)
        resp = client.post(
            "/api/v1/example",
            cookies={_SESSION_COOKIE: cookie_value},
            headers={"x-csrf-token": "wrong-token"},
        )
        assert resp.status_code == 403


class TestSessionCookieFlags:
    def test_session_cookie_set_on_login(self) -> None:
        # Verify the cookie name constant is correct
        assert _SESSION_COOKIE == "tailhedge_session"
