"""Evaluator OCI sandbox security tests.

These tests verify the evaluator sandbox enforces all security constraints
required by TASK-020:
- network access is blocked
- secret/broker paths are inaccessible
- data mounts are read-only
- infinite loops time out
- fork bombs / process floods are blocked
- excessive memory is killed
- holdout data is never mounted
- oversized output is rejected

Requirements tested:
- FR-006: strategy interface isolation
- FR-008: autoresearch iteration safety
- FR-010: final holdout isolation

The tests require a working Docker daemon.  They are marked ``integration``
and will be skipped in CI environments without Docker support.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tailhedge.research.evaluator import (
    SandboxConfig,
    build_evaluator_image,
    ensure_image,
    evaluate_strategy_source,
    get_image_id,
    run_in_sandbox,
)

EVALUATOR_IMAGE = "tailhedge-evaluator"


def _docker_available() -> bool:
    """Check if Docker daemon is accessible."""
    import subprocess

    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


requires_docker = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker daemon not available",
)


def _make_context(
    trade_date: str = "2026-01-15",
    underlying_close: float = 500.0,
    features: list[str] | None = None,
) -> dict[str, object]:  # type: ignore[type-arg]
    """Create a minimal StrategyContext dict for testing."""
    return {
        "trade_date": trade_date,
        "underlying_close": underlying_close,
        "enabled_features": features or [],
        "portfolio": {
            "total_value": 100_000.0,
            "cash": 50_000.0,
            "units": 200.0,
            "base_currency": "GBP",
        },
    }


VALID_STRATEGY = """
from tailhedge.domain.strategy_sdk import (
    StrategyContext,
    TargetHedgePlan,
)


class Strategy:
    def decide(self, context: StrategyContext) -> TargetHedgePlan:
        return TargetHedgePlan(
            trade_date=context.trade_date,
            reasoning="Valid test strategy",
        )
"""


# ---------------------------------------------------------------------------
# Image build tests
# ---------------------------------------------------------------------------


@requires_docker
class TestEvaluatorImage:
    """Tests for the evaluator Docker image."""

    def test_image_builds_successfully(self) -> None:
        """Evaluator image builds without errors."""
        image_id = build_evaluator_image()
        assert image_id is not None
        assert image_id.startswith("sha256:")

    def test_image_exists_after_build(self) -> None:
        """Built image is inspectable."""
        build_evaluator_image()
        image_id = get_image_id(EVALUATOR_IMAGE)
        assert image_id is not None

    def test_ensure_image_idempotent(self) -> None:
        """ensure_image returns the same ID on repeated calls."""
        id1 = ensure_image()
        id2 = ensure_image()
        assert id1 == id2


# ---------------------------------------------------------------------------
# Network isolation tests
# ---------------------------------------------------------------------------


@requires_docker
class TestNetworkIsolation:
    """Verify that network access is blocked inside the sandbox."""

    def test_network_request_fails(self) -> None:
        """Strategy attempting a network connection must fail."""
        strategy = """
import socket

class Strategy:
    def decide(self, context):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect(("8.8.8.8", 53))
            s.close()
            raise RuntimeError("Network access was not blocked")
        except OSError:
            from tailhedge.domain.strategy_sdk import TargetHedgePlan
            return TargetHedgePlan(
                trade_date=context.trade_date,
                reasoning="Network correctly blocked",
            )
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            wall_timeout_seconds=30,
        )
        assert result.success, (
            f"Strategy should succeed when network is blocked: {result.error_message}"
        )

    def test_http_request_fails(self) -> None:
        """Strategy attempting HTTP request must fail."""
        strategy = """
import urllib.request

class Strategy:
    def decide(self, context):
        try:
            urllib.request.urlopen("http://example.com", timeout=3)
            raise RuntimeError("HTTP access was not blocked")
        except Exception:
            from tailhedge.domain.strategy_sdk import TargetHedgePlan
            return TargetHedgePlan(
                trade_date=context.trade_date,
                reasoning="HTTP correctly blocked",
            )
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            wall_timeout_seconds=30,
        )
        assert result.success, (
            f"Strategy should succeed when HTTP is blocked: {result.error_message}"
        )


# ---------------------------------------------------------------------------
# Secret/broker path isolation tests
# ---------------------------------------------------------------------------


@requires_docker
class TestSecretPathIsolation:
    """Verify that secret and broker paths are inaccessible."""

    def test_etc_shadow_inaccessible(self) -> None:
        """Strategy cannot read /etc/shadow."""
        strategy = """
