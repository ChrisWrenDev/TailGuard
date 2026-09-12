"""FastAPI application with authentication routes and Jinja2 templates."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from tailhedge.config import Settings
from tailhedge.web.auth import (
    _SESSION_COOKIE,
    create_session_cookie,
    generate_csrf_token,
    generate_session_id,
    require_auth,
    require_csrf,
)

app = FastAPI(title="TailHedge", version="0.1.0")

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


def _get_settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# Health endpoints (no auth)
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    # TODO: check database connectivity
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


@app.get("/auth/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    csrf_token = generate_csrf_token("login-form")
    context = {
        "request": request,
        "csrf_token": csrf_token,
        "error": None,
    }
    return templates.TemplateResponse(request, "login.html", context)


@app.post("/auth/login", response_model=None)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse | HTMLResponse:
    # TODO: look up user in database; for now reject all logins
    # This will be wired up properly when database auth is complete.
    settings = _get_settings()

    # For demonstration: accept owner/owner
    if username == "owner" and password == "owner":
        session_id = generate_session_id()
        _, cookie_value = create_session_cookie(
            session_id, settings.session_max_age_seconds
        )
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            _SESSION_COOKIE,
            cookie_value,
            max_age=settings.session_max_age_seconds,
            httponly=True,
            samesite=str(settings.session_cookie_samesite),  # type: ignore[arg-type]
            secure=settings.session_cookie_secure,
        )
        return response

    csrf_token = generate_csrf_token("login-form")
    context: dict[str, object] = {
        "request": request,
        "csrf_token": csrf_token,
        "error": "Invalid username or password.",
    }
    return templates.TemplateResponse(request, "login.html", context, status_code=401)


@app.post("/auth/logout")
async def logout(
    _session_id: Annotated[str, Depends(require_auth)],
) -> RedirectResponse:
    response = RedirectResponse(
        url="/auth/login", status_code=status.HTTP_303_SEE_OTHER
    )
    response.delete_cookie(_SESSION_COOKIE)
    return response


# ---------------------------------------------------------------------------
# Protected page routes (require auth)
# ---------------------------------------------------------------------------


def _page_context(request: Request, active_page: str, **kwargs: object) -> dict[str, object]:
    """Build standard template context for a page."""
    ctx: dict[str, object] = {
        "request": request,
        "active_page": active_page,
        "mode": "RESEARCH_ONLY",
        "broker_status": "Not connected",
        "kill_switch": "Disengaged",
    }
    ctx.update(kwargs)
    return ctx


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    _session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "dashboard.html", _page_context(request, "dashboard")
    )


@app.get("/portfolio", response_class=HTMLResponse)
async def portfolio_page(
    request: Request,
    _session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "portfolio.html", _page_context(request, "portfolio")
    )


@app.get("/research/campaigns", response_class=HTMLResponse)
async def research_campaigns(
    request: Request,
    _session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "research-campaigns.html", _page_context(request, "research")
    )


@app.get("/research/experiments", response_class=HTMLResponse)
async def research_experiments(
    request: Request,
    _session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "research-experiments.html", _page_context(request, "research")
    )


@app.get("/research/releases", response_class=HTMLResponse)
async def research_releases(
    request: Request,
    _session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "research-releases.html", _page_context(request, "research")
    )


@app.get("/operations/daily-runs", response_class=HTMLResponse)
async def operations_daily_runs(
    request: Request,
    _session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "operations-daily-runs.html", _page_context(request, "operations")
    )


@app.get("/operations/orders", response_class=HTMLResponse)
async def operations_orders(
    request: Request,
    _session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "operations-orders.html", _page_context(request, "operations")
    )


@app.get("/operations/broker-health", response_class=HTMLResponse)
async def operations_broker_health(
    request: Request,
    _session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "operations-broker-health.html", _page_context(request, "operations")
    )


@app.get("/data", response_class=HTMLResponse)
async def data_page(
    request: Request,
    _session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "data.html", _page_context(request, "data")
    )


@app.get("/audit-log", response_class=HTMLResponse)
async def audit_log_page(
    request: Request,
    _session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "audit-log.html", _page_context(request, "audit-log")
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    _session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "settings.html", _page_context(request, "settings")
    )


@app.get("/settings/risk-controls", response_class=HTMLResponse)
async def settings_risk_controls(
    request: Request,
    _session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "settings-risk-controls.html", _page_context(request, "settings")
    )


@app.get("/settings/schedule", response_class=HTMLResponse)
async def settings_schedule(
    request: Request,
    _session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "settings-schedule.html", _page_context(request, "settings")
    )


@app.get("/settings/integrations", response_class=HTMLResponse)
async def settings_integrations(
    request: Request,
    _session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "settings-integrations.html", _page_context(request, "settings")
    )


@app.get("/settings/notifications", response_class=HTMLResponse)
async def settings_notifications(
    request: Request,
    _session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "settings-notifications.html", _page_context(request, "settings")
    )


# ---------------------------------------------------------------------------
# Protected API routes
# ---------------------------------------------------------------------------


@app.get("/api/v1/status")
async def api_status(
    session_id: Annotated[str, Depends(require_auth)],
) -> dict[str, str]:
    return {"status": "authenticated", "session": session_id}


@app.post("/api/v1/example")
async def api_example(
    session_id: Annotated[str, Depends(require_csrf)],
) -> dict[str, str]:
    return {"status": "csrf_validated", "session": session_id}
