#!/usr/bin/env python3
"""Add a new user to the job search system.

Usage:
    python scripts/add_user.py --name "John Doe" --email "john@example.com"
    python scripts/add_user.py -n "Jane Doe" -e "jane@example.com"
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.database import User, UserCriteria, get_engine, get_session


def add_user(name: str, email: str, base_url: str = "http://localhost:8000") -> None:
    """Create a new user and print their shareable URL."""
    engine = get_engine()
    session = get_session(engine)

    try:
        # Check if email already exists
        existing = session.query(User).filter(User.email == email).first()
        if existing:
            print(f"❌ Error: User with email '{email}' already exists")
            print(f"   Their dashboard URL: {base_url}/u/{existing.access_token}")
            sys.exit(1)

        # Create new user (access_token is auto-generated)
        user = User(name=name, email=email)
        session.add(user)
        session.commit()

        # Refresh to get the generated access_token
        session.refresh(user)

        # Create empty criteria for the user
        criteria = UserCriteria(user_id=user.id)
        session.add(criteria)
        session.commit()

        # Print success message
        print()
        print("=" * 60)
        print("✅ User created successfully!")
        print("=" * 60)
        print()
        print(f"  Name:  {user.name}")
        print(f"  Email: {user.email}")
        print()
        print("  Share this URL:")
        print(f"  {base_url}/u/{user.access_token}")
        print()
        print("  ⚠️  Keep this URL private!")
        print("  Anyone with this link can view and edit preferences.")
        print()
        print("=" * 60)

    except Exception as e:
        session.rollback()
        print(f"❌ Error creating user: {e}")
        sys.exit(1)
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description="Add a new user to the job search system"
    )
    parser.add_argument(
        "-n", "--name",
        required=True,
        help="User's display name"
    )
    parser.add_argument(
        "-e", "--email",
        required=True,
        help="User's email address"
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the web dashboard (default: http://localhost:8000)"
    )

    args = parser.parse_args()

    add_user(args.name, args.email, args.base_url)


if __name__ == "__main__":
    main()