class Strategy:
    def decide(self, context):
        try:
            with open("/etc/shadow") as f:
                content = f.read()
                if content:
                    raise RuntimeError("Was able to read /etc/shadow")
        except (PermissionError, FileNotFoundError, OSError):
            pass

        from tailhedge.domain.strategy_sdk import TargetHedgePlan
        return TargetHedgePlan(
            trade_date=context.trade_date,
            reasoning="Secret path correctly blocked",
        )
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            wall_timeout_seconds=30,
        )
        assert result.success, f"Strategy should succeed: {result.error_message}"

    def test_docker_socket_inaccessible(self) -> None:
        """Strategy cannot access Docker socket."""
        strategy = """
import os

class Strategy:
    def decide(self, context):
        paths = ["/var/run/docker.sock", "/run/docker.sock"]
        for path in paths:
            if os.path.exists(path):
                raise RuntimeError(f"Docker socket accessible at {path}")

        from tailhedge.domain.strategy_sdk import TargetHedgePlan
        return TargetHedgePlan(
            trade_date=context.trade_date,
            reasoning="Docker socket correctly blocked",
        )
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            wall_timeout_seconds=30,
        )
        assert result.success, f"Strategy should succeed: {result.error_message}"

    def test_home_directory_not_writable(self) -> None:
        """Strategy cannot write to /home directory."""
        strategy = """
import os

class Strategy:
    def decide(self, context):
        try:
            with open("/home/test_write.txt", "w") as f:
                f.write("should fail")
            raise RuntimeError("Was able to write to /home")
        except (PermissionError, OSError):
            pass

        from tailhedge.domain.strategy_sdk import TargetHedgePlan
        return TargetHedgePlan(
            trade_date=context.trade_date,
            reasoning="Home directory write correctly blocked",
        )
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            wall_timeout_seconds=30,
        )
        assert result.success, f"Strategy should succeed: {result.error_message}"


# ---------------------------------------------------------------------------
# Read-only mount tests
# ---------------------------------------------------------------------------


@requires_docker
class TestReadOnlyMounts:
    """Verify that data mounts are read-only."""

    def test_write_to_data_mount_fails(self) -> None:
        """Strategy cannot write to /data mount."""
        strategy = """
import os

class Strategy:
    def decide(self, context):
        try:
            with open("/data/test_write.txt", "w") as f:
                f.write("should fail")
            raise RuntimeError("Was able to write to /data")
        except (PermissionError, OSError):
            pass

        from tailhedge.domain.strategy_sdk import TargetHedgePlan
        return TargetHedgePlan(
            trade_date=context.trade_date,
            reasoning="Data write correctly blocked",
        )
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            wall_timeout_seconds=30,
        )
        assert result.success, f"Strategy should succeed: {result.error_message}"

    def test_write_to_workspace_fails(self) -> None:
        """Strategy cannot write to /workspace mount."""
        strategy = """
import os

class Strategy:
    def decide(self, context):
        try:
            with open("/workspace/test_write.txt", "w") as f:
                f.write("should fail")
            raise RuntimeError("Was able to write to /workspace")
        except (PermissionError, OSError):
            pass

        from tailhedge.domain.strategy_sdk import TargetHedgePlan
        return TargetHedgePlan(
            trade_date=context.trade_date,
            reasoning="Workspace write correctly blocked",
        )
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            wall_timeout_seconds=30,
        )
        assert result.success, f"Strategy should succeed: {result.error_message}"


# ---------------------------------------------------------------------------
# Timeout tests
# ---------------------------------------------------------------------------


