#!/usr/bin/env python3
"""Job maintenance utilities.

Commands:
    backfill-fingerprints  Generate fingerprints for jobs that don't have one
    mark-stale             Mark jobs as inactive if not seen for X days
    stats                  Show job statistics

Usage:
    python scripts/job_maintenance.py backfill-fingerprints
    python scripts/job_maintenance.py mark-stale --days 7
    python scripts/job_maintenance.py stats
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.database import get_engine, get_session
from src.models.job_utils import (
    backfill_fingerprints,
    get_job_stats,
    mark_stale_jobs_inactive,
)


def cmd_backfill_fingerprints(args):
    """Backfill fingerprints for existing jobs."""
    engine = get_engine()
    session = get_session(engine)

    try:
        count = backfill_fingerprints(session)
        print(f"Backfilled fingerprints for {count} jobs")
    finally:
        session.close()


def cmd_mark_stale(args):
    """Mark stale jobs as inactive."""
    engine = get_engine()
    session = get_session(engine)

    try:
        count = mark_stale_jobs_inactive(
            session,
            days_threshold=args.days,
            job_board=args.board,
        )
        print(f"Marked {count} jobs as inactive (not seen in {args.days} days)")
    finally:
        session.close()


def cmd_stats(args):
    """Show job statistics."""
    engine = get_engine()
    session = get_session(engine)

    try:
        stats = get_job_stats(session)

        print("\n" + "=" * 40)
        print("JOB STATISTICS")
        print("=" * 40)
        print(f"Total jobs:    {stats['total']}")
        print(f"Active jobs:   {stats['active']}")
        print(f"Inactive jobs: {stats['inactive']}")

        if stats['by_board']:
            print("\nBy Job Board:")
            print("-" * 40)
            print(f"{'Board':<15} {'Active':<10} {'Inactive':<10}")
            print("-" * 40)
            for board, counts in sorted(stats['by_board'].items()):
                print(f"{board:<15} {counts['active']:<10} {counts['inactive']:<10}")

        print("=" * 40 + "\n")

    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description="Job maintenance utilities"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # backfill-fingerprints
    parser_backfill = subparsers.add_parser(
        "backfill-fingerprints",
        help="Generate fingerprints for jobs that don't have one"
    )
    parser_backfill.set_defaults(func=cmd_backfill_fingerprints)

    # mark-stale
    parser_stale = subparsers.add_parser(
        "mark-stale",
        help="Mark jobs as inactive if not seen for X days"
    )
    parser_stale.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days threshold (default: 7)"
    )
    parser_stale.add_argument(
        "--board",
        type=str,
        help="Only process jobs from this board"
    )
    parser_stale.set_defaults(func=cmd_mark_stale)

    # stats
    parser_stats = subparsers.add_parser(
        "stats",
        help="Show job statistics"
    )
    parser_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
