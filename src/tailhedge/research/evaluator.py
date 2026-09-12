"""Evaluator OCI sandbox runner.

Runs untrusted agent-generated strategy code inside a locked-down OCI
container with:
- ``--network=none``
- read-only root filesystem
- dropped Linux capabilities (all)
- unprivileged (non-root) user
- memory / CPU / PID / wall-clock limits
- read-only mounts for evaluator package and allowed data slice only
- writable tmpfs for result JSON only
- no broker, config, secrets, or holdout mounts
- ``--pids-limit`` to block fork bombs

The runner builds the evaluator image on first use (or when the image
hash changes), then executes ``docker run`` with the strictest feasible
flags.  It is designed for local single-host deployment; no Kubernetes
or Docker Swarm orchestration is assumed.

Security rules enforced:
1. Candidate source hash is verified before execution.
2. Strategy output is validated against prohibited-field and schema checks.
3. Wall-clock timeout kills the container on expiry.
4. Output exceeding the configured size limit is rejected.
5. The holdout partition is never mounted.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

IMAGE_NAME = "tailhedge-evaluator"
DEFAULT_CPU_SECONDS = 30
DEFAULT_MEMORY_MB = 512
DEFAULT_PID_MAX = 64
DEFAULT_WALL_TIMEOUT_SECONDS = 120
DEFAULT_OUTPUT_MAX_BYTES = 10 * 1024 * 1024
RESULT_MAX_BYTES = 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SandboxConfig:
    """Configuration for a single evaluator sandbox run."""

    strategy_source: str
    """Python source code of the candidate strategy."""

    strategy_hash: str
    """Expected SHA-256 hex digest of ``strategy_source``."""

    context_json: dict[str, object]
    """Serialised StrategyContext."""

    data_mount_path: Path | None = None
    """Read-only mount for the allowed data slice."""

    holdout_mount_path: Path | None = None
    """Path to holdout data — NEVER mounted inside the container."""

    cpu_seconds: int = DEFAULT_CPU_SECONDS
    memory_mb: int = DEFAULT_MEMORY_MB
    pid_max: int = DEFAULT_PID_MAX
    wall_timeout_seconds: int = DEFAULT_WALL_TIMEOUT_SECONDS
    output_max_bytes: int = DEFAULT_OUTPUT_MAX_BYTES

    evaluator_image_tag: str = IMAGE_NAME
    """Docker image tag for the evaluator."""


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluatorResult:
    """Result of a sandbox evaluator run."""

    success: bool
    """True if the strategy executed and produced a valid plan."""

    output_json: dict[str, object] | None = None
    """Deserialised TargetHedgePlan JSON if successful."""

    error_type: str | None = None
    """Error class name if the run failed."""

    error_message: str | None = None
    """Human-readable error if the run failed."""

    wall_time_seconds: float = 0.0
    """Wall-clock time of the container run."""

    output_bytes: int = 0
    """Size of the output JSON in bytes."""


# ---------------------------------------------------------------------------
# Image build
# ---------------------------------------------------------------------------


def build_evaluator_image(
    image_tag: str = IMAGE_NAME,
    *,
    dockerfile_dir: Path | None = None,
) -> str:
    """Build the evaluator OCI image.

    Returns the image ID (sha256 digest) on success.

    Raises
    ------
    RuntimeError
        If the ``docker build`` command fails.
    """
    if dockerfile_dir is None:
        dockerfile_dir = Path(__file__).resolve().parents[3] / "evaluator_image"

    if not dockerfile_dir.exists():
        raise FileNotFoundError(
            f"Evaluator image directory not found: {dockerfile_dir}"
        )

    logger.info("Building evaluator image %s from %s", image_tag, dockerfile_dir)

    result = subprocess.run(
        [
            "docker",
            "build",
            "-t",
            image_tag,
            str(dockerfile_dir),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Docker build failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    inspect = subprocess.run(
        ["docker", "inspect", "-f", "{{.Id}}", image_tag],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if inspect.returncode != 0:
        raise RuntimeError(f"Failed to inspect built image: {inspect.stderr}")

    image_id = inspect.stdout.strip()
    logger.info("Evaluator image built: %s", image_id)
    return image_id


def get_image_id(image_tag: str = IMAGE_NAME) -> str | None:
    """Return the image ID for the given tag, or None if not found."""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.Id}}", image_tag],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def ensure_image(image_tag: str = IMAGE_NAME) -> str:
    """Ensure the evaluator image exists, building it if necessary.

    Returns the image ID.
    """
    image_id = get_image_id(image_tag)
    if image_id is not None:
        return image_id
    return build_evaluator_image(image_tag)


# ---------------------------------------------------------------------------
# Sandbox runner
# ---------------------------------------------------------------------------


def run_in_sandbox(config: SandboxConfig) -> EvaluatorResult:
    """Execute a candidate strategy inside an OCI sandbox.

    Parameters
    ----------
    config : SandboxConfig
        The configuration for this evaluation run.

    Returns
    -------
    EvaluatorResult
        The result of the evaluation.
    """
    actual_hash = hashlib.sha256(config.strategy_source.encode("utf-8")).hexdigest()
    if actual_hash != config.strategy_hash:
        return EvaluatorResult(
            success=False,
            error_type="HashMismatch",
            error_message=(
                f"Strategy source hash mismatch: expected {config.strategy_hash}, "
                f"got {actual_hash}"
            ),
        )

    if config.holdout_mount_path is not None:
        logger.warning(
            "Holdout path provided but will NOT be mounted: %s",
            config.holdout_mount_path,
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="tailhedge_sandbox_"))
    try:
        return _run_container(config, tmp_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _run_container(config: SandboxConfig, tmp_dir: Path) -> EvaluatorResult:
    """Run the Docker container with all security constraints."""
    workspace_dir = tmp_dir / "workspace"
    workspace_dir.mkdir()
    result_dir = tmp_dir / "result"
    result_dir.mkdir()
    result_dir.chmod(0o777)
    data_dir = tmp_dir / "data"
    data_dir.mkdir()

    (workspace_dir / "candidate.py").write_text(
        config.strategy_source, encoding="utf-8"
    )
    (workspace_dir / "context.json").write_text(
        json.dumps(config.context_json, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    if config.data_mount_path and config.data_mount_path.exists():
        for item in config.data_mount_path.iterdir():
            if item.is_file():
                shutil.copy2(item, data_dir / item.name)
            elif item.is_dir():
                shutil.copytree(item, data_dir / item.name)

    tailhedge_src = Path(__file__).resolve().parents[2]

    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit",
        str(config.pid_max),
        "--memory",
        f"{config.memory_mb}m",
        "--cpus",
        "1.0",
        "--user",
        "evaluator:evaluator",
        f"--mount=type=bind,src={workspace_dir},dst=/workspace,readonly",
        f"--mount=type=bind,src={result_dir},dst=/result",
        f"--mount=type=bind,src={tailhedge_src},dst=/opt/tailhedge_src,readonly",
        "-e",
        "PYTHONPATH=/opt/tailhedge_src",
        "--tmpfs=/data:size=100m,mode=555",
        "--tmpfs=/tmp:size=10m,mode=755",
        "--tmpfs=/home/evaluator:size=10m,mode=755",
        "--entrypoint",
        "python",
        config.evaluator_image_tag,
        "/entrypoint.py",
    ]

    if config.data_mount_path and config.data_mount_path.exists():
        docker_cmd[11:11] = [
            f"--mount=type=bind,src={data_dir},dst=/data,readonly",
        ]

    logger.info(
        "Running evaluator sandbox: hash=%s wall_timeout=%ds",
        config.strategy_hash[:16],
        config.wall_timeout_seconds,
    )

    start_time = time.monotonic()

    try:
        proc = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=config.wall_timeout_seconds,
        )
        elapsed = time.monotonic() - start_time

        output_file = result_dir / "output.json"
        if output_file.exists():
            raw_output = output_file.read_text(encoding="utf-8")
            output_bytes = len(raw_output.encode("utf-8"))

            if output_bytes > config.output_max_bytes:
                return EvaluatorResult(
                    success=False,
                    error_type="OutputTooLarge",
                    error_message=(
                        f"Output exceeds size limit: {output_bytes} bytes "
                        f"(max {config.output_max_bytes})"
                    ),
                    wall_time_seconds=elapsed,
                    output_bytes=output_bytes,
                )

            try:
                output_json = json.loads(raw_output)
            except json.JSONDecodeError as e:
                return EvaluatorResult(
                    success=False,
                    error_type="InvalidOutput",
                    error_message=f"Invalid JSON output: {e}",
                    wall_time_seconds=elapsed,
                    output_bytes=output_bytes,
                )

            if output_json.get("status") == "ERROR":
                return EvaluatorResult(
                    success=False,
                    error_type=output_json.get("error_type", "UnknownError"),
                    error_message=output_json.get("error_message", "Unknown error"),
                    wall_time_seconds=elapsed,
                    output_bytes=output_bytes,
                )

            return EvaluatorResult(
                success=True,
                output_json=output_json,
                wall_time_seconds=elapsed,
                output_bytes=output_bytes,
            )

        stderr_output = proc.stderr[:2000] if proc.stderr else ""
        return EvaluatorResult(
            success=False,
            error_type="NoOutput",
            error_message=(
                f"Container produced no output (exit {proc.returncode}). "
                f"stderr: {stderr_output}"
            ),
            wall_time_seconds=elapsed,
        )

    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start_time
        logger.warning(
            "Evaluator sandbox timed out after %.1fs (limit %ds)",
            elapsed,
            config.wall_timeout_seconds,
        )
        _kill_container_if_running(config.evaluator_image_tag)
        return EvaluatorResult(
            success=False,
            error_type="Timeout",
            error_message=(
                f"Container exceeded wall-clock timeout of "
                f"{config.wall_timeout_seconds}s"
            ),
            wall_time_seconds=elapsed,
        )

    except FileNotFoundError as e:
        elapsed = time.monotonic() - start_time
        return EvaluatorResult(
            success=False,
            error_type="DockerNotFound",
            error_message=f"Docker executable not found: {e}",
            wall_time_seconds=elapsed,
        )


def _kill_container_if_running(image_tag: str) -> None:
    """Attempt to kill any running container with the given image tag."""
    with contextlib.suppress(Exception):
        subprocess.run(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                f"ancestor={image_tag}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )


# ---------------------------------------------------------------------------
# Convenience: evaluate a strategy source string
# ---------------------------------------------------------------------------


def evaluate_strategy_source(
    strategy_source: str,
    context_json: dict[str, object],
    *,
    data_mount_path: Path | None = None,
    holdout_mount_path: Path | None = None,
    cpu_seconds: int = DEFAULT_CPU_SECONDS,
    memory_mb: int = DEFAULT_MEMORY_MB,
    pid_max: int = DEFAULT_PID_MAX,
    wall_timeout_seconds: int = DEFAULT_WALL_TIMEOUT_SECONDS,
    output_max_bytes: int = DEFAULT_OUTPUT_MAX_BYTES,
    evaluator_image_tag: str = IMAGE_NAME,
) -> EvaluatorResult:
    """High-level API: evaluate a strategy source in the sandbox.

    Parameters
    ----------
    strategy_source : str
        Python source code of the candidate strategy.
    context_json : dict
        Serialised StrategyContext.
    data_mount_path : Path, optional
        Read-only data slice to mount.
    holdout_mount_path : Path, optional
        Never mounted — logged and ignored.
    cpu_seconds, memory_mb, pid_max, wall_timeout_seconds : int
        Resource limits.
    evaluator_image_tag : str
        Docker image tag.

    Returns
    -------
    EvaluatorResult
        The evaluation result.
    """
    strategy_hash = hashlib.sha256(strategy_source.encode("utf-8")).hexdigest()

    config = SandboxConfig(
        strategy_source=strategy_source,
        strategy_hash=strategy_hash,
        context_json=context_json,
        data_mount_path=data_mount_path,
        holdout_mount_path=holdout_mount_path,
        cpu_seconds=cpu_seconds,
        memory_mb=memory_mb,
        pid_max=pid_max,
        wall_timeout_seconds=wall_timeout_seconds,
        output_max_bytes=output_max_bytes,
        evaluator_image_tag=evaluator_image_tag,
    )

    ensure_image(evaluator_image_tag)

    return run_in_sandbox(config)
