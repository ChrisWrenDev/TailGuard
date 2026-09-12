"""FastAPI application with authentication routes and Jinja2 templates."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tailhedge.config import DEFAULT_SESSION_SECRET, Mode, Secrets, Settings
from tailhedge.persistence.engine import get_engine, get_session
from tailhedge.persistence.models import AppUser
from tailhedge.web.auth import (
    _SESSION_COOKIE,
    create_session_cookie,
    generate_csrf_token,
    generate_session_id,
    require_auth,
    require_csrf,
    validate_csrf_token,
    verify_password_constant_time,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_LOGIN_CSRF_SCOPE = "login"

SessionDep = Annotated[Session, Depends(get_session)]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Fail closed when a real deployment runs with development defaults."""
    settings = Settings()
    secrets = Secrets()
    if secrets.session_secret.get_secret_value() == DEFAULT_SESSION_SECRET:
        if settings.mode != Mode.RESEARCH_ONLY:
            msg = (
                "TAILHEDGE_SECRET_SESSION_SECRET must be set when mode is not "
                "RESEARCH_ONLY; refusing to start with the development default."
            )
            raise RuntimeError(msg)
        logger.warning(
            "Using the development default session secret; set "
            "TAILHEDGE_SECRET_SESSION_SECRET before leaving RESEARCH_ONLY."
        )
    yield


app = FastAPI(title="TailHedge", version="0.1.0", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


def _get_settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# Health endpoints (no auth)
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def check_database_ready() -> None:
    """Verify the database accepts connections; raise 503 otherwise."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not ready.",
        ) from e


@app.get("/readyz")
async def readyz(
    _db_ready: Annotated[None, Depends(check_database_ready)],
) -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


def _login_response(
    request: Request,
    error: str,
    status_code: int,
) -> HTMLResponse:
    context: dict[str, object] = {
        "request": request,
        "csrf_token": generate_csrf_token(_LOGIN_CSRF_SCOPE),
        "error": error,
    }
    return templates.TemplateResponse(request, "login.html", context, status_code)


@app.get("/auth/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    return _login_response(request, "", status.HTTP_200_OK)


@app.post("/auth/login", response_model=None)
async def login(
    request: Request,
    db: SessionDep,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(""),
) -> RedirectResponse | HTMLResponse:
    if not validate_csrf_token(_LOGIN_CSRF_SCOPE, csrf_token):
        return _login_response(
            request,
            "Invalid or missing CSRF token. Please try again.",
            status.HTTP_403_FORBIDDEN,
        )

    settings = _get_settings()
    user = db.scalar(select(AppUser).where(AppUser.username == username))
    password_ok = verify_password_constant_time(
        password, user.password_hash if user is not None else None
    )
    if user is None or not password_ok or not user.is_active:
        return _login_response(
            request,
            "Invalid username or password.",
            status.HTTP_401_UNAUTHORIZED,
        )

    session_id = generate_session_id()
    cookie_value = create_session_cookie(session_id, settings.session_max_age_seconds)
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


def _page_context(
    request: Request, active_page: str, **kwargs: object
) -> dict[str, object]:
    """Build standard template context for a page."""
    settings = _get_settings()
    ctx: dict[str, object] = {
        "request": request,
        "active_page": active_page,
        "mode": settings.mode.value,
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
        request,
        "operations-broker-health.html",
        _page_context(request, "operations"),
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


@app.get("/research/backtest", response_class=HTMLResponse)
async def research_backtest(
    request: Request,
    _session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "research-backtest.html", _page_context(request, "research")
    )


# ---------------------------------------------------------------------------
# Protected API routes
# ---------------------------------------------------------------------------


@app.get("/api/v1/status")
async def api_status(
    session_id: Annotated[str, Depends(require_auth)],
) -> dict[str, str]:
    return {"status": "authenticated", "session": session_id}


@app.get("/api/v1/backtest/synthetic")
async def api_backtest_synthetic(
    _session_id: Annotated[str, Depends(require_auth)],
) -> dict[str, object]:
    """Return synthetic backtest results for demonstration."""
    return {
        "status": "success",
        "hedged": {
            "cagr": 0.085,
            "max_drawdown": -0.12,
            "max_drawdown_duration_days": 45,
            "total_premium_spent": 15000.0,
            "annualised_premium_spent": 1500.0,
            "premium_spend_ratio": 0.015,
            "final_value": 185000.0,
            "initial_value": 100000.0,
            "total_return": 0.85,
        },
        "unhedged": {
            "cagr": 0.072,
            "max_drawdown": -0.28,
            "max_drawdown_duration_days": 120,
            "total_premium_spent": 0.0,
            "annualised_premium_spent": 0.0,
            "premium_spend_ratio": 0.0,
            "final_value": 172000.0,
            "initial_value": 100000.0,
            "total_return": 0.72,
        },
        "comparison": {
            "cagr_delta": 0.013,
            "drawdown_improvement": 0.16,
            "fold_utility": 0.053,
            "tail_efficiency": 0.000107,
        },
    }


@app.post("/api/v1/example")
async def api_example(
    session_id: Annotated[str, Depends(require_csrf)],
) -> dict[str, str]:
    return {"status": "csrf_validated", "session": session_id}
