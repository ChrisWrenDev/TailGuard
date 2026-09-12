"""CLI entry point for the worker."""

from __future__ import annotations

import argparse
import sys

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

    for job_type in args.job_type:
        if job_type not in worker.job_handlers:
            print(
                f"Error: No handler registered for job type: {job_type}",
                file=sys.stderr,
            )
            return 1

    # TODO: Import and use real database session factory
    print("Worker CLI stub - database connection not yet implemented")
    print(f"Worker ID: {worker.worker_id}")
    print(f"Registered handlers: {list(worker.job_handlers.keys())}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
