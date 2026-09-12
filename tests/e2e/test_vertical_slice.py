"""E2E vertical-slice test (TASK-014): owner runs and views a synthetic backtest.

Drives a real browser against a live server: unauthenticated access is
redirected to login, the authenticated owner sees the empty state, clicks
"Run synthetic backtest", and sees actual computed metric values in the
text table (no chart hover, no em-dash placeholders).
"""

from __future__ import annotations

import socket
import threading
import time
import urllib.request

import pytest

pytest.importorskip("playwright")

import uvicorn
from playwright.sync_api import expect, sync_playwright

from tailhedge.web.app import app
from tailhedge.web.auth import (
    _SESSION_COOKIE,
    create_session_cookie,
    generate_session_id,
)

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def server_url() -> str:
    """Start a live uvicorn server on a random port for the module."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{url}/healthz", timeout=1)
                break
            except Exception:
                time.sleep(0.1)
        else:
            pytest.fail("server did not become healthy")
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _authed_context(browser: object, server_url: str) -> object:
    """Browser context with a forged valid session cookie."""
    session_id = generate_session_id()
    cookie_value = create_session_cookie(session_id, max_age=3600)
    context = browser.new_context()
    context.add_cookies(
        [{"name": _SESSION_COOKIE, "value": cookie_value, "url": server_url}]
    )
    return context


def test_unauthenticated_redirects_to_login(server_url: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{server_url}/research/backtest")
        expect(page).to_have_url(f"{server_url}/auth/login")
        assert "Sign in to your account" in page.content()
        browser.close()


def test_owner_runs_and_views_synthetic_backtest(server_url: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = _authed_context(browser, server_url)
        page = context.new_page()

        # Empty state before any run
        page.goto(f"{server_url}/research/backtest")
        expect(page.get_by_text("No backtest results yet")).to_be_visible()

        # Run the synthetic backtest via the form (server-side CSRF included)
        page.get_by_role("button", name="Run synthetic backtest").click()

        # Real numbers render in the text table — accessible without hover
        page.wait_for_selector('[data-testid="hedged-cagr"]')
        hedged_cagr = page.inner_text('[data-testid="hedged-cagr"]')
        assert hedged_cagr.strip() != "—"
        assert "%" in hedged_cagr

        hedged_dd = page.inner_text('[data-testid="hedged-drawdown"]')
        assert hedged_dd.strip() != "—"

        premium = page.inner_text('[data-testid="premium-spend"]')
        assert "$" in premium

        # Baseline comparison lists all three baselines with numeric cells
        baseline_rows = page.locator('[data-testid="baseline-row"]')
        expect(baseline_rows).to_have_count(3)
        for i in range(3):
            row_text = baseline_rows.nth(i).inner_text()
            assert "No Hedge" in row_text or "Equity" in row_text or "PPUT" in row_text

        # Empty state no longer displayed
        assert "No backtest results yet" not in page.content()
        browser.close()
