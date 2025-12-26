"""Job matching system for matching jobs to user criteria."""

import logging
import re
from dataclasses import dataclass, field

from src.models.database import Job, MatchedJob, User, UserCriteria, get_engine, get_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Scoring weights (must sum to 100)
WEIGHT_TITLE_KEYWORDS = 40
WEIGHT_DESCRIPTION_KEYWORDS = 30
WEIGHT_LOCATION = 15
WEIGHT_SALARY = 15


@dataclass
class MatchDetails:
    """Details about how a job matched user criteria."""
    title_keywords_matched: list[str] = field(default_factory=list)
    description_keywords_matched: list[str] = field(default_factory=list)
    location_matched: bool = False
    location_value: str | None = None
    salary_in_range: bool = False
    salary_value: tuple[int | None, int | None] = (None, None)

    # Individual scores
    title_score: int = 0
    description_score: int = 0
    location_score: int = 0
    salary_score: int = 0

    def to_dict(self) -> dict:
        return {
            "title_keywords_matched": self.title_keywords_matched,
            "description_keywords_matched": self.description_keywords_matched,
            "location_matched": self.location_matched,
            "location_value": self.location_value,
            "salary_in_range": self.salary_in_range,
            "salary_value": self.salary_value,
            "scores": {
                "title": self.title_score,
                "description": self.description_score,
                "location": self.location_score,
                "salary": self.salary_score,
            }
        }


@dataclass
class MatchSummary:
    """Summary of matching results for a user."""
    user_id: int
    total_jobs: int = 0
    jobs_matched: int = 0
    jobs_below_threshold: int = 0
    new_matches: int = 0
    existing_matches: int = 0


