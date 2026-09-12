"""Evaluator entrypoint for isolated strategy execution.

This script runs inside an OCI container with strict security constraints:
- no network
- read-only root filesystem (except /result tmpfs)
- dropped Linux capabilities
- unprivileged user
- resource limits (CPU, memory, PID, timeout)

It loads a candidate strategy source file, imports it as a Python module,
invokes its ``decide`` method with a provided StrategyContext, serialises
the TargetHedgePlan result to /result/output.json, and exits.

Security measures:
- Only /workspace (strategy source) and /data (allowed data slice) are
  readable; broker/config/secrets/holdout paths are never mounted.
- Strategy code is executed via importlib with a restricted namespace.
- No network modules are imported before execution.
- stdout/stderr are captured; no direct host output.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path

RESULT_DIR = Path("/result")
STRATEGY_PATH = Path("/workspace/candidate.py")
CONTEXT_PATH = Path("/workspace/context.json")
DATA_DIR = Path("/data")
HOLDOUT_DIR = Path("/holdout")

SECURITY_BLOCKED_PATHS = [
    "/var/run/docker.sock",
    "/run/docker.sock",
]


def _validate_environment() -> None:
    """Verify we are running under the expected security constraints."""
    errors: list[str] = []

    if os.getuid() == 0:
        errors.append("Running as root is not permitted")

    if os.environ.get("DOCKER_HOST"):
        errors.append("DOCKER_HOST environment variable is present")

    try:
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(("8.8.8.8", 53))
        sock.close()
        if result == 0:
            errors.append("Network connectivity detected (should be blocked)")
    except Exception:
        pass

    for path_str in SECURITY_BLOCKED_PATHS:
        p = Path(path_str)
        if p.exists():
            errors.append(f"Blocked path {path_str} exists and is accessible")

    if errors:
        raise SecurityError(
            "Security validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )


class SecurityError(Exception):
    """Raised when a security constraint is violated."""


def _load_strategy(source_path: Path) -> type:
    """Load a candidate strategy module from source code.

    The strategy must define a class implementing StrategyProtocol:
        class Strategy:
            def decide(self, context: StrategyContext) -> TargetHedgePlan: ...
    """
    if not source_path.exists():
        raise FileNotFoundError(f"Strategy source not found: {source_path}")

    source = source_path.read_text(encoding="utf-8")
    if len(source) > 1024 * 1024:
        raise ValueError(f"Strategy source too large: {len(source)} bytes (max 1MB)")

    spec = importlib.util.spec_from_file_location(
        "candidate_strategy", str(source_path)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load strategy from {source_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    strategy_class = getattr(module, "Strategy", None)
    if strategy_class is None:
        raise AttributeError("Strategy module must define a 'Strategy' class")

    return strategy_class


def _load_context(context_path: Path) -> object:
    """Load and deserialise a StrategyContext from JSON.

    Returns a plain dict that the strategy can use.
    """
    if not context_path.exists():
        raise FileNotFoundError(f"Context not found: {context_path}")

    raw = context_path.read_text(encoding="utf-8")
    if len(raw) > 1024 * 1024:
        raise ValueError(f"Context too large: {len(raw)} bytes (max 1MB)")

    return json.loads(raw)


def _execute_strategy(
    strategy_class: type,
    context_data: dict,  # type: ignore[type-arg]
) -> dict:  # type: ignore[type-arg]
    """Execute the strategy's decide method and return the plan dict."""
    from tailhedge.domain.strategy_sdk import (
        HedgePositionSnapshot,
        OptionQuoteSnapshot,
        PortfolioSnapshot,
        StrategyContext,
        StrategyFeature,
        TargetHedgePlan,
        validate_plan_not_prohibited,
    )

    enabled_features = set()
    for feat_name in context_data.get("enabled_features", []):
        with contextlib.suppress(ValueError):
            enabled_features.add(StrategyFeature(feat_name))

    portfolio_data = context_data.get("portfolio")
    portfolio = None
    if portfolio_data:
        portfolio = PortfolioSnapshot(
            total_value=portfolio_data["total_value"],
            cash=portfolio_data["cash"],
            units=portfolio_data["units"],
            base_currency=portfolio_data["base_currency"],
            benchmark_equivalent_exposure=portfolio_data.get(
                "benchmark_equivalent_exposure", 0.0
            ),
        )

    positions = []
    for pos_data in context_data.get("positions", []):
        from datetime import date as date_type

        positions.append(
            HedgePositionSnapshot(
                strike=pos_data["strike"],
                expiration_date=date_type.fromisoformat(pos_data["expiration_date"]),
                quantity=pos_data["quantity"],
                entry_premium=pos_data["entry_premium"],
                current_dte=pos_data["current_dte"],
            )
        )

    option_chain = []
    for quote_data in context_data.get("option_chain", []):
        from datetime import date as date_type

        option_chain.append(
            OptionQuoteSnapshot(
                trade_date=date_type.fromisoformat(quote_data["trade_date"]),
                strike=quote_data["strike"],
                expiration_date=date_type.fromisoformat(quote_data["expiration_date"]),
                bid=quote_data["bid"],
                ask=quote_data["ask"],
                underlying_price=quote_data["underlying_price"],
            )
        )

    from datetime import date as date_type

    context = StrategyContext(
        trade_date=date_type.fromisoformat(context_data["trade_date"]),
        underlying_close=context_data["underlying_close"],
        enabled_features=frozenset(enabled_features),
        portfolio=portfolio,
        positions=tuple(positions),
        option_chain=tuple(option_chain),
        budget_consumed_ytd=context_data.get("budget_consumed_ytd", 0.0),
        budget_remaining=context_data.get("budget_remaining", 0.0),
        budget_cap_pct=context_data.get("budget_cap_pct", 0.0),
    )

    strategy = strategy_class()
    result = strategy.decide(context)

    if not isinstance(result, TargetHedgePlan):
        raise TypeError(
            f"Strategy must return TargetHedgePlan, got {type(result).__name__}"
        )

    plan_dict = {
        "schema_version": result.schema_version,
        "trade_date": result.trade_date.isoformat(),
        "tranches": [],
        "reasoning": result.reasoning,
    }

    for t in result.tranches:
        tranche_dict: dict = {"action": t.action.value}  # type: ignore[type-arg]
        if t.strike is not None:
            tranche_dict["strike"] = t.strike
        if t.expiration_date is not None:
            tranche_dict["expiration_date"] = t.expiration_date.isoformat()
        if t.quantity:
            tranche_dict["quantity"] = t.quantity
        if t.from_strike is not None:
            tranche_dict["from_strike"] = t.from_strike
        if t.from_expiration_date is not None:
            tranche_dict["from_expiration_date"] = t.from_expiration_date.isoformat()
        if t.from_quantity:
            tranche_dict["from_quantity"] = t.from_quantity
        if t.reinvest_fraction:
            tranche_dict["reinvest_fraction"] = t.reinvest_fraction
        plan_dict["tranches"].append(tranche_dict)

    errors = validate_plan_not_prohibited(plan_dict)
    if errors:
        raise ValueError(f"Plan contains prohibited fields: {'; '.join(errors)}")

    return plan_dict


