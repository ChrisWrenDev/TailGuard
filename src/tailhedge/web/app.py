"""FastAPI application with authentication routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from tailhedge.config import Settings
from tailhedge.web.auth import _SESSION_COOKIE, require_auth, require_csrf

app = FastAPI(title="TailHedge", version="0.1.0")


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
async def login_form() -> str:
    return (
        "<html><body>"
        "<h1>TailHedge Login</h1>"
        '<form method="post" action="/auth/login">'
        '<input type="hidden" name="csrf_token" value="{{ csrf_token }}" />'
        '<label>Username: <input name="username" required /></label><br/>'
        '<label>Password: <input name="password" type="password" required /></label><br/>'
        '<button type="submit">Login</button>'
        "</form></body></html>"
    )


@app.post("/auth/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    settings: Annotated[Settings, Depends(_get_settings)] = ...,  # type: ignore[assignment]
) -> RedirectResponse:
    # TODO: look up user in database; for now reject all logins
    # This will be wired up properly when database auth is complete.
    del request, username, password, settings  # unused until DB wiring
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="AUTH_INVALID",
    )


@app.post("/auth/logout")
async def logout(
    session_id: Annotated[str, Depends(require_auth)],
) -> RedirectResponse:
    del session_id  # used by require_auth dependency
    response = RedirectResponse(
        url="/auth/login", status_code=status.HTTP_303_SEE_OTHER
    )
    response.delete_cookie(_SESSION_COOKIE)
    return response


# ---------------------------------------------------------------------------
# Protected example route (requires auth)
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
