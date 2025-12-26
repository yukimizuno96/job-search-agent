#!/usr/bin/env python3
"""Initialize database and add sample data for testing."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.database import (
    Base,
    Job,
    MatchedJob,
    User,
    UserCriteria,
    get_engine,
    get_session,
)


def init_db():
    """Create all tables and add sample data."""
    engine = get_engine()

    # Create all tables
    Base.metadata.create_all(engine)
    print("✓ Tables created")

    session = get_session(engine)

    try:
        # Check if sample user already exists
        existing_user = session.query(User).filter_by(email="test@example.com").first()
        if existing_user:
            print("✓ Sample user already exists (id={})".format(existing_user.id))
            return

        # Create sample user
        user = User(
            name="Test User",
            email="test@example.com"
        )
        session.add(user)
        session.flush()  # Get the user ID
        print("✓ Created user: {} ({})".format(user.name, user.email))

        # Create sample criteria
        criteria = UserCriteria(
            user_id=user.id,
            keywords_json=["python", "backend", "senior engineer", "remote"],
            locations_json=["Tokyo", "Remote", "San Francisco"],
            min_salary=100000,
            max_salary=200000,
            remote_preference=True
        )
        session.add(criteria)
        print("✓ Created search criteria:")
        print("  - Keywords: {}".format(criteria.keywords_json))
        print("  - Locations: {}".format(criteria.locations_json))
        print("  - Salary range: ${:,} - ${:,}".format(criteria.min_salary, criteria.max_salary))
        print("  - Remote preference: {}".format(criteria.remote_preference))

        # Create a sample job to test relationships
        job = Job(
            title="Senior Python Developer",
            company="Tech Corp",
            description="Looking for an experienced Python developer...",
            salary="$150,000 - $180,000",
            location="Remote",
            url="https://example.com/jobs/12345",
            job_board="indeed"
        )
        session.add(job)
        session.flush()
        print("✓ Created sample job: {} at {}".format(job.title, job.company))

        # Create a matched job entry
        matched = MatchedJob(
            user_id=user.id,
            job_id=job.id,
            match_score=0.85
        )
        session.add(matched)
        print("✓ Created match: user {} <-> job {} (score: {})".format(
            user.id, job.id, matched.match_score
        ))

        session.commit()
        print("\n✓ All sample data committed successfully!")

        # Verify by querying
        print("\n--- Verification ---")
        user = session.query(User).filter_by(email="test@example.com").first()
        print("User: {} (id={})".format(user.name, user.id))
        print("Criteria count: {}".format(len(user.criteria)))
        print("Matched jobs count: {}".format(len(user.matched_jobs)))

    except Exception as e:
        session.rollback()
        print("✗ Error: {}".format(e))
        raise
    finally:
        session.close()


if __name__ == "__main__":
    init_db()
