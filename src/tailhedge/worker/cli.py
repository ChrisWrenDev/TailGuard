"""CLI entry point for the worker."""

from __future__ import annotations

import argparse
import logging
import sys

from tailhedge.persistence.engine import get_session_factory
from tailhedge.worker.worker import Worker


def dummy_handler(payload: dict[str, object]) -> None:
    """Dummy job handler for testing."""
    print(f"Processing dummy job: {payload}")


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the worker CLI.

    Args:
        argv: Command line arguments (defaults to sys.argv)

    Returns:
        Exit code
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        prog="tailhedge-worker",
        description="TailHedge job worker",
    )
    parser.add_argument(
        "--worker-id",
        type=str,
        default=None,
        help="Worker ID (generated if not provided)",
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=300,
        help="Lease duration in seconds (default: 300)",
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=int,
        default=30,
        help="Heartbeat interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=5,
        help="Poll interval in seconds (default: 5)",
    )
    parser.add_argument(
        "--job-type",
        type=str,
        action="append",
        default=[],
        help="Job types to process (can be specified multiple times)",
    )
    parser.add_argument(
        "--dummy",
        action="store_true",
        help="Run with dummy job handler for testing",
    )

    args = parser.parse_args(argv)

    # Create worker
    worker = Worker(
        worker_id=args.worker_id,
        lease_seconds=args.lease_seconds,
        heartbeat_interval=args.heartbeat_interval,
        poll_interval=args.poll_interval,
    )

    # Register handlers
    if args.dummy:
        worker.register_handler("DUMMY", dummy_handler)

    if not worker.job_handlers:
        parser.error(
            "No handlers registered. Use --dummy or register handlers programmatically."
        )

    for job_type in args.job_type:
        if job_type not in worker.job_handlers:
            print(
                f"Error: No handler registered for job type: {job_type}",
                file=sys.stderr,
            )
            return 1

    try:
        session_factory = get_session_factory()
    except Exception as e:
        print(f"Error: Failed to configure database connection: {e}", file=sys.stderr)
        return 1

    try:
        worker.run(session_factory)
    except Exception as e:
        print(f"Error: Worker failed: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