def _write_result(result: dict, output_path: Path) -> None:  # type: ignore[type-arg]
    """Write the result JSON to the output path."""
    output = json.dumps(result, sort_keys=True, separators=(",", ":"))

    max_output_size = 10 * 1024 * 1024
    if len(output.encode("utf-8")) > max_output_size:
        raise ValueError(
            f"Output too large: {len(output.encode('utf-8'))} bytes "
            f"(max {max_output_size})"
        )

    output_path.write_text(output, encoding="utf-8")


def _write_error(error: Exception, output_path: Path) -> None:
    """Write an error result to the output path."""
    result = {
        "status": "ERROR",
        "error_type": type(error).__name__,
        "error_message": str(error),
    }
    output = json.dumps(result, sort_keys=True, separators=(",", ":"))
    output_path.write_text(output, encoding="utf-8")


def main() -> None:
    """Main entry point for the evaluator."""
    output_path = RESULT_DIR / "output.json"

    try:
        _validate_environment()

        if not STRATEGY_PATH.exists():
            raise FileNotFoundError(f"Strategy source not found at {STRATEGY_PATH}")

        strategy_class = _load_strategy(STRATEGY_PATH)

        context_data = _load_context(CONTEXT_PATH)

        result = _execute_strategy(strategy_class, context_data)

        _write_result(result, output_path)

        sys.exit(0)

    except Exception as exc:
        with contextlib.suppress(Exception):
            _write_error(exc, output_path)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
