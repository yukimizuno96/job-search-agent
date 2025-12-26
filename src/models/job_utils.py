"""Job utility functions for deduplication and expiration."""

import hashlib
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from .database import Job


def normalize_text(text: str | None) -> str:
    """Normalize text for fingerprint generation.

    - Lowercase
    - Remove extra whitespace
    - Remove common variations (株式会社 position, etc.)
    """
    if not text:
        return ""

    text = text.lower().strip()

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)

    # Normalize company name variations
    # Move 株式会社 to consistent position (or remove for comparison)
    text = re.sub(r"^株式会社\s*", "", text)
    text = re.sub(r"\s*株式会社$", "", text)

    # Remove common punctuation variations
    text = re.sub(r"[【】\[\]（）\(\)「」『』]", "", text)

    return text.strip()


def generate_fingerprint(title: str, company: str, job_board: str) -> str:
    """Generate a fingerprint hash for deduplication.

    Args:
        title: Job title.
        company: Company name.
        job_board: Job board source.

    Returns:
        SHA256 hash (first 16 chars) of normalized title + company + job_board.
    """
    normalized = "|".join([
        normalize_text(title),
        normalize_text(company),
        job_board.lower().strip(),
    ])

    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def find_duplicate_job(
    session: Session,
    url: str,
    fingerprint: str,
) -> Job | None:
    """Find existing job by URL or fingerprint.

    Args:
        session: Database session.
        url: Job URL.
        fingerprint: Job fingerprint.

    Returns:
        Existing Job if found, None otherwise.
    """
    # Check by URL first (exact match)
    job = session.query(Job).filter(Job.url == url).first()
    if job:
        return job

    # Check by fingerprint (fuzzy match)
    job = session.query(Job).filter(Job.fingerprint == fingerprint).first()
    if job:
        return job

    return None


def update_job_seen(job: Job, session: Session) -> None:
    """Update last_seen_at timestamp for an existing job.

    Args:
        job: The job to update.
        session: Database session.
    """
    job.last_seen_at = datetime.now(timezone.utc)
    job.is_active = True  # Re-activate if it was marked inactive


def mark_stale_jobs_inactive(
    session: Session,
    days_threshold: int = 7,
    job_board: str | None = None,
) -> int:
    """Mark jobs as inactive if not seen for X days.

    Args:
        session: Database session.
        days_threshold: Number of days after which to mark inactive.
        job_board: Optional - only process jobs from this board.

    Returns:
        Number of jobs marked inactive.
    """
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_threshold)

    query = (
        update(Job)
        .where(Job.is_active == True)
        .where(Job.last_seen_at < cutoff_date)
    )

    if job_board:
        query = query.where(Job.job_board == job_board)

    query = query.values(is_active=False)

    result = session.execute(query)
    session.commit()

    return result.rowcount


def backfill_fingerprints(session: Session) -> int:
    """Backfill fingerprints for existing jobs that don't have one.

    Args:
        session: Database session.

    Returns:
        Number of jobs updated.
    """
    jobs = session.query(Job).filter(Job.fingerprint.is_(None)).all()

    for job in jobs:
        job.fingerprint = generate_fingerprint(job.title, job.company, job.job_board)

    session.commit()
    return len(jobs)


def get_job_stats(session: Session) -> dict:
    """Get job statistics.

    Returns:
        Dictionary with job counts by status and board.
    """
    from sqlalchemy import func

    total = session.query(func.count(Job.id)).scalar()
    active = session.query(func.count(Job.id)).filter(Job.is_active == True).scalar()
    inactive = session.query(func.count(Job.id)).filter(Job.is_active == False).scalar()

    by_board = (
        session.query(Job.job_board, Job.is_active, func.count(Job.id))
        .group_by(Job.job_board, Job.is_active)
        .all()
    )

    board_stats = {}
    for board, is_active, count in by_board:
        if board not in board_stats:
            board_stats[board] = {"active": 0, "inactive": 0}
        if is_active:
            board_stats[board]["active"] = count
        else:
            board_stats[board]["inactive"] = count

    return {
        "total": total,
        "active": active,
        "inactive": inactive,
        "by_board": board_stats,
    }