@requires_docker
class TestTimeoutEnforcement:
    """Verify that infinite loops and long-running code time out."""

    def test_infinite_loop_times_out(self) -> None:
        """Infinite loop must be terminated by wall-clock timeout."""
        strategy = """
class Strategy:
    def decide(self, context):
        while True:
            pass
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            wall_timeout_seconds=5,
        )
        assert not result.success
        assert result.error_type == "Timeout"
        assert result.wall_time_seconds <= 15

    def test_sleep_times_out(self) -> None:
        """Long sleep must be terminated by wall-clock timeout."""
        strategy = """
import time

class Strategy:
    def decide(self, context):
        time.sleep(60)
        from tailhedge.domain.strategy_sdk import TargetHedgePlan
        return TargetHedgePlan(trade_date=context.trade_date)
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            wall_timeout_seconds=5,
        )
        assert not result.success
        assert result.error_type == "Timeout"


# ---------------------------------------------------------------------------
# Resource limit tests
# ---------------------------------------------------------------------------


@requires_docker
class TestResourceLimits:
    """Verify that resource limits are enforced."""

    def test_excessive_memory_terminated(self) -> None:
        """Excessive memory allocation must be killed."""
        strategy = """
class Strategy:
    def decide(self, context):
        data = b"x" * (1024 * 1024 * 1024)
        from tailhedge.domain.strategy_sdk import TargetHedgePlan
        return TargetHedgePlan(trade_date=context.trade_date)
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            memory_mb=64,
            wall_timeout_seconds=30,
        )
        assert not result.success
        assert result.error_type in ("Timeout", "MemoryError", "NoOutput")

    def test_fork_bomb_blocked(self) -> None:
        """Fork bomb must be blocked by PID limit."""
        strategy = """
import os

class Strategy:
    def decide(self, context):
        try:
            for _ in range(1000):
                pid = os.fork()
                if pid == 0:
                    os._exit(0)
        except OSError:
            pass

        from tailhedge.domain.strategy_sdk import TargetHedgePlan
        return TargetHedgePlan(
            trade_date=context.trade_date,
            reasoning="Fork bomb blocked",
        )
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            pid_max=16,
            wall_timeout_seconds=15,
        )
        assert result.success, (
            f"Fork bomb strategy should succeed (blocked): {result.error_message}"
        )


# ---------------------------------------------------------------------------
# Holdout isolation tests
# ---------------------------------------------------------------------------


@requires_docker
class TestHoldoutIsolation:
    """Verify that holdout data is never mounted."""

    def test_holdout_not_mounted(self) -> None:
        """Holdout path must not exist inside the container."""
        strategy = """
import os

class Strategy:
    def decide(self, context):
        holdout_path = "/holdout"
        if os.path.exists(holdout_path):
            entries = os.listdir(holdout_path)
            if entries:
                raise RuntimeError(
                    f"Holdout mounted and accessible: {entries}"
                )

        from tailhedge.domain.strategy_sdk import TargetHedgePlan
        return TargetHedgePlan(
            trade_date=context.trade_date,
            reasoning="Holdout correctly not mounted",
        )
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            holdout_mount_path=Path("/nonexistent/holdout"),
            wall_timeout_seconds=30,
        )
        assert result.success, f"Strategy should succeed: {result.error_message}"


# ---------------------------------------------------------------------------
# Output validation tests
# ---------------------------------------------------------------------------


@requires_docker
class TestOutputValidation:
    """Verify that output validation works correctly."""

    def test_invalid_output_rejected(self) -> None:
        """Strategy returning non-TargetHedgePlan must fail."""
        strategy = """
class Strategy:
    def decide(self, context):
        return {"not": "a plan"}
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            wall_timeout_seconds=30,
        )
        assert not result.success
        assert result.error_type in ("TypeError", "InvalidOutput", "AttributeError")

    def test_prohibited_fields_rejected(self) -> None:
        """Strategy plan with prohibited fields must be rejected."""
        strategy = """
from tailhedge.domain.strategy_sdk import (
    StrategyContext,
    TargetHedgePlan,
    HedgeAction,
    TargetTranche,
)


class Strategy:
    def decide(self, context):
        import json
        plan = TargetHedgePlan(
            trade_date=context.trade_date,
            reasoning="Test",
        )
        plan_dict = json.loads(plan.to_json())
        plan_dict["broker_order_id"] = "evil"
        return plan_dict
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            wall_timeout_seconds=30,
        )
        assert not result.success
        assert result.error_type in ("TypeError", "ValueError", "InvalidOutput")

    def test_oversized_output_rejected(self) -> None:
        """Output exceeding size limit must be rejected."""
        strategy = """
