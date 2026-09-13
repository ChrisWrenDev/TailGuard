"""FastAPI application with authentication routes and Jinja2 templates."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

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
    session_id: Annotated[str, Depends(require_auth)],
    db: SessionDep,
) -> HTMLResponse:
    """Campaign list page with live campaign rows."""
    from tailhedge.research.campaign_service import list_campaigns

    campaigns = list_campaigns(db)
    campaign_list = [
        {
            "id": str(c.id),
            "name": c.name,
            "status": c.status,
            "dataset_id": str(c.dataset_id),
            "max_iterations": c.max_iterations,
            "created_at": c.created_at.isoformat(),
            "manifest_sha256": c.campaign_manifest_sha256,
        }
        for c in campaigns
    ]
    return templates.TemplateResponse(
        request,
        "research-campaigns.html",
        _page_context(
            request,
            "research",
            campaigns=campaign_list,
            csrf_token=generate_csrf_token(session_id),
        ),
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
    session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    """Empty-state backtest page; results appear after an explicit run."""
    return templates.TemplateResponse(
        request,
        "research-backtest.html",
        _page_context(
            request,
            "research",
            result=None,
            csrf_token=generate_csrf_token(session_id),
        ),
    )


@app.post("/research/backtest/run", response_class=HTMLResponse)
async def research_backtest_run(
    request: Request,
    session_id: Annotated[str, Depends(require_csrf)],
) -> HTMLResponse:
    """Run the deterministic synthetic backtest and render real results."""
    from tailhedge.research.synthetic_backtest import run_synthetic_backtest

    result = run_synthetic_backtest()
    logger.info(
        "Synthetic backtest run by session %s: hedged CAGR %.4f",
        session_id[:8],
        result.hedged.metrics.cagr,
    )
    return templates.TemplateResponse(
        request,
        "research-backtest.html",
        _page_context(
            request,
            "research",
            result=result,
            csrf_token=generate_csrf_token(session_id),
        ),
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
    """Return the deterministic synthetic backtest, computed by the shared engine."""
    from tailhedge.research.synthetic_backtest import run_synthetic_backtest

    return run_synthetic_backtest().to_api_dict()


@app.post("/api/v1/example")
async def api_example(
    session_id: Annotated[str, Depends(require_csrf)],
) -> dict[str, str]:
    return {"status": "csrf_validated", "session": session_id}


# ---------------------------------------------------------------------------
# Dataset import API
# ---------------------------------------------------------------------------


@app.post("/api/v1/datasets/import")
async def api_dataset_import(
    _request: Request,
    _session_id: Annotated[str, Depends(require_csrf)],
    db: SessionDep,
    name: str = Form(...),
    source_vendor: str = Form(...),
    source_paths: str = Form(...),
    source_role: str = Form("OPTION_CHAIN"),
    timezone: str = Form("America/New_York"),
) -> RedirectResponse:
    """Trigger a dataset import job.

    Accepts form data with the dataset name, vendor, comma-separated
    file paths, source role, and timezone. Enqueues a background import
    job and redirects to the data page.
    """

    from tailhedge.worker.job_queue import enqueue_job

    paths_list = [p.strip() for p in source_paths.split(",") if p.strip()]

    settings = _get_settings()
    job = enqueue_job(
        db,
        job_type="dataset_import",
        payload={
            "name": name,
            "source_vendor": source_vendor,
            "source_paths": paths_list,
            "source_role": source_role,
            "timezone": timezone,
            "dataset_root": settings.dataset_root,
        },
    )

    logger.info(
        "Dataset import job enqueued: job_id=%s name=%s",
        job.id,
        name,
    )

    return RedirectResponse(
        url=f"/data?import_message=Import+job+{job.id}+queued.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Dataset listing API
# ---------------------------------------------------------------------------


@app.get("/api/v1/datasets")
async def api_list_datasets(
    _session_id: Annotated[str, Depends(require_auth)],
    db: SessionDep,
) -> dict[str, object]:
    """Return a list of all imported datasets with their validation status."""
    from sqlalchemy import select

    from tailhedge.persistence.models import ResearchDataset

    datasets = (
        db.execute(select(ResearchDataset).order_by(ResearchDataset.created_at.desc()))
        .scalars()
        .all()
    )
    result = []
    for ds in datasets:
        result.append(
            {
                "id": str(ds.id),
                "name": ds.name,
                "source_vendor": ds.source_vendor,
                "schema_version": ds.schema_version,
                "timezone": ds.timezone,
                "start_date": ds.start_date.isoformat()
                if hasattr(ds.start_date, "isoformat")
                else str(ds.start_date),
                "end_date": ds.end_date.isoformat()
                if hasattr(ds.end_date, "isoformat")
                else str(ds.end_date),
                "row_count": ds.row_count,
                "status": ds.status,
                "manifest_sha256": ds.manifest_sha256[:16] + "...",
                "created_at": ds.created_at.isoformat()
                if hasattr(ds.created_at, "isoformat")
                else str(ds.created_at),
            }
        )
    return {"datasets": result, "count": len(result)}


@app.get("/api/v1/datasets/{dataset_id}/validation")
async def api_dataset_validation(
    dataset_id: str,
    _session_id: Annotated[str, Depends(require_auth)],
    db: SessionDep,
) -> dict[str, object]:
    """Return the validation results for a specific dataset."""
    import uuid as uuid_mod

    from sqlalchemy import select

    from tailhedge.persistence.models import DatasetValidationResult, ResearchDataset

    try:
        ds_uuid = uuid_mod.UUID(dataset_id)
    except ValueError:
        return {"error": "Invalid dataset ID format"}

    dataset = db.execute(
        select(ResearchDataset).where(ResearchDataset.id == ds_uuid)
    ).scalar_one_or_none()

    if dataset is None:
        return {"error": "Dataset not found"}

    validations = (
        db.execute(
            select(DatasetValidationResult)
            .where(DatasetValidationResult.dataset_id == ds_uuid)
            .order_by(DatasetValidationResult.created_at.desc())
        )
        .scalars()
        .all()
    )

    validation_list = []
    for v in validations:
        validation_list.append(
            {
                "id": str(v.id),
                "validator_version": v.validator_version,
                "status": v.status,
                "summary_json": v.summary_json,
                "created_at": v.created_at.isoformat()
                if hasattr(v.created_at, "isoformat")
                else str(v.created_at),
            }
        )

    return {
        "dataset": {
            "id": str(dataset.id),
            "name": dataset.name,
            "status": dataset.status,
            "row_count": dataset.row_count,
        },
        "validations": validation_list,
    }


# ---------------------------------------------------------------------------
# Data page route (with datasets)
# ---------------------------------------------------------------------------


@app.get("/data", response_class=HTMLResponse)
async def data_page(
    request: Request,
    session_id: Annotated[str, Depends(require_auth)],
    db: SessionDep,
) -> HTMLResponse:
    """Data page showing imported datasets and their validation health."""
    from sqlalchemy import select

    from tailhedge.persistence.models import DatasetValidationResult, ResearchDataset

    import_message = request.query_params.get("import_message", "")

    datasets = (
        db.execute(select(ResearchDataset).order_by(ResearchDataset.created_at.desc()))
        .scalars()
        .all()
    )

    dataset_list = []
    for ds in datasets:
        latest_validation = db.execute(
            select(DatasetValidationResult)
            .where(DatasetValidationResult.dataset_id == ds.id)
            .order_by(DatasetValidationResult.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        validation_summary = {}
        if latest_validation:
            validation_summary = {
                "status": latest_validation.status,
                "summary": latest_validation.summary_json,
            }

        dataset_list.append(
            {
                "id": str(ds.id),
                "name": ds.name,
                "source_vendor": ds.source_vendor,
                "schema_version": ds.schema_version,
                "timezone": ds.timezone,
                "start_date": ds.start_date.strftime("%Y-%m-%d")
                if hasattr(ds.start_date, "strftime")
                else str(ds.start_date),
                "end_date": ds.end_date.strftime("%Y-%m-%d")
                if hasattr(ds.end_date, "strftime")
                else str(ds.end_date),
                "row_count": ds.row_count,
                "status": ds.status,
                "validation": validation_summary,
            }
        )

    return templates.TemplateResponse(
        request,
        "data.html",
        _page_context(
            request,
            "data",
            datasets=dataset_list,
            csrf_token=generate_csrf_token(session_id),
            import_message=import_message,
        ),
    )


# ---------------------------------------------------------------------------
# Import form partial (HTMX)
# ---------------------------------------------------------------------------


@app.get("/data/import-form", response_class=HTMLResponse)
async def data_import_form(
    request: Request,
    session_id: Annotated[str, Depends(require_auth)],
) -> HTMLResponse:
    """Return the import form as an HTMX partial."""
    return templates.TemplateResponse(
        request,
        "data-import-form.html",
        _page_context(
            request,
            "data",
            csrf_token=generate_csrf_token(session_id),
        ),
    )


# ---------------------------------------------------------------------------
# Campaign API (FR-007, TASK-021)
# ---------------------------------------------------------------------------


def _campaign_to_api_dict(campaign: object) -> dict[str, object]:
    """Serialise a ResearchCampaign for the JSON API (immutable fields marked)."""
    from tailhedge.research.campaign_config import IMMUTABLE_CONFIG_FIELDS

    c: Any = campaign
    data: dict[str, object] = {
        "id": str(c.id),
        "name": c.name,
        "description": c.description,
        "status": c.status,
        "dataset_id": str(c.dataset_id),
        "created_at": c.created_at.isoformat(),
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "ended_at": c.ended_at.isoformat() if c.ended_at else None,
        "cloned_from_campaign_id": (
            str(c.cloned_from_campaign_id) if c.cloned_from_campaign_id else None
        ),
    }
    for field_name in IMMUTABLE_CONFIG_FIELDS:
        value = getattr(c, field_name)
        if isinstance(value, UUID):
            value = str(value)
        data[field_name] = {"value": value, "immutable": True}
    data["campaign_manifest_sha256"] = c.campaign_manifest_sha256
    return data


@app.get("/api/v1/campaigns")
async def api_list_campaigns(
    _session_id: Annotated[str, Depends(require_auth)],
    db: SessionDep,
    status_filter: str | None = None,
    dataset_id: str | None = None,
) -> dict[str, object]:
    """List campaigns with optional status/dataset filters (API_SPEC §5)."""
    from tailhedge.research.campaign_service import list_campaigns

    dataset_uuid: UUID | None = None
    if dataset_id is not None:
        try:
            dataset_uuid = UUID(dataset_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid dataset ID format.",
            ) from exc

    campaigns = list_campaigns(db, status=status_filter, dataset_id=dataset_uuid)
    return {
        "campaigns": [_campaign_to_api_dict(c) for c in campaigns],
        "count": len(campaigns),
    }


@app.get("/api/v1/campaigns/{campaign_id}")
async def api_get_campaign(
    campaign_id: str,
    _session_id: Annotated[str, Depends(require_auth)],
    db: SessionDep,
) -> dict[str, object]:
    """Return one campaign with config/status; immutable fields marked."""
    from tailhedge.research.campaign_service import get_campaign

    try:
        campaign_uuid = UUID(campaign_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid campaign ID format.",
        ) from exc
    campaign = get_campaign(db, campaign_uuid)
    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found.",
        )
    return _campaign_to_api_dict(campaign)


@app.post("/api/v1/campaigns")
async def api_create_campaign(
    request: Request,
    _session_id: Annotated[str, Depends(require_csrf)],
    db: SessionDep,
) -> dict[str, object]:
    """Create a DRAFT campaign (API_SPEC §5).

    Body: JSON with ``name``, ``dataset_id`` and optional frozen-config
    overrides.  Defaults come from the architecture spec.
    """

    from tailhedge.research.campaign_config import CampaignConfigError
    from tailhedge.research.campaign_service import (
        create_campaign,
        default_campaign_config,
    )

    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be valid JSON.",
        ) from exc
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be a JSON object.",
        )

    name = body.get("name")
    dataset_id_raw = body.get("dataset_id")
    if not name or not dataset_id_raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'name' and 'dataset_id' are required.",
        )
    try:
        dataset_uuid = UUID(str(dataset_id_raw))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid dataset ID format.",
        ) from exc

    override_fields = (
        "portfolio_proxy_json",
        "split_config_json",
        "scoring_profile_json",
        "execution_cost_profile_json",
        "robustness_profile_json",
        "feature_allowlist_json",
        "strategy_bounds_json",
        "agent_config_redacted_json",
    )
    override_kwargs: dict[str, dict[str, object]] = {
        field_name: body[field_name]
        for field_name in override_fields
        if field_name in body
    }
    max_iterations = body.get("max_iterations")

    annual_premium_cap_raw = body.get("annual_premium_cap")
    try:
        annual_premium_cap = (
            float(annual_premium_cap_raw)
            if annual_premium_cap_raw is not None
            else None
        )
        max_iterations_value = (
            int(max_iterations) if max_iterations is not None else None
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'annual_premium_cap' must be a number and "
            "'max_iterations' must be an integer.",
        ) from exc

    try:
        config = default_campaign_config(
            dataset_id=dataset_uuid,
            annual_premium_cap=annual_premium_cap,
            max_iterations=max_iterations_value,
            **override_kwargs,
        )
        campaign = create_campaign(
            db,
            name=str(name),
            dataset_id=dataset_uuid,
            config=config,
            description=(str(body["description"]) if body.get("description") else None),
        )
    except CampaignConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return _campaign_to_api_dict(campaign)


@app.post("/api/v1/campaigns/{campaign_id}/start")
async def api_start_campaign(
    campaign_id: str,
    _session_id: Annotated[str, Depends(require_csrf)],
    db: SessionDep,
) -> dict[str, object]:
    """Freeze config and start a DRAFT campaign (API_SPEC §5).

    Errors: ``CAMPAIGN_NOT_DRAFT``, ``DATASET_NOT_READY``, ``CONFIG_HASH_FAILED``.
    """
    import uuid as uuid_mod

    from tailhedge.research.campaign_config import CampaignStateError
    from tailhedge.research.campaign_service import (
        CampaignManifestConflictError,
        CampaignNotFoundError,
        DatasetNotReadyError,
        start_campaign,
    )

    try:
        campaign_uuid = uuid_mod.UUID(campaign_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid campaign ID format.",
        ) from exc

    try:
        campaign = start_campaign(db, campaign_uuid)
    except CampaignNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found.",
        ) from exc
    except CampaignStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CAMPAIGN_NOT_DRAFT",
        ) from exc
    except DatasetNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="DATASET_NOT_READY",
        ) from exc
    except CampaignManifestConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CONFIG_HASH_FAILED",
        ) from exc

    return _campaign_to_api_dict(campaign)


@app.post("/api/v1/campaigns/{campaign_id}/clone")
async def api_clone_campaign(
    campaign_id: str,
    request: Request,
    _session_id: Annotated[str, Depends(require_csrf)],
    db: SessionDep,
) -> dict[str, object]:
    """Clone a campaign into a new DRAFT campaign (FR-007 clone path).

    Optional JSON body: ``name`` and ``config_overrides`` (a mapping of
    frozen config field names to replacement values).  Without a body the
    full configuration is copied unchanged.
    """
    import uuid as uuid_mod

    from tailhedge.research.campaign_config import CampaignConfigError
    from tailhedge.research.campaign_service import (
        CampaignNotFoundError,
        clone_campaign,
    )

    try:
        campaign_uuid = uuid_mod.UUID(campaign_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid campaign ID format.",
        ) from exc

    body: dict[str, object] = {}
    try:
        raw_body = await request.json()
    except Exception:
        raw_body = None
    if raw_body is not None:
        if not isinstance(raw_body, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request body must be a JSON object.",
            )
        body = raw_body

    name = body.get("name")
    config_overrides = body.get("config_overrides")
    if config_overrides is not None and not isinstance(config_overrides, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'config_overrides' must be a JSON object of frozen "
            "config field names to values.",
        )

    try:
        clone = clone_campaign(
            db,
            campaign_uuid,
            name=str(name) if name else None,
            config_overrides=dict(config_overrides) if config_overrides else None,
        )
    except CampaignNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found.",
        ) from exc
    except CampaignConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return _campaign_to_api_dict(clone)
