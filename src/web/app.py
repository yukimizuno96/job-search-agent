"""FastAPI web dashboard for job search agent."""

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.models.database import Job, MatchedJob, User, UserCriteria, get_engine, get_session, init_db
from src.matching.matcher import JobMatcher

app = FastAPI(title="Job Search Dashboard")


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    init_db()

# Templates directory
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def get_db_session():
    """Get a database session."""
    engine = get_engine()
    return get_session(engine)


def get_user_by_token(session, access_token: str) -> Optional[User]:
    """Get user by access token, returns None if not found."""
    return session.query(User).filter(User.access_token == access_token).first()


# =============================================================================
# Home Page
# =============================================================================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page - project description (no user list for privacy)."""
    session = get_db_session()
    try:
        # Get stats
        total_jobs = session.query(func.count(Job.id)).scalar()
        active_jobs = session.query(func.count(Job.id)).filter(Job.is_active == True).scalar()

        # Get job board counts
        by_board = (
            session.query(Job.job_board, func.count(Job.id))
            .group_by(Job.job_board)
            .all()
        )

        return templates.TemplateResponse("index.html", {
            "request": request,
            "stats": {
                "total_jobs": total_jobs,
                "active_jobs": active_jobs,
                "by_board": {board: count for board, count in by_board},
            },
        })
    finally:
        session.close()


# =============================================================================
# User Profile / Matches (accessed via access token)
# =============================================================================
@app.get("/u/{access_token}", response_class=HTMLResponse)
async def user_matches(
    request: Request,
    access_token: str,
    min_score: Optional[float] = Query(None, ge=0, le=100),
    job_board: Optional[str] = Query(None),
    sort: str = Query("score"),
):
    """User profile page - show matched jobs."""
    session = get_db_session()
    try:
        user = get_user_by_token(session, access_token)
        if not user:
            return HTMLResponse("Page not found", status_code=404)

        # Get user criteria
        criteria = session.query(UserCriteria).filter(
            UserCriteria.user_id == user.id
        ).first()

        # Build query for matched jobs
        query = (
            session.query(MatchedJob, Job)
            .join(Job, MatchedJob.job_id == Job.id)
            .filter(MatchedJob.user_id == user.id)
            .filter(Job.is_active == True)
        )

        # Apply filters
        if min_score is not None:
            query = query.filter(MatchedJob.match_score >= min_score)
        if job_board:
            query = query.filter(Job.job_board == job_board)

        # Apply sorting
        if sort == "score":
            query = query.order_by(MatchedJob.match_score.desc())
        elif sort == "date":
            query = query.order_by(Job.scraped_at.desc())
        elif sort == "company":
            query = query.order_by(Job.company)

        matches = query.all()

        # Get available job boards for filter dropdown
        job_boards = session.query(Job.job_board).distinct().all()
        job_boards = [jb[0] for jb in job_boards]

        return templates.TemplateResponse("user_matches.html", {
            "request": request,
            "user": user,
            "access_token": access_token,
            "criteria": criteria,
            "matches": matches,
            "job_boards": job_boards,
            "filters": {
                "min_score": min_score,
                "job_board": job_board,
                "sort": sort,
            },
        })
    finally:
        session.close()


@app.post("/u/{access_token}/run-matching")
async def run_matching(access_token: str):
    """Run job matching for a user."""
    session = get_db_session()
    try:
        user = get_user_by_token(session, access_token)
        if not user:
            return HTMLResponse("Page not found", status_code=404)

        matcher = JobMatcher()
        matcher.match_all_for_user(user.id, min_score=30)

        return RedirectResponse(f"/u/{access_token}", status_code=303)
    finally:
        session.close()


# =============================================================================
# User Settings (accessed via access token)
# =============================================================================
@app.get("/u/{access_token}/settings", response_class=HTMLResponse)
async def user_settings(request: Request, access_token: str, saved: Optional[str] = Query(None)):
    """User settings page - edit criteria."""
    session = get_db_session()
    try:
        user = get_user_by_token(session, access_token)
        if not user:
            return HTMLResponse("Page not found", status_code=404)

        criteria = session.query(UserCriteria).filter(
            UserCriteria.user_id == user.id
        ).first()

        # Parse JSON fields for display
        keywords = []
        locations = []
        if criteria:
            if criteria.keywords_json:
                keywords = criteria.keywords_json if isinstance(criteria.keywords_json, list) else []
            if criteria.locations_json:
                locations = criteria.locations_json if isinstance(criteria.locations_json, list) else []

        return templates.TemplateResponse("user_settings.html", {
            "request": request,
            "user": user,
            "access_token": access_token,
            "criteria": criteria,
            "keywords": keywords,
            "locations": locations,
            "saved": saved == "1",
        })
    finally:
        session.close()