from tailhedge.domain.strategy_sdk import StrategyContext, TargetHedgePlan


class Strategy:
    def decide(self, context):
        huge_reasoning = "x" * (1024 * 1024 * 20)
        return TargetHedgePlan(
            trade_date=context.trade_date,
            reasoning=huge_reasoning,
        )
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            output_max_bytes=1024 * 1024,
            wall_timeout_seconds=30,
        )
        assert not result.success
        assert result.error_type in ("OutputTooLarge", "ValueError")


# ---------------------------------------------------------------------------
# Valid strategy tests
# ---------------------------------------------------------------------------


@requires_docker
class TestValidStrategy:
    """Verify that valid strategies execute correctly."""

    def test_no_action_strategy(self) -> None:
        """Empty plan (NO_ACTION) must succeed."""
        result = evaluate_strategy_source(
            VALID_STRATEGY,
            _make_context(),
            wall_timeout_seconds=30,
        )
        assert result.success
        assert result.output_json is not None
        assert result.output_json["trade_date"] == "2026-01-15"
        assert result.wall_time_seconds > 0

    def test_strategy_with_context_features(self) -> None:
        """Strategy receiving enabled features must work."""
        strategy = """
from tailhedge.domain.strategy_sdk import (
    StrategyContext,
    StrategyFeature,
    TargetHedgePlan,
)


class Strategy:
    def decide(self, context: StrategyContext) -> TargetHedgePlan:
        reasoning = f"Features: {sorted(f.value for f in context.enabled_features)}"
        return TargetHedgePlan(
            trade_date=context.trade_date,
            reasoning=reasoning,
        )
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(features=["CURRENT_PORTFOLIO", "UNDERLYING_CLOSE"]),
            wall_timeout_seconds=30,
        )
        assert result.success
        assert "CURRENT_PORTFOLIO" in result.output_json["reasoning"]  # type: ignore[index]

    def test_strategy_hash_verification(self) -> None:
        """Hash mismatch must be rejected before container launch."""
        result = evaluate_strategy_source(
            VALID_STRATEGY,
            _make_context(),
            wall_timeout_seconds=30,
        )
        config = SandboxConfig(
            strategy_source=VALID_STRATEGY,
            strategy_hash="0" * 64,
            context_json=_make_context(),
        )
        result = run_in_sandbox(config)
        assert not result.success
        assert result.error_type == "HashMismatch"


# ---------------------------------------------------------------------------
# Exit code and error propagation tests
# ---------------------------------------------------------------------------


@requires_docker
class TestErrorPropagation:
    """Verify that strategy errors are captured and reported."""

    def test_strategy_exception_captured(self) -> None:
        """Strategy raising an exception must produce an ERROR result."""
        strategy = """
class Strategy:
    def decide(self, context):
        raise ValueError("Intentional test error")
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            wall_timeout_seconds=30,
        )
        assert not result.success
        assert result.error_type == "ValueError"
        assert "Intentional test error" in (result.error_message or "")

    def test_missing_strategy_class(self) -> None:
        """Module without Strategy class must fail."""
        strategy = """
class NotStrategy:
    def decide(self, context):
        pass
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            wall_timeout_seconds=30,
        )
        assert not result.success
        assert result.error_type == "AttributeError"

    def test_syntax_error_captured(self) -> None:
        """Strategy with syntax error must fail gracefully."""
        strategy = """
def broken(
    # missing closing paren
"""
        result = evaluate_strategy_source(
            strategy,
            _make_context(),
            wall_timeout_seconds=30,
        )
        assert not result.success
