"""Tests for the web application shell, navigation, and page rendering (TASK-006)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tailhedge.web.app import app
from tailhedge.web.auth import (
    _SESSION_COOKIE,
    create_session_cookie,
    generate_session_id,
)

client = TestClient(app)


def _auth_client() -> TestClient:
    """Return a test client with a valid session cookie."""
    session_id = generate_session_id()
    _, cookie_value = create_session_cookie(session_id, max_age=3600)
    return TestClient(app, cookies={_SESSION_COOKIE: cookie_value})


def _unauth_client() -> TestClient:
    """Return a test client without authentication."""
    return TestClient(app, follow_redirects=False)


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------


class TestHealthEndpoints:
    def test_healthz_returns_ok(self) -> None:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_readyz_returns_ok(self) -> None:
        resp = client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Login page
# ---------------------------------------------------------------------------


class TestLoginPage:
    def test_login_page_renders(self) -> None:
        resp = client.get("/auth/login")
        assert resp.status_code == 200
        assert "TailHedge" in resp.text
        assert "Sign in to your account" in resp.text

    def test_login_page_has_accessible_form(self) -> None:
        resp = client.get("/auth/login")
        assert resp.status_code == 200
        assert 'for="username"' in resp.text
        assert 'for="password"' in resp.text
        assert 'type="password"' in resp.text
        assert 'type="submit"' in resp.text

    def test_login_page_has_csrf_token(self) -> None:
        resp = client.get("/auth/login")
        assert resp.status_code == 200
        assert 'name="csrf_token"' in resp.text

    def test_login_rejects_invalid_credentials(self) -> None:
        resp = client.post(
            "/auth/login",
            data={"username": "wrong", "password": "wrong"},
            follow_redirects=False,
        )
        assert resp.status_code == 401
        assert "Invalid username or password" in resp.text

    def test_login_accepts_valid_credentials(self) -> None:
        resp = client.post(
            "/auth/login",
            data={"username": "owner", "password": "owner"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"

    def test_login_sets_session_cookie(self) -> None:
        resp = client.post(
            "/auth/login",
            data={"username": "owner", "password": "owner"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        # Verify Set-Cookie header is present in response
        set_cookie_header = resp.headers.get("set-cookie", "")
        assert _SESSION_COOKIE in set_cookie_header


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


class TestLogout:
    def test_logout_redirects_to_login(self) -> None:
        auth = _auth_client()
        resp = auth.post(
            "/auth/logout",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/auth/login"


# ---------------------------------------------------------------------------
# Protected page routing
# ---------------------------------------------------------------------------


class TestProtectedPagesRedirect:
    """Unauthenticated requests to protected pages redirect to login."""

    def test_root_redirects(self) -> None:
        resp = _unauth_client().get("/")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/auth/login"

    def test_portfolio_redirects(self) -> None:
        resp = _unauth_client().get("/portfolio")
        assert resp.status_code == 303

    def test_research_campaigns_redirects(self) -> None:
        resp = _unauth_client().get("/research/campaigns")
        assert resp.status_code == 303

    def test_data_redirects(self) -> None:
        resp = _unauth_client().get("/data")
        assert resp.status_code == 303

    def test_audit_log_redirects(self) -> None:
        resp = _unauth_client().get("/audit-log")
        assert resp.status_code == 303

    def test_settings_redirects(self) -> None:
        resp = _unauth_client().get("/settings")
        assert resp.status_code == 303


# ---------------------------------------------------------------------------
# Authenticated page rendering
# ---------------------------------------------------------------------------


class TestDashboardPage:
    def test_dashboard_renders(self) -> None:
        auth = _auth_client()
        resp = auth.get("/")
        assert resp.status_code == 200
        assert "Dashboard" in resp.text
        assert "Welcome to TailHedge" in resp.text

    def test_dashboard_shows_empty_state(self) -> None:
        auth = _auth_client()
        resp = auth.get("/")
        assert resp.status_code == 200
        assert "No portfolio or dataset configured" in resp.text


class TestPortfolioPage:
    def test_portfolio_renders(self) -> None:
        auth = _auth_client()
        resp = auth.get("/portfolio")
        assert resp.status_code == 200
        assert "Portfolio" in resp.text


class TestResearchPages:
    def test_campaigns_page_renders(self) -> None:
        auth = _auth_client()
        resp = auth.get("/research/campaigns")
        assert resp.status_code == 200
        assert "Campaigns" in resp.text
        assert "Create Campaign" in resp.text

    def test_experiments_page_renders(self) -> None:
        auth = _auth_client()
        resp = auth.get("/research/experiments")
        assert resp.status_code == 200
        assert "Experiments" in resp.text

    def test_releases_page_renders(self) -> None:
        auth = _auth_client()
        resp = auth.get("/research/releases")
        assert resp.status_code == 200
        assert "Candidates / Releases" in resp.text


class TestOperationsPages:
    def test_daily_runs_page_renders(self) -> None:
        auth = _auth_client()
        resp = auth.get("/operations/daily-runs")
        assert resp.status_code == 200
        assert "Daily Runs" in resp.text

    def test_orders_page_renders(self) -> None:
        auth = _auth_client()
        resp = auth.get("/operations/orders")
        assert resp.status_code == 200
        assert "Orders" in resp.text

    def test_broker_health_page_renders(self) -> None:
        auth = _auth_client()
        resp = auth.get("/operations/broker-health")
        assert resp.status_code == 200
        assert "Broker Health" in resp.text


class TestDataPage:
    def test_data_page_renders(self) -> None:
        auth = _auth_client()
        resp = auth.get("/data")
        assert resp.status_code == 200
        assert "Data" in resp.text
        assert "Import Dataset" in resp.text


class TestAuditLogPage:
    def test_audit_log_page_renders(self) -> None:
        auth = _auth_client()
        resp = auth.get("/audit-log")
        assert resp.status_code == 200
        assert "Audit Log" in resp.text


class TestSettingsPages:
    def test_settings_main_renders(self) -> None:
        auth = _auth_client()
        resp = auth.get("/settings")
        assert resp.status_code == 200
        assert "Settings" in resp.text

    def test_risk_controls_page_renders(self) -> None:
        auth = _auth_client()
        resp = auth.get("/settings/risk-controls")
        assert resp.status_code == 200
        assert "Risk Controls" in resp.text

    def test_schedule_page_renders(self) -> None:
        auth = _auth_client()
        resp = auth.get("/settings/schedule")
        assert resp.status_code == 200
        assert "Schedule" in resp.text

    def test_integrations_page_renders(self) -> None:
        auth = _auth_client()
        resp = auth.get("/settings/integrations")
        assert resp.status_code == 200
        assert "Integrations" in resp.text

    def test_notifications_page_renders(self) -> None:
        auth = _auth_client()
        resp = auth.get("/settings/notifications")
        assert resp.status_code == 200
        assert "Notifications" in resp.text


# ---------------------------------------------------------------------------
# Navigation structure
# ---------------------------------------------------------------------------


class TestNavigationStructure:
    """Verify that all pages include the navigation and status bar."""

    def test_navigation_present_on_dashboard(self) -> None:
        auth = _auth_client()
        resp = auth.get("/")
        assert resp.status_code == 200
        assert 'aria-label="Primary navigation"' in resp.text
        assert 'aria-label="System status"' in resp.text

    def test_all_navigation_links_present(self) -> None:
        auth = _auth_client()
        resp = auth.get("/")
        assert resp.status_code == 200
        # Check all main navigation items
        assert 'href="/"' in resp.text
        assert 'href="/portfolio"' in resp.text
        assert 'href="/research/campaigns"' in resp.text
        assert 'href="/operations/daily-runs"' in resp.text
        assert 'href="/data"' in resp.text
        assert 'href="/audit-log"' in resp.text
        assert 'href="/settings"' in resp.text

    def test_active_page_highlighted(self) -> None:
        auth = _auth_client()
        resp = auth.get("/")
        assert resp.status_code == 200
        assert 'navigation__link--active' in resp.text
        assert 'aria-current="page"' in resp.text

    def test_status_bar_shows_mode(self) -> None:
        auth = _auth_client()
        resp = auth.get("/")
        assert resp.status_code == 200
        assert "Mode: RESEARCH_ONLY" in resp.text
        assert "Broker: Not connected" in resp.text
        assert "Kill Switch: Disengaged" in resp.text


# ---------------------------------------------------------------------------
# Accessibility
# ---------------------------------------------------------------------------


class TestAccessibility:
    """Verify accessibility baseline for all pages."""

    def test_html_lang_attribute(self) -> None:
        auth = _auth_client()
        resp = auth.get("/")
        assert resp.status_code == 200
        assert 'lang="en"' in resp.text

    def test_main_role_attribute(self) -> None:
        auth = _auth_client()
        resp = auth.get("/")
        assert resp.status_code == 200
        assert 'role="main"' in resp.text

    def test_navigation_role_attribute(self) -> None:
        auth = _auth_client()
        resp = auth.get("/")
        assert resp.status_code == 200
        assert 'role="navigation"' in resp.text

    def test_status_bar_role_attribute(self) -> None:
        auth = _auth_client()
        resp = auth.get("/")
        assert resp.status_code == 200
        assert 'role="banner"' in resp.text

    def test_empty_state_role_attribute(self) -> None:
        auth = _auth_client()
        resp = auth.get("/")
        assert resp.status_code == 200
        assert 'role="status"' in resp.text

    def test_login_page_has_accessible_labels(self) -> None:
        resp = client.get("/auth/login")
        assert resp.status_code == 200
        assert 'for="username"' in resp.text
        assert 'for="password"' in resp.text
        assert 'autocomplete="username"' in resp.text
        assert 'autocomplete="current-password"' in resp.text

    def test_sub_navigation_aria_labels(self) -> None:
        auth = _auth_client()
        resp = auth.get("/research/campaigns")
        assert resp.status_code == 200
        assert 'aria-label="Research sub-navigation"' in resp.text

    def test_settings_sub_navigation_aria_labels(self) -> None:
        auth = _auth_client()
        resp = auth.get("/settings/risk-controls")
        assert resp.status_code == 200
        assert 'aria-label="Settings sub-navigation"' in resp.text


# ---------------------------------------------------------------------------
# Static assets
# ---------------------------------------------------------------------------


class TestStaticAssets:
    def test_css_stylesheet_accessible(self) -> None:
        resp = client.get("/static/css/style.css")
        assert resp.status_code == 200
        assert "TailHedge" in resp.text

    def test_htmx_script_accessible(self) -> None:
        auth = _auth_client()
        resp = auth.get("/")
        assert resp.status_code == 200
        assert "htmx.org" in resp.text


# ---------------------------------------------------------------------------
# Logout button
# ---------------------------------------------------------------------------


class TestLogoutButton:
    def test_logout_button_present_on_pages(self) -> None:
        auth = _auth_client()
        resp = auth.get("/")
        assert resp.status_code == 200
        assert 'action="/auth/logout"' in resp.text
        assert "Logout" in resp.text
