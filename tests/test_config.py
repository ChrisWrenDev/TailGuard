"""Tests for typed configuration and environment separation (TASK-002)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from tailhedge.config import Mode, Secrets, Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no leftover env vars leak between tests."""
    for key in (
        "TAILHEDGE_MODE",
        "TAILHEDGE_ALLOW_LIVE",
        "TAILHEDGE_DATABASE_HOST",
        "TAILHEDGE_DATABASE_PORT",
        "TAILHEDGE_DATABASE_NAME",
        "TAILHEDGE_DATABASE_USER",
        "TAILHEDGE_DATASET_ROOT",
        "TAILHEDGE_DECISION_TIME",
        "TAILHEDGE_DECISION_TIMEZONE",
        "TAILHEDGE_BROKER_HOST",
        "TAILHEDGE_BROKER_PORT",
        "TAILHEDGE_BROKER_CLIENT_ID",
        "TAILHEDGE_BROKER_ACCOUNT_ALIAS",
        "TAILHEDGE_AGENT_PROVIDER_COMMAND",
        "TAILHEDGE_SANDBOX_CPU_SECONDS",
        "TAILHEDGE_SANDBOX_MEMORY_MB",
        "TAILHEDGE_SANDBOX_PID_MAX",
        "TAILHEDGE_MAX_ANNUAL_PREMIUM_PCT",
        "TAILHEDGE_MAX_SINGLE_PREMIUM_PCT",
    ):
        monkeypatch.delenv(key, raising=False)


class TestMode:
    def test_valid_modes_exist(self) -> None:
        assert Mode.RESEARCH_ONLY == "RESEARCH_ONLY"
        assert Mode.SHADOW == "SHADOW"
        assert Mode.PAPER == "PAPER"
        assert Mode.LIVE_APPROVAL == "LIVE_APPROVAL"
        assert Mode.LIVE_AUTONOMOUS == "LIVE_AUTONOMOUS"

    def test_mode_is_string_enum(self) -> None:
        assert isinstance(Mode.RESEARCH_ONLY, str)
        assert Mode.RESEARCH_ONLY == "RESEARCH_ONLY"


class TestSettings:
    def test_defaults(self) -> None:
        settings = Settings()
        assert settings.mode == Mode.RESEARCH_ONLY
        assert settings.allow_live is False
        assert settings.database_host == "localhost"

    def test_mode_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAILHEDGE_MODE", "PAPER")
        settings = Settings()
        assert settings.mode == Mode.PAPER

    def test_reject_live_approval_without_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TAILHEDGE_MODE", "LIVE_APPROVAL")
        with pytest.raises(ValidationError, match="LIVE_APPROVAL"):
            Settings()

    def test_reject_live_autonomous_without_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TAILHEDGE_MODE", "LIVE_AUTONOMOUS")
        with pytest.raises(ValidationError, match="LIVE_AUTONOMOUS"):
            Settings()

    def test_reject_invalid_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAILHEDGE_MODE", "INVALID_MODE")
        with pytest.raises(ValidationError):
            Settings()

    def test_database_url_non_secret_omits_password(self) -> None:
        settings = Settings()
        url = settings.database_url_non_secret
        assert "PASSWORD" not in url
        assert "tailhedge@localhost" in url

    def test_settings_serialisation_excludes_secrets(self) -> None:
        settings = Settings()
        dumped = settings.model_dump()
        assert "password" not in str(dumped).lower()

    def test_risk_thresholds_default(self) -> None:
        settings = Settings()
        assert settings.max_annual_premium_pct == pytest.approx(0.03)
        assert settings.max_single_premium_pct == pytest.approx(0.01)

    def test_sandbox_limits_default(self) -> None:
        settings = Settings()
        assert settings.sandbox_cpu_seconds == 30
        assert settings.sandbox_memory_mb == 512
        assert settings.sandbox_pid_max == 64


class TestSecrets:
    def test_secrets_default_construction(self) -> None:
        secrets = Secrets()
        assert isinstance(secrets.database_url, SecretStr)

    def test_secrets_not_in_serialisation(self) -> None:
        secrets = Secrets()
        # mode='json' serialises SecretStr as masked strings, not raw values
        dumped = secrets.model_dump(mode="json")
        for value in dumped.values():
            assert not isinstance(value, SecretStr)
            if isinstance(value, str):
                assert (
                    value
                    != "postgresql+psycopg://tailhedge:tailhedge@localhost:5432/tailhedge"
                )

    def test_mask_all_returns_stars(self) -> None:
        secrets = Secrets()
        masked = secrets.mask_all()
        assert all(v == "***" for v in masked.values())
        assert "database_url" in masked

    def test_secrets_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAILHEDGE_SECRET_AGENT_API_KEY", "test-key-123")
        secrets = Secrets()
        assert secrets.agent_api_key is not None
        assert secrets.agent_api_key.get_secret_value() == "test-key-123"