class JobMatcher:
    """Matches jobs to user criteria and calculates match scores."""

    def __init__(self):
        self.engine = get_engine()

    def _normalize_text(self, text: str | None) -> str:
        """Normalize text for matching (lowercase, strip whitespace)."""
        if not text:
            return ""
        # Convert to lowercase and normalize whitespace
        return re.sub(r'\s+', ' ', text.lower().strip())

    def _keyword_matches(self, text: str, keywords: list[str]) -> list[str]:
        """Find which keywords match in the text (partial match, case-insensitive).

        Args:
            text: Text to search in.
            keywords: List of keywords to find.

        Returns:
            List of keywords that were found in the text.
        """
        if not text or not keywords:
            return []

        normalized_text = self._normalize_text(text)
        matched = []

        for keyword in keywords:
            normalized_keyword = self._normalize_text(keyword)
            if normalized_keyword and normalized_keyword in normalized_text:
                matched.append(keyword)

        return matched

    def _location_matches(self, job_location: str | None, user_locations: list[str]) -> tuple[bool, str | None]:
        """Check if job location matches any user preferred locations.

        Args:
            job_location: Job's location string.
            user_locations: List of user's preferred locations.

        Returns:
            Tuple of (matched: bool, matched_location: str or None).
        """
        if not job_location or not user_locations:
            return False, None

        normalized_job_location = self._normalize_text(job_location)

        for location in user_locations:
            normalized_location = self._normalize_text(location)
            if normalized_location and normalized_location in normalized_job_location:
                return True, location

        return False, None

    def _salary_in_range(
        self,
        job_min: int | None,
        job_max: int | None,
        user_min: int | None,
        user_max: int | None,
    ) -> bool:
        """Check if job salary overlaps with user's desired range.

        Args:
            job_min: Job's minimum annual salary.
            job_max: Job's maximum annual salary.
            user_min: User's minimum desired salary.
            user_max: User's maximum desired salary.

        Returns:
            True if there's any overlap in ranges.
        """
        # If job has no salary info, we can't match
        if job_min is None and job_max is None:
            return False

        # If user has no salary preference, any salary matches
        if user_min is None and user_max is None:
            return True

        # Use available values for comparison
        job_low = job_min or job_max
        job_high = job_max or job_min
        user_low = user_min or 0
        user_high = user_max or float('inf')

        # Check for overlap: job range intersects with user range
        return job_low <= user_high and job_high >= user_low

    def match_job_to_user(self, job: Job, criteria: UserCriteria) -> tuple[int, MatchDetails]:
        """Calculate match score between a job and user criteria.

        Args:
            job: Job model instance.
            criteria: UserCriteria model instance.

        Returns:
            Tuple of (score: int 0-100, details: MatchDetails).
        """
        details = MatchDetails()

        # Get keywords from criteria (stored as JSON)
        keywords = criteria.keywords_json or []
        if isinstance(keywords, str):
            keywords = [keywords]

        # Get locations from criteria
        locations = criteria.locations_json or []
        if isinstance(locations, str):
            locations = [locations]

        # --- Title keyword matching (40%) ---
        if keywords:
            title_matches = self._keyword_matches(job.title, keywords)
            details.title_keywords_matched = title_matches
            # Score based on percentage of keywords matched
            match_ratio = len(title_matches) / len(keywords)
            details.title_score = int(match_ratio * WEIGHT_TITLE_KEYWORDS)

        # --- Description keyword matching (30%) ---
        if keywords:
            desc_matches = self._keyword_matches(job.description, keywords)
            # Don't count keywords already matched in title
            unique_desc_matches = [k for k in desc_matches if k not in details.title_keywords_matched]
            details.description_keywords_matched = unique_desc_matches
            # Score based on percentage of remaining keywords matched
            remaining_keywords = len(keywords) - len(details.title_keywords_matched)
            if remaining_keywords > 0:
                match_ratio = len(unique_desc_matches) / remaining_keywords
            else:
                # All keywords in title, give full description score as bonus
                match_ratio = 1.0 if desc_matches else 0.0
            details.description_score = int(match_ratio * WEIGHT_DESCRIPTION_KEYWORDS)

        # --- Location matching (15%) ---
        if locations:
            matched, matched_loc = self._location_matches(job.location, locations)
            details.location_matched = matched
            details.location_value = matched_loc
            details.location_score = WEIGHT_LOCATION if matched else 0

        # --- Salary matching (15%) ---
        salary_matched = self._salary_in_range(
            job.salary_annual_min,
            job.salary_annual_max,
            criteria.min_salary,
            criteria.max_salary,
        )
        details.salary_in_range = salary_matched
        details.salary_value = (job.salary_annual_min, job.salary_annual_max)
        details.salary_score = WEIGHT_SALARY if salary_matched else 0

        # Calculate total score
        total_score = (
            details.title_score +
            details.description_score +
            details.location_score +
            details.salary_score
        )

        return total_score, details

    def match_all_for_user(self, user_id: int, min_score: int = 50) -> MatchSummary:
        """Match all jobs against a user's criteria and save matches.

        Args:
            user_id: ID of the user to match jobs for.
            min_score: Minimum score threshold for saving matches (0-100).

        Returns:
            MatchSummary with statistics.
        """
        session = get_session(self.engine)
        summary = MatchSummary(user_id=user_id)

        try:
            # Get user and their criteria
            user = session.query(User).filter(User.id == user_id).first()
            if not user:
                logger.error(f"User {user_id} not found")
                return summary

            # Get the user's most recent criteria
            criteria = (
                session.query(UserCriteria)
                .filter(UserCriteria.user_id == user_id)
                .order_by(UserCriteria.updated_at.desc())
                .first()
            )
            if not criteria:
                logger.error(f"No criteria found for user {user_id}")
                return summary

            logger.info(f"Matching jobs for user: {user.name} (ID: {user_id})")
            logger.info(f"Keywords: {criteria.keywords_json}")
            logger.info(f"Locations: {criteria.locations_json}")
            logger.info(f"Salary range: {criteria.min_salary} - {criteria.max_salary}")

            # Get all jobs
            jobs = session.query(Job).all()
            summary.total_jobs = len(jobs)
            logger.info(f"Total jobs to match: {summary.total_jobs}")

            # Match each job
            for job in jobs:
                score, details = self.match_job_to_user(job, criteria)

                if score >= min_score:
                    summary.jobs_matched += 1

                    # Check if match already exists
                    existing_match = (
                        session.query(MatchedJob)
                        .filter(
                            MatchedJob.user_id == user_id,
                            MatchedJob.job_id == job.id
                        )
                        .first()
                    )

                    if existing_match:
                        # Update existing match score
                        existing_match.match_score = score / 100.0
                        summary.existing_matches += 1
                    else:
                        # Create new match
                        match = MatchedJob(
                            user_id=user_id,
                            job_id=job.id,
                            match_score=score / 100.0,  # Store as 0-1 float
                        )
                        session.add(match)
                        summary.new_matches += 1

                    logger.debug(
                        f"Match: {job.title[:40]} | Score: {score} | "
                        f"Title: {details.title_keywords_matched} | "
                        f"Location: {details.location_matched}"
                    )
                else:
                    summary.jobs_below_threshold += 1

            session.commit()

            logger.info("=" * 50)
            logger.info("MATCHING SUMMARY")
            logger.info("=" * 50)
            logger.info(f"Total jobs:        {summary.total_jobs}")
            logger.info(f"Jobs matched:      {summary.jobs_matched}")
            logger.info(f"Below threshold:   {summary.jobs_below_threshold}")
            logger.info(f"New matches saved: {summary.new_matches}")
            logger.info(f"Existing updated:  {summary.existing_matches}")

            return summary

        except Exception as e:
            session.rollback()
            logger.error(f"Error during matching: {e}")
            raise
        finally:
            session.close()

    def get_matches_for_user(self, user_id: int, limit: int = 20) -> list[dict]:
        """Get top matches for a user.

        Args:
            user_id: ID of the user.
            limit: Maximum number of matches to return.

        Returns:
            List of match dictionaries with job details.
        """
        session = get_session(self.engine)

        try:
            matches = (
                session.query(MatchedJob, Job)
                .join(Job)
                .filter(MatchedJob.user_id == user_id)
                .order_by(MatchedJob.match_score.desc())
                .limit(limit)
                .all()
            )

            results = []
            for match, job in matches:
                results.append({
                    "job_id": job.id,
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "salary_text": job.salary_text,
                    "salary_annual_min": job.salary_annual_min,
                    "salary_annual_max": job.salary_annual_max,
                    "url": job.url,
                    "job_board": job.job_board,
                    "match_score": int(match.match_score * 100),
                    "matched_at": match.matched_at.isoformat(),
                })

            return results

        finally:
            session.close()