@app.post("/u/{access_token}/settings")
async def update_settings(
    access_token: str,
    keywords: str = Form(""),
    locations: str = Form(""),
    min_salary: Optional[str] = Form(None),
    max_salary: Optional[str] = Form(None),
    remote_preference: Optional[str] = Form(None),
):
    """Update user criteria."""
    session = get_db_session()
    try:
        user = get_user_by_token(session, access_token)
        if not user:
            return HTMLResponse("Page not found", status_code=404)

        # Parse comma-separated inputs
        keywords_list = [k.strip() for k in keywords.split(",") if k.strip()]
        locations_list = [loc.strip() for loc in locations.split(",") if loc.strip()]

        # Get or create criteria
        criteria = session.query(UserCriteria).filter(
            UserCriteria.user_id == user.id
        ).first()

        if not criteria:
            criteria = UserCriteria(user_id=user.id)
            session.add(criteria)

        # Update fields
        criteria.keywords_json = keywords_list if keywords_list else None
        criteria.locations_json = locations_list if locations_list else None
        # Convert 万円 to 円 (multiply by 10000)
        criteria.min_salary = int(min_salary) * 10000 if min_salary else None
        criteria.max_salary = int(max_salary) * 10000 if max_salary else None
        criteria.remote_preference = remote_preference == "true" if remote_preference else None

        session.commit()

        return RedirectResponse(f"/u/{access_token}/settings?saved=1", status_code=303)
    finally:
        session.close()


# =============================================================================
# Browse Jobs
# =============================================================================
@app.get("/jobs", response_class=HTMLResponse)
async def browse_jobs(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=5, le=100),
    job_board: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    is_active: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    """Browse all scraped jobs with pagination and filters."""
    session = get_db_session()
    try:
        # Build query
        query = session.query(Job)

        # Apply filters
        if job_board:
            query = query.filter(Job.job_board == job_board)
        if location:
            query = query.filter(Job.location.ilike(f"%{location}%"))
        if is_active == "true":
            query = query.filter(Job.is_active == True)
        elif is_active == "false":
            query = query.filter(Job.is_active == False)
        if search:
            query = query.filter(
                (Job.title.ilike(f"%{search}%")) |
                (Job.company.ilike(f"%{search}%"))
            )

        # Get total count
        total = query.count()

        # Apply pagination
        query = query.order_by(Job.scraped_at.desc())
        query = query.offset((page - 1) * per_page).limit(per_page)
        jobs = query.all()

        # Calculate pagination info
        total_pages = (total + per_page - 1) // per_page

        # Get available job boards for filter dropdown
        job_boards = session.query(Job.job_board).distinct().all()
        job_boards = [jb[0] for jb in job_boards]

        return templates.TemplateResponse("jobs.html", {
            "request": request,
            "jobs": jobs,
            "job_boards": job_boards,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
            },
            "filters": {
                "job_board": job_board,
                "location": location,
                "is_active": is_active,
                "search": search,
            },
        })
    finally:
        session.close()


# =============================================================================
# API Endpoints
# =============================================================================
@app.get("/api/stats")
async def get_stats():
    """Get job statistics."""
    session = get_db_session()
    try:
        total_jobs = session.query(func.count(Job.id)).scalar()
        active_jobs = session.query(func.count(Job.id)).filter(Job.is_active == True).scalar()
        total_users = session.query(func.count(User.id)).scalar()
        total_matches = session.query(func.count(MatchedJob.id)).scalar()

        by_board = (
            session.query(Job.job_board, func.count(Job.id))
            .group_by(Job.job_board)
            .all()
        )

        return {
            "total_jobs": total_jobs,
            "active_jobs": active_jobs,
            "total_users": total_users,
            "total_matches": total_matches,
            "by_board": {board: count for board, count in by_board},
        }
    finally:
        session.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
