"""Durable job queue with lease, heartbeat, and retry mechanics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import and_, or_, select, update

from tailhedge.persistence.models import Job, JobAttempt

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session


class JobClaimError(Exception):
    """Raised when a job cannot be claimed."""


class JobNotFoundError(Exception):
    """Raised when a job is not found."""


class JobLeaseExpiredError(Exception):
    """Raised when a job lease has expired."""


def _close_dangling_attempts(
    session: Session,
    job_ids: list[uuid.UUID],
    now: datetime,
) -> None:
    """Close RUNNING attempts that belong to jobs no longer being processed."""
    if not job_ids:
        return
    session.execute(
        update(JobAttempt)
        .where(
            JobAttempt.job_id.in_(job_ids),
            JobAttempt.status == "RUNNING",
            JobAttempt.ended_at.is_(None),
        )
        .values(ended_at=now, status="INTERRUPTED")
    )


def _fail_exhausted_expired_leases(session: Session, now: datetime) -> list[uuid.UUID]:
    """Mark LEASED jobs with expired leases and no attempts left as FAILED."""
    stmt = (
        update(Job)
        .where(
            Job.status == "LEASED",
            Job.lease_expires_at.isnot(None),
            Job.lease_expires_at < now,
            Job.attempts >= Job.max_attempts,
        )
        .values(status="FAILED", lease_owner=None, lease_expires_at=None)
        .returning(Job.id)
    )
    exhausted_ids = list(session.execute(stmt).scalars().all())
    if exhausted_ids:
        _close_dangling_attempts(session, exhausted_ids, now)
        session.commit()
    return exhausted_ids


def claim_job(
    session: Session,
    worker_id: str,
    job_type: str | None = None,
    lease_seconds: int = 300,
) -> Job:
    """Claim the next available job for processing.

    Claimable jobs are PENDING (with no future ``run_after``) or LEASED
    with an expired lease. Jobs with an expired lease and no attempts
    remaining are marked FAILED instead of being re-claimed.

    Args:
        session: Database session
        worker_id: Unique identifier for the worker
        job_type: Optional filter by job type
        lease_seconds: How long the lease should last

    Returns:
        The claimed Job

    Raises:
        JobClaimError: If no jobs are available to claim
    """
    now = datetime.now(UTC)
    _fail_exhausted_expired_leases(session, now)

    claimable = or_(
        and_(
            Job.status == "PENDING",
            or_(Job.run_after.is_(None), Job.run_after <= now),
        ),
        and_(
            Job.status == "LEASED",
            Job.lease_expires_at.isnot(None),
            Job.lease_expires_at < now,
            Job.attempts < Job.max_attempts,
        ),
    )
    conditions = [claimable]
    if job_type:
        conditions.append(Job.type == job_type)

    # Order by priority (descending) and created_at (ascending)
    stmt = (
        select(Job)
        .where(and_(*conditions))
        .order_by(Job.priority.desc(), Job.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )

    job = session.execute(stmt).scalar_one_or_none()
    if job is None:
        raise JobClaimError("No jobs available to claim")

    was_leased = job.status == "LEASED"

    # Claim the job
    lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.status = "LEASED"
    job.lease_owner = worker_id
    job.lease_expires_at = lease_expires_at
    job.attempts += 1

    if was_leased:
        _close_dangling_attempts(session, [job.id], now)

    # Create a job attempt record
    attempt = JobAttempt(
        job_id=job.id,
        attempt_no=job.attempts,
        started_at=now,
        status="RUNNING",
    )
    session.add(attempt)
    session.commit()

    return job


def heartbeat_job(
    session: Session,
    job_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int = 300,
) -> None:
    """Extend the lease on a job (heartbeat).

    Args:
        session: Database session
        job_id: Job to heartbeat
        worker_id: Worker that owns the lease
        lease_seconds: New lease duration

    Raises:
        JobNotFoundError: If job doesn't exist
        JobLeaseExpiredError: If lease already expired or owned by another worker
    """
    stmt = select(Job).where(Job.id == job_id).with_for_update()
    job = session.execute(stmt).scalar_one_or_none()
    if job is None:
        raise JobNotFoundError(f"Job {job_id} not found")

    if job.lease_owner != worker_id:
        raise JobLeaseExpiredError(
            f"Job {job_id} is owned by {job.lease_owner}, not {worker_id}"
        )

    now = datetime.now(UTC)
    if job.lease_expires_at and job.lease_expires_at < now:
        raise JobLeaseExpiredError(f"Job {job_id} lease has expired")

    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    session.commit()


def complete_job(
    session: Session,
    job_id: uuid.UUID,
    worker_id: str,
    success: bool = True,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> None:
    """Mark a job as completed or failed.

    Args:
        session: Database session
        job_id: Job to complete
        worker_id: Worker that owns the lease
        success: Whether the job succeeded
        error_code: Optional error code if failed
        error_detail: Optional error detail if failed

    Raises:
        JobNotFoundError: If job doesn't exist
        JobLeaseExpiredError: If worker doesn't own the lease
    """
    stmt = select(Job).where(Job.id == job_id).with_for_update()
    job = session.execute(stmt).scalar_one_or_none()
    if job is None:
        raise JobNotFoundError(f"Job {job_id} not found")

    if job.lease_owner != worker_id:
        raise JobLeaseExpiredError(
            f"Job {job_id} is owned by {job.lease_owner}, not {worker_id}"
        )

    now = datetime.now(UTC)

    # Update the job attempt
    attempt_stmt = (
        select(JobAttempt)
        .where(
            and_(
                JobAttempt.job_id == job_id,
                JobAttempt.attempt_no == job.attempts,
            )
        )
        .with_for_update()
    )
    attempt = session.execute(attempt_stmt).scalar_one_or_none()
    if attempt:
        attempt.ended_at = now
        if success:
            attempt.status = "COMPLETED"
        else:
            attempt.status = "FAILED"
            attempt.error_code = error_code
            attempt.error_detail_redacted = error_detail

    # Update job status
    if success:
        job.status = "COMPLETED"
        job.lease_owner = None
        job.lease_expires_at = None
    else:
        # Check if we can retry
        if job.attempts < job.max_attempts:
            job.status = "PENDING"
            job.lease_owner = None
            job.lease_expires_at = None
            # Set run_after for exponential backoff
            backoff_seconds = min(300, 2**job.attempts * 10)
            job.run_after = now + timedelta(seconds=backoff_seconds)
        else:
            job.status = "FAILED"
            job.lease_owner = None
            job.lease_expires_at = None

    session.commit()


def recover_expired_leases(
    session: Session,
    worker_id: str | None = None,
) -> list[uuid.UUID]:
    """Recover jobs with expired leases.

    Jobs with attempts remaining are reset to PENDING; jobs with no
    attempts remaining are marked FAILED. Dangling RUNNING attempt
    records are closed as INTERRUPTED.

    Args:
        session: Database session
        worker_id: Optional filter by worker ID

    Returns:
        List of recovered (PENDING) job IDs
    """
    now = datetime.now(UTC)

    conditions = [
        Job.status == "LEASED",
        Job.lease_expires_at.isnot(None),
        Job.lease_expires_at < now,
    ]
    if worker_id:
        conditions.append(Job.lease_owner == worker_id)

    failed_stmt = (
        update(Job)
        .where(and_(*conditions), Job.attempts >= Job.max_attempts)
        .values(status="FAILED", lease_owner=None, lease_expires_at=None)
        .returning(Job.id)
    )
    failed_ids = list(session.execute(failed_stmt).scalars().all())

    recover_stmt = (
        update(Job)
        .where(and_(*conditions), Job.attempts < Job.max_attempts)
        .values(status="PENDING", lease_owner=None, lease_expires_at=None)
        .returning(Job.id)
    )
    recovered_ids = list(session.execute(recover_stmt).scalars().all())

    _close_dangling_attempts(session, failed_ids + recovered_ids, now)
    session.commit()

    return recovered_ids


def get_job(session: Session, job_id: uuid.UUID) -> Job | None:
    """Get a job by ID.

    Args:
        session: Database session
        job_id: Job ID

    Returns:
        Job if found, None otherwise
    """
    stmt = select(Job).where(Job.id == job_id)
    return session.execute(stmt).scalar_one_or_none()


def enqueue_job(
    session: Session,
    job_type: str,
    payload: dict[str, object] | None = None,
    unique_key: str | None = None,
    priority: int = 0,
    max_attempts: int = 3,
) -> Job:
    """Enqueue a new job.

    Args:
        session: Database session
        job_type: Type of job
        payload: Optional JSON payload
        unique_key: Optional unique key for deduplication
        priority: Job priority (higher = more urgent)
        max_attempts: Maximum number of retry attempts

    Returns:
        The created Job
    """
    job = Job(
        type=job_type,
        payload_json=payload,
        unique_key=unique_key,
        priority=priority,
        max_attempts=max_attempts,
        status="PENDING",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job
