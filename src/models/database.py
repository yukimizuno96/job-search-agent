import os
import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def generate_access_token() -> str:
    """Generate a secure random access token."""
    return secrets.token_urlsafe(32)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    access_token: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, default=generate_access_token, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    criteria: Mapped[list["UserCriteria"]] = relationship(
        "UserCriteria", back_populates="user", cascade="all, delete-orphan"
    )
    matched_jobs: Mapped[list["MatchedJob"]] = relationship(
        "MatchedJob", back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_users_email", "email"),)


class UserCriteria(Base):
    __tablename__ = "user_criteria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    keywords_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    locations_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    min_salary: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_salary: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    remote_preference: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user: Mapped["User"] = relationship("User", back_populates="criteria")

    __table_args__ = (Index("ix_user_criteria_user_id", "user_id"),)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    salary_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    salary_annual_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    salary_annual_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False)
    job_board: Mapped[str] = mapped_column(String(100), nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Deduplication fingerprint (hash of normalized title + company + job_board)
    fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # Job expiration tracking
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    matched_jobs: Mapped[list["MatchedJob"]] = relationship(
        "MatchedJob", back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_jobs_job_board", "job_board"),
        Index("ix_jobs_company", "company"),
        Index("ix_jobs_scraped_at", "scraped_at"),
        Index("ix_jobs_is_active", "is_active"),
        Index("ix_jobs_last_seen_at", "last_seen_at"),
    )


class MatchedJob(Base):
    __tablename__ = "matched_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id"), nullable=False)
    match_score: Mapped[float] = mapped_column(Float, nullable=False)
    matched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="matched_jobs")
    job: Mapped["Job"] = relationship("Job", back_populates="matched_jobs")

    __table_args__ = (
        Index("ix_matched_jobs_user_id", "user_id"),
        Index("ix_matched_jobs_job_id", "job_id"),
        Index("ix_matched_jobs_score", "match_score"),
        Index("ix_matched_jobs_user_job", "user_id", "job_id", unique=True),
    )


def get_database_url() -> str:
    """Get database URL from environment or use default."""
    return os.environ.get("DATABASE_URL", "sqlite:///jobs.db")


def get_engine(database_url: str = None):
    if database_url is None:
        database_url = get_database_url()
    return create_engine(database_url, echo=False)


def get_session(engine):
    Session = sessionmaker(bind=engine)
    return Session()


def init_db(database_url: str = None):
    if database_url is None:
        database_url = get_database_url()
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    return engine
