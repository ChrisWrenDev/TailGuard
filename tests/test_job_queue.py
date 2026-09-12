"""Integration tests for the durable job queue and worker (TASK-005)."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from tailhedge.persistence.models import Base, Job, JobAttempt
from tailhedge.worker.job_queue import (
    JobClaimError,
    JobLeaseExpiredError,
    claim_job,
    complete_job,
    enqueue_job,
    get_job,
    heartbeat_job,
    recover_expired_leases,
)
from tailhedge.worker.worker import Worker
from tests.integration import TEST_DATABASE_URL, requires_postgres

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable

    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

pytestmark = [requires_postgres]


def _fresh_factory() -> tuple[Engine, Callable[[], Session]]:
    """Drop/recreate the queue tables and return (engine, session factory)."""
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


class TestJobEnqueue:
    def test_enqueue_job_creates_pending_job(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB", payload={"key": "value"})

        assert job.id is not None
        assert job.type == "TEST_JOB"
        assert job.payload_json == {"key": "value"}
        assert job.status == "PENDING"
        assert job.attempts == 0
        assert job.max_attempts == 3

    def test_enqueue_job_with_unique_key(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB", unique_key="unique-123", priority=10)

        assert job.unique_key == "unique-123"
        assert job.priority == 10

    def test_enqueue_multiple_jobs(self, db_session: Session) -> None:
        enqueue_job(db_session, "JOB_A", priority=1)
        enqueue_job(db_session, "JOB_B", priority=2)
        enqueue_job(db_session, "JOB_C", priority=0)

        jobs = db_session.execute(select(Job)).scalars().all()
        assert len(jobs) == 3


class TestJobClaim:
    def test_claim_job_returns_pending_job(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB")
        claimed = claim_job(db_session, "worker-1")

        assert claimed.id == job.id
        assert claimed.status == "LEASED"
        assert claimed.lease_owner == "worker-1"
        assert claimed.lease_expires_at is not None
        assert claimed.attempts == 1

    def test_claim_job_respects_priority(self, db_session: Session) -> None:
        enqueue_job(db_session, "LOW", priority=0)
        enqueue_job(db_session, "HIGH", priority=10)
        enqueue_job(db_session, "MEDIUM", priority=5)

        claimed = claim_job(db_session, "worker-1")
        assert claimed.type == "HIGH"

    def test_claim_job_respects_fifo_within_priority(self, db_session: Session) -> None:
        job1 = enqueue_job(db_session, "SAME", priority=5)
        enqueue_job(db_session, "SAME", priority=5)

        claimed = claim_job(db_session, "worker-1")
        assert claimed.id == job1.id

    def test_claim_job_filters_by_type(self, db_session: Session) -> None:
        enqueue_job(db_session, "TYPE_A")
        job_b = enqueue_job(db_session, "TYPE_B")

        claimed = claim_job(db_session, "worker-1", job_type="TYPE_B")
        assert claimed.id == job_b.id

    def test_claim_job_raises_when_no_jobs(self, db_session: Session) -> None:
        with pytest.raises(JobClaimError, match="No jobs available"):
            claim_job(db_session, "worker-1")

    def test_claim_job_skips_leased_jobs(self, db_session: Session) -> None:
        enqueue_job(db_session, "TEST_JOB")
        claim_job(db_session, "worker-1", lease_seconds=300)

        # Second worker cannot claim the same job while the lease holds
        with pytest.raises(JobClaimError, match="No jobs available"):
            claim_job(db_session, "worker-2")

    def test_claim_job_reclaims_expired_lease(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB")
        claim_job(db_session, "worker-1", lease_seconds=1)

        time.sleep(1.1)

        claimed2 = claim_job(db_session, "worker-2")
        assert claimed2.id == job.id
        assert claimed2.lease_owner == "worker-2"
        assert claimed2.attempts == 2

    def test_claim_job_respects_run_after(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB")
        claim_job(db_session, "worker-1")
        complete_job(db_session, job.id, "worker-1", success=False)

        refreshed = get_job(db_session, job.id)
        assert refreshed is not None
        assert refreshed.status == "PENDING"
        assert refreshed.run_after is not None
        assert refreshed.run_after > datetime.now(UTC)

        # Backoff window: claim is refused until run_after elapses
        with pytest.raises(JobClaimError, match="No jobs available"):
            claim_job(db_session, "worker-2")

        db_session.execute(
            update(Job)
            .where(Job.id == job.id)
            .values(run_after=datetime.now(UTC) - timedelta(seconds=1))
        )
        db_session.commit()

        claimed = claim_job(db_session, "worker-2")
        assert claimed.id == job.id

    def test_claim_job_with_max_attempts(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB", max_attempts=1)
        claim_job(db_session, "worker-1")
        complete_job(db_session, job.id, "worker-1", success=False)

        # Job should be FAILED, not PENDING
        updated_job = get_job(db_session, job.id)
        assert updated_job is not None
        assert updated_job.status == "FAILED"


class TestJobHeartbeat:
    def test_heartbeat_extends_lease(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB")
        claimed = claim_job(db_session, "worker-1", lease_seconds=10)
        original_expires = claimed.lease_expires_at

        heartbeat_job(db_session, job.id, "worker-1", lease_seconds=20)

        updated_job = get_job(db_session, job.id)
        assert updated_job is not None
        assert updated_job.lease_expires_at is not None
        assert original_expires is not None
        assert updated_job.lease_expires_at > original_expires

    def test_heartbeat_rejects_wrong_worker(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB")
        claim_job(db_session, "worker-1")

        with pytest.raises(JobLeaseExpiredError, match="owned by worker-1"):
            heartbeat_job(db_session, job.id, "worker-2")

    def test_heartbeat_rejects_expired_lease(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB")
        claim_job(db_session, "worker-1", lease_seconds=1)

        time.sleep(1.1)

        with pytest.raises(JobLeaseExpiredError, match="lease has expired"):
            heartbeat_job(db_session, job.id, "worker-1")


class TestJobCompletion:
    def test_complete_job_success(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB")
        claim_job(db_session, "worker-1")

        complete_job(db_session, job.id, "worker-1", success=True)

        updated_job = get_job(db_session, job.id)
        assert updated_job is not None
        assert updated_job.status == "COMPLETED"
        assert updated_job.lease_owner is None
        assert updated_job.lease_expires_at is None

    def test_complete_job_with_retry(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB", max_attempts=3)
        claim_job(db_session, "worker-1")

        complete_job(db_session, job.id, "worker-1", success=False)

        updated_job = get_job(db_session, job.id)
        assert updated_job is not None
        assert updated_job.status == "PENDING"
        assert updated_job.attempts == 1
        assert updated_job.lease_owner is None
        assert updated_job.run_after is not None

    def test_complete_job_max_attempts_exceeded(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB", max_attempts=2)

        # First attempt
        claim_job(db_session, "worker-1")
        complete_job(db_session, job.id, "worker-1", success=False)

        # Clear the retry backoff so the second attempt can start immediately
        db_session.execute(
            update(Job)
            .where(Job.id == job.id)
            .values(run_after=datetime.now(UTC) - timedelta(seconds=1))
        )
        db_session.commit()

        # Second attempt
        claim_job(db_session, "worker-1")
        complete_job(db_session, job.id, "worker-1", success=False)

        updated_job = get_job(db_session, job.id)
        assert updated_job is not None
        assert updated_job.status == "FAILED"

    def test_complete_job_creates_attempt_record(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB")
        claim_job(db_session, "worker-1")

        complete_job(db_session, job.id, "worker-1", success=True)

        attempt = db_session.execute(
            select(JobAttempt).where(JobAttempt.job_id == job.id)
        ).scalar_one()

        assert attempt.attempt_no == 1
        assert attempt.status == "COMPLETED"
        assert attempt.started_at is not None
        assert attempt.ended_at is not None

    def test_complete_job_records_error(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB")
        claim_job(db_session, "worker-1")

        complete_job(
            db_session,
            job.id,
            "worker-1",
            success=False,
            error_code="TEST_ERROR",
            error_detail="Something went wrong",
        )

        attempt = db_session.execute(
            select(JobAttempt).where(JobAttempt.job_id == job.id)
        ).scalar_one()

        assert attempt.error_code == "TEST_ERROR"
        assert attempt.error_detail_redacted == "Something went wrong"

    def test_complete_job_rejects_wrong_worker(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB")
        claim_job(db_session, "worker-1")

        with pytest.raises(JobLeaseExpiredError, match="owned by worker-1"):
            complete_job(db_session, job.id, "worker-2", success=True)


class TestLeaseRecovery:
    def test_recover_expired_leases(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB")
        claim_job(db_session, "worker-1", lease_seconds=1)

        time.sleep(1.1)

        recovered = recover_expired_leases(db_session)
        assert len(recovered) == 1
        assert recovered[0] == job.id

        updated_job = get_job(db_session, job.id)
        assert updated_job is not None
        assert updated_job.status == "PENDING"
        assert updated_job.lease_owner is None

    def test_recover_marks_exhausted_jobs_failed(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB", max_attempts=1)
        claim_job(db_session, "worker-1", lease_seconds=1)

        time.sleep(1.1)

        recovered = recover_expired_leases(db_session)
        assert recovered == []

        updated_job = get_job(db_session, job.id)
        assert updated_job is not None
        assert updated_job.status == "FAILED"

    def test_recover_closes_dangling_attempts(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB")
        claim_job(db_session, "worker-1", lease_seconds=1)

        time.sleep(1.1)
        recover_expired_leases(db_session)

        attempts = (
            db_session.execute(select(JobAttempt).where(JobAttempt.job_id == job.id))
            .scalars()
            .all()
        )
        assert len(attempts) == 1
        assert attempts[0].status == "INTERRUPTED"
        assert attempts[0].ended_at is not None

    def test_reclaim_closes_dangling_attempts(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB")
        claim_job(db_session, "worker-1", lease_seconds=1)

        time.sleep(1.1)
        claim_job(db_session, "worker-2", lease_seconds=30)

        attempts = (
            db_session.execute(
                select(JobAttempt)
                .where(JobAttempt.job_id == job.id)
                .order_by(JobAttempt.attempt_no)
            )
            .scalars()
            .all()
        )
        assert len(attempts) == 2
        assert attempts[0].status == "INTERRUPTED"
        assert attempts[0].ended_at is not None
        assert attempts[1].status == "RUNNING"
        assert attempts[1].ended_at is None

    def test_reclaim_respects_max_attempts(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB", max_attempts=1)
        claim_job(db_session, "worker-1", lease_seconds=1)

        time.sleep(1.1)

        # The expired lease must not be reclaimed beyond max_attempts
        with pytest.raises(JobClaimError):
            claim_job(db_session, "worker-2")

        updated_job = get_job(db_session, job.id)
        assert updated_job is not None
        assert updated_job.status == "FAILED"

    def test_recover_expired_leases_by_worker(self, db_session: Session) -> None:
        job1 = enqueue_job(db_session, "JOB_1")
        job2 = enqueue_job(db_session, "JOB_2")

        claim_job(db_session, "worker-1", lease_seconds=1)
        claim_job(db_session, "worker-2", lease_seconds=100)

        time.sleep(1.1)

        # Only recover worker-1's jobs
        recovered = recover_expired_leases(db_session, worker_id="worker-1")
        assert len(recovered) == 1

        updated_job1 = get_job(db_session, job1.id)
        updated_job2 = get_job(db_session, job2.id)
        assert updated_job1 is not None
        assert updated_job2 is not None
        assert updated_job1.status == "PENDING"
        assert updated_job2.status == "LEASED"

    def test_recover_no_expired_leases(self, db_session: Session) -> None:
        enqueue_job(db_session, "TEST_JOB")
        claim_job(db_session, "worker-1", lease_seconds=300)

        recovered = recover_expired_leases(db_session)
        assert len(recovered) == 0


class TestConcurrentClaim:
    def test_only_one_worker_can_claim_same_job(self, db_session: Session) -> None:
        """Concurrent claim attempts across sessions yield one winner."""
        job = enqueue_job(db_session, "TEST_JOB")

        claimed1 = claim_job(db_session, "worker-1")
        assert claimed1.id == job.id

        # Second claim should fail while the lease holds
        with pytest.raises(JobClaimError):
            claim_job(db_session, "worker-2")

    def test_threaded_concurrent_claims_yield_single_winner(self) -> None:
        """True concurrency: 10 threads race for one job."""
        engine, factory = _fresh_factory()

        with factory() as s:
            job = enqueue_job(s, "RACE")

        winners: list[uuid.UUID] = []
        winners_lock = threading.Lock()

        def race(i: int) -> None:
            session = factory()
            try:
                claimed = claim_job(session, f"worker-{i}", lease_seconds=30)
                with winners_lock:
                    winners.append(claimed.id)
            except JobClaimError:
                pass
            finally:
                session.close()

        threads = [threading.Thread(target=race, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        engine.dispose()
        assert winners == [job.id]

    def test_multiple_jobs_can_be_claimed_concurrently(
        self, db_session: Session
    ) -> None:
        """Test that different jobs can be claimed by different workers."""
        job1 = enqueue_job(db_session, "JOB_1")
        job2 = enqueue_job(db_session, "JOB_2")
        job3 = enqueue_job(db_session, "JOB_3")

        claimed1 = claim_job(db_session, "worker-1")
        claimed2 = claim_job(db_session, "worker-2")
        claimed3 = claim_job(db_session, "worker-3")

        claimed_ids = {claimed1.id, claimed2.id, claimed3.id}
        assert claimed_ids == {job1.id, job2.id, job3.id}

    def test_job_becomes_available_after_completion(self, db_session: Session) -> None:
        """Test that a completed job slot allows new jobs to be claimed."""
        job1 = enqueue_job(db_session, "JOB_1")
        job2 = enqueue_job(db_session, "JOB_2")

        # Claim and complete first job
        claim_job(db_session, "worker-1")
        complete_job(db_session, job1.id, "worker-1", success=True)

        # Now second job can be claimed
        claimed2 = claim_job(db_session, "worker-1")
        assert claimed2.id == job2.id


class TestWorkerLoop:
    def test_worker_processes_job_end_to_end(self) -> None:
        """Worker loop claims, processes, and completes an enqueued job."""
        engine, factory = _fresh_factory()

        processed: list[dict[str, Any]] = []
        done = threading.Event()

        def handler(payload: dict[str, Any]) -> None:
            processed.append(payload)
            done.set()

        worker = Worker(
            worker_id="w-e2e",
            lease_seconds=30,
            heartbeat_interval=5,
            poll_interval=0.1,
        )
        worker.register_handler("DUMMY", handler)

        thread = threading.Thread(target=worker.run, args=(factory,), daemon=True)
        thread.start()
        try:
            with factory() as s:
                job = enqueue_job(s, "DUMMY", payload={"x": 1})

            assert done.wait(timeout=10)
            assert processed == [{"x": 1}]

            deadline = time.time() + 10
            while time.time() < deadline:
                with factory() as s:
                    refreshed = get_job(s, job.id)
                if refreshed is not None and refreshed.status == "COMPLETED":
                    break
                time.sleep(0.05)

            with factory() as s:
                refreshed = get_job(s, job.id)
                assert refreshed is not None
                assert refreshed.status == "COMPLETED"
                attempt = s.execute(
                    select(JobAttempt).where(JobAttempt.job_id == job.id)
                ).scalar_one()
                assert attempt.status == "COMPLETED"
        finally:
            worker.stop()
            thread.join(timeout=5)
            engine.dispose()

    def test_worker_heartbeats_during_long_handler(self) -> None:
        """The heartbeat thread keeps the lease alive while a handler runs.

        The handler runs for 4s with a 2s lease; without a working
        heartbeat the lease expires mid-handler, the job is reclaimed,
        and attempts would exceed 1.
        """
        engine, factory = _fresh_factory()

        def slow_handler(_payload: dict[str, Any]) -> None:
            time.sleep(4)

        worker = Worker(
            worker_id="w-hb",
            lease_seconds=2,
            heartbeat_interval=1,
            poll_interval=0.1,
        )
        worker.register_handler("SLOW", slow_handler)

        thread = threading.Thread(target=worker.run, args=(factory,), daemon=True)
        thread.start()
        try:
            with factory() as s:
                job = enqueue_job(s, "SLOW", payload={})

            deadline = time.time() + 15
            while time.time() < deadline:
                with factory() as s:
                    refreshed = get_job(s, job.id)
                if refreshed is not None and refreshed.status == "COMPLETED":
                    break
                time.sleep(0.1)

            with factory() as s:
                refreshed = get_job(s, job.id)
                assert refreshed is not None
                assert refreshed.status == "COMPLETED"
                assert refreshed.attempts == 1
        finally:
            worker.stop()
            thread.join(timeout=5)
            engine.dispose()
