"""Typed configuration with environment separation and secrets isolation."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Mode(StrEnum):
    """Operation modes. Live modes are post-MVP and rejected by default."""

    RESEARCH_ONLY = "RESEARCH_ONLY"
    SHADOW = "SHADOW"
    PAPER = "PAPER"
    LIVE_APPROVAL = "LIVE_APPROVAL"
    LIVE_AUTONOMOUS = "LIVE_AUTONOMOUS"


_LIVE_MODES = frozenset({Mode.LIVE_APPROVAL, Mode.LIVE_AUTONOMOUS})


class Secrets(BaseSettings):
    """Secret values loaded from environment only. Never serialised or logged."""

    model_config = SettingsConfigDict(env_prefix="TAILHEDGE_SECRET_")

    database_url: SecretStr = Field(
        default=SecretStr(
            "postgresql+psycopg://tailhedge:tailhedge@localhost:5432/tailhedge"
        ),
        description="Full SQLAlchemy database URL (contains password).",
    )
    ibkr_password: SecretStr | None = Field(
        default=None,
        description="IBKR TWS/Gateway password.",
    )
    ibkr_account: SecretStr | None = Field(
        default=None,
        description="IBKR account identifier.",
    )
    agent_api_key: SecretStr | None = Field(
        default=None,
        description="API key for external agent/LLM provider.",
    )
    notification_api_key: SecretStr | None = Field(
        default=None,
        description="API key for notification provider.",
    )
    session_secret: SecretStr = Field(
        default=SecretStr("dev-only-session-secret-replace-in-production"),
        description="Secret key for signing session cookies.",
    )

    def mask_all(self) -> dict[str, str]:
        """Return a safe-to-log snapshot with every secret masked."""
        return dict.fromkeys(Secrets.model_fields, "***")


class Settings(BaseSettings):
    """Non-secret application configuration loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_prefix="TAILHEDGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- mode ---
    mode: Mode = Field(
        default=Mode.RESEARCH_ONLY,
        description="Current operation mode.",
    )
    allow_live: bool = Field(
        default=False,
        description="Must be True to permit live modes. MVP always False.",
    )

    # --- database (non-secret parts) ---
    database_host: str = Field(default="localhost", description="PostgreSQL host.")
    database_port: int = Field(default=5432, description="PostgreSQL port.")
    database_name: str = Field(
        default="tailhedge", description="PostgreSQL database name."
    )
    database_user: str = Field(default="tailhedge", description="PostgreSQL user.")

    # --- dataset ---
    dataset_root: str = Field(
        default="data",
        description="Root path for licensed research datasets.",
    )

    # --- scheduling ---
    decision_time: str = Field(
        default="15:45",
        description="Daily decision time in HH:MM (America/New_York).",
    )
    decision_timezone: str = Field(
        default="America/New_York",
        description="IANA timezone for daily decision.",
    )

    # --- broker (non-secret) ---
    broker_host: str = Field(default="127.0.0.1", description="TWS/Gateway host.")
    broker_port: int = Field(default=7497, description="TWS/Gateway port.")
    broker_client_id: int = Field(default=1, description="IBKR client ID.")
    broker_account_alias: str = Field(
        default="paper",
        description="Human label for the configured broker account.",
    )

    # --- agent / sandbox ---
    agent_provider_command: str | None = Field(
        default=None,
        description="Shell command for the local-command agent provider.",
    )
    sandbox_cpu_seconds: int = Field(
        default=30, description="Evaluator CPU time limit."
    )
    sandbox_memory_mb: int = Field(
        default=512, description="Evaluator memory limit (MB)."
    )
    sandbox_pid_max: int = Field(default=64, description="Evaluator PID limit.")

    # --- risk thresholds (defaults from spec) ---
    max_annual_premium_pct: float = Field(
        default=0.03,
        description="Maximum annualised premium spend as fraction of equity.",
    )
    max_single_premium_pct: float = Field(
        default=0.01,
        description="Maximum single-trade premium as fraction of equity.",
    )

    # --- session ---
    session_cookie_secure: bool = Field(
        default=False,
        description="Set Secure flag on session cookie (True when TLS enabled).",
    )
    session_cookie_samesite: str = Field(
        default="strict",
        description="SameSite policy for session cookie.",
    )
    session_max_age_seconds: int = Field(
        default=86400,
        description="Session lifetime in seconds (default 24h).",
    )

    @model_validator(mode="after")
    def reject_live_in_mvp(self) -> Settings:
        """Live modes are not permitted in MVP."""
        if self.mode in _LIVE_MODES and not self.allow_live:
            msg = (
                f"Mode {self.mode.value!r} requires allow_live=True. "
                "Live modes are not enabled in MVP."
            )
            raise ValueError(msg)
        return self

    @property
    def database_url_non_secret(self) -> str:
        """Construct database URL without the password (safe for logging)."""
        return (
            f"postgresql+psycopg://{self.database_user}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )
