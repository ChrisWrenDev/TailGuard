"""Worker loop for processing jobs from the durable queue."""

from __future__ import annotations

import logging
import signal
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any

from tailhedge.worker.job_queue import (
    JobClaimError,
    JobLeaseExpiredError,
    JobNotFoundError,
    claim_job,
    complete_job,
    heartbeat_job,
    recover_expired_leases,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class Worker:
    """Worker that processes jobs from the queue.

    A daemon thread heartbeats the current job every ``heartbeat_interval``
    seconds so long-running handlers do not lose their lease. Expired
    leases are recovered automatically when the worker is idle.

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
        heartbeat_interval: float = 30,
        poll_interval: float = 5,
    ) -> None:
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.job_handlers = job_handlers or {}
        self.lease_seconds = lease_seconds
        self.heartbeat_interval = heartbeat_interval
        self.poll_interval = poll_interval
        self._running = False
        self._lock = threading.Lock()
        self._current_job_id: uuid.UUID | None = None
        self._session_factory: Callable[[], Session] | None = None

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

    def _heartbeat_loop(self) -> None:
        """Extend the lease on the current job at a fixed interval."""
        while self._running:
            time.sleep(self.heartbeat_interval)
            if not self._running:
                break
            with self._lock:
                job_id = self._current_job_id
            if job_id is None or self._session_factory is None:
                continue
            session = self._session_factory()
            try:
                heartbeat_job(session, job_id, self.worker_id, self.lease_seconds)
            except (JobLeaseExpiredError, JobNotFoundError) as e:
                logger.warning("Heartbeat failed for job %s: %s", job_id, e)
            except Exception:
                logger.exception("Unexpected heartbeat error for job %s", job_id)
            finally:
                session.close()

    def run(self, db_session_factory: Callable[[], Session]) -> None:
        """Run the worker loop until stopped.

        Args:
            db_session_factory: Callable that returns a new database session
        """
        self._running = True
        self._session_factory = db_session_factory

        if threading.current_thread() is threading.main_thread():

            def handle_signal(_signum: int, _frame: Any) -> None:
                self.stop()

            signal.signal(signal.SIGINT, handle_signal)
            signal.signal(signal.SIGTERM, handle_signal)

        logger.info("Worker %s started", self.worker_id)
        logger.info("Registered handlers: %s", list(self.job_handlers.keys()))

        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name="heartbeat", daemon=True
        )
        heartbeat_thread.start()

        try:
            while self._running:
                session = db_session_factory()
                try:
                    self._process_one(session)
                except Exception:
                    logger.exception("Worker error")
                    time.sleep(self.poll_interval)
                finally:
                    session.close()
        finally:
            self._running = False
            heartbeat_thread.join(timeout=self.heartbeat_interval + 1)
            logger.info("Worker %s stopped", self.worker_id)

    def _process_one(self, session: Session) -> None:
        """Claim and process a single job, or wait if none are available."""
        try:
            job = claim_job(session, self.worker_id, lease_seconds=self.lease_seconds)
        except JobClaimError:
            # No jobs available; recover expired leases while idle
            try:
                recover_expired_leases(session)
            except Exception:
                logger.exception("Lease recovery failed")
            time.sleep(self.poll_interval)
            return

        with self._lock:
            self._current_job_id = job.id

        try:
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
                return

            try:
                handler(job.payload_json or {})
            except Exception as e:
                logger.exception("Handler failed for job %s", job.id)
                complete_job(
                    session,
                    job.id,
                    self.worker_id,
                    success=False,
                    error_code="HANDLER_ERROR",
                    error_detail=str(e)[:500],
                )
            else:
                complete_job(session, job.id, self.worker_id, success=True)
        finally:
            with self._lock:
                self._current_job_id = None
