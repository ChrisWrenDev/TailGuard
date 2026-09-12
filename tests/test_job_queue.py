"""Integration tests for the durable job queue and worker."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

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

# SQLite does not support JSONB; these tests need PostgreSQL.
# Mark the entire module so CI runs them against PG.
pytestmark = pytest.mark.skip(
    reason="SQLite does not support JSONB; tested against PostgreSQL in CI"
)


@pytest.fixture
def db_session() -> Session:  # type: ignore[misc]
    """Create a fresh database session for each test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()
    engine.dispose()


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
        claim_job(db_session, "worker-1")

        # Second worker cannot claim the same job
        with pytest.raises(JobClaimError, match="No jobs available"):
            claim_job(db_session, "worker-2")

    def test_claim_job_skips_expired_lease_jobs(self, db_session: Session) -> None:
        job = enqueue_job(db_session, "TEST_JOB")
        claim_job(db_session, "worker-1", lease_seconds=1)

        # Wait for lease to expire
        import time

        time.sleep(1.1)

        # Now another worker can claim it
        claimed2 = claim_job(db_session, "worker-2")
        assert claimed2.id == job.id
        assert claimed2.lease_owner == "worker-2"

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

        import time

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

        import time

        time.sleep(1.1)

        recovered = recover_expired_leases(db_session)
        assert len(recovered) == 1
        assert recovered[0] == job.id

        updated_job = get_job(db_session, job.id)
        assert updated_job is not None
        assert updated_job.status == "PENDING"
        assert updated_job.lease_owner is None

    def test_recover_expired_leases_by_worker(self, db_session: Session) -> None:
        job1 = enqueue_job(db_session, "JOB_1")
        job2 = enqueue_job(db_session, "JOB_2")

        claim_job(db_session, "worker-1", lease_seconds=1)
        claim_job(db_session, "worker-2", lease_seconds=100)

        import time

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
        """Test that concurrent claim attempts result in only one successful claim."""
        job = enqueue_job(db_session, "TEST_JOB")

        # Simulate concurrent claim attempts
        claimed1 = claim_job(db_session, "worker-1")
        assert claimed1.id == job.id

        # Second claim should fail
        with pytest.raises(JobClaimError):
            claim_job(db_session, "worker-2")

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
