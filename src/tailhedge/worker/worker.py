"""Worker CLI for processing jobs from the durable queue."""

from __future__ import annotations

import signal
import sys
import time
import uuid
from typing import TYPE_CHECKING, Any

from tailhedge.worker.job_queue import (
    JobClaimError,
    claim_job,
    complete_job,
    heartbeat_job,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class Worker:
    """Worker that processes jobs from the queue.

    Args:
        worker_id: Unique identifier for this worker
        job_handlers: Mapping of job type to handler function
        lease_seconds: Lease duration in seconds
        heartbeat_interval: Seconds between heartbeats
        poll_interval: Seconds between polling for jobs
    """

    def __init__(
        self,
        worker_id: str | None = None,
        job_handlers: dict[str, Callable[[dict[str, Any]], None]] | None = None,
        lease_seconds: int = 300,
        heartbeat_interval: int = 30,
        poll_interval: int = 5,
    ) -> None:
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.job_handlers = job_handlers or {}
        self.lease_seconds = lease_seconds
        self.heartbeat_interval = heartbeat_interval
        self.poll_interval = poll_interval
        self._running = False
        self._current_job_id: uuid.UUID | None = None
        self._current_job_type: str | None = None

    def register_handler(
        self, job_type: str, handler: Callable[[dict[str, Any]], None]
    ) -> None:
        """Register a handler for a job type.

        Args:
            job_type: Job type to handle
            handler: Function that takes job payload and processes it
        """
        self.job_handlers[job_type] = handler

    def stop(self) -> None:
        """Signal the worker to stop."""
        self._running = False

    def run(self, db_session_factory: Any) -> None:
        """Run the worker loop.

        Args:
            db_session_factory: Callable that returns a new database session
        """
        self._running = True

        # Handle signals for graceful shutdown
        def handle_signal(_signum: int, _frame: Any) -> None:
            self.stop()

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        print(f"Worker {self.worker_id} started")
        print(f"Registered handlers: {list(self.job_handlers.keys())}")

        last_heartbeat = time.time()

        while self._running:
            session = db_session_factory()
            try:
                # Heartbeat if we have a current job
                if (
                    self._current_job_id
                    and time.time() - last_heartbeat > self.heartbeat_interval
                ):
                    heartbeat_job(
                        session,
                        self._current_job_id,
                        self.worker_id,
                        self.lease_seconds,
                    )
                    last_heartbeat = time.time()

                # Try to claim a job
                try:
                    job = claim_job(
                        session, self.worker_id, lease_seconds=self.lease_seconds
                    )
                    self._current_job_id = job.id
                    self._current_job_type = job.type
                    last_heartbeat = time.time()

                    # Find handler
                    handler = self.job_handlers.get(job.type)
                    if handler is None:
                        complete_job(
                            session,
                            job.id,
                            self.worker_id,
                            success=False,
                            error_code="NO_HANDLER",
                            error_detail=f"No handler registered for job type: {job.type}",
                        )
                        self._current_job_id = None
                        self._current_job_type = None
                        continue

                    # Execute handler
                    try:
                        handler(job.payload_json or {})
                        complete_job(session, job.id, self.worker_id, success=True)
                    except Exception as e:
                        complete_job(
                            session,
                            job.id,
                            self.worker_id,
                            success=False,
                            error_code="HANDLER_ERROR",
                            error_detail=str(e)[:500],
                        )
                    finally:
                        self._current_job_id = None
                        self._current_job_type = None

                except JobClaimError:
                    # No jobs available, wait and retry
                    time.sleep(self.poll_interval)
                    continue

            except Exception as e:
                print(f"Worker error: {e}", file=sys.stderr)
                time.sleep(self.poll_interval)
            finally:
                session.close()

        print(f"Worker {self.worker_id} stopped")
