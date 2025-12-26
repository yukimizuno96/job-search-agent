# Job Search Agent

A job aggregator that scrapes Japanese job boards, matches listings against user preferences, and serves results through a web dashboard.

## Features

- **Multi-board scraping**: Green, Wantedly (with Playwright for JS-heavy sites)
- **Smart matching**: Scores jobs based on keywords, location, salary preferences
- **Web dashboard**: Browse jobs, set preferences, view personalized matches
- **Shareable URLs**: Each user gets a private access token URL
- **Deduplication**: Fingerprinting prevents duplicate job entries

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy, SQLite
- **Scraping**: BeautifulSoup, Playwright (headless browser)
- **Frontend**: Jinja2 templates, Tailwind CSS
- **Hosting**: Fly.io

## Setup

```bash
# Clone and install
git clone https://github.com/YOUR_USERNAME/job-search-agent.git
cd job-search-agent
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install Playwright browsers (for Wantedly scraper)
playwright install chromium
```

## Usage

### Run the scraper

```bash
# Using config file
python scripts/scrape_all_boards.py --config scraper_config.json

# Or with CLI options
python scripts/scrape_all_boards.py --keywords "デザイナー" --location "東京" --max-pages 10
```

### Start the web dashboard

```bash
python -m src.web.app
# Visit http://localhost:8000
```

### Add a user

```bash
python scripts/add_user.py --name "Name" --email "email@example.com"
# Returns a private URL for the user
```

## Project Structure

```
job-search-agent/
├── src/
│   ├── models/          # SQLAlchemy models (User, Job, MatchedJob)
│   ├── scrapers/        # Job board scrapers (Green, Wantedly, etc.)
│   ├── matching/        # Job matching algorithm
│   └── web/             # FastAPI app and templates
├── scripts/             # CLI utilities (scrape, add user)
├── scraper_config.json  # Scraper settings
├── Dockerfile           # Container config
└── fly.toml             # Fly.io deployment config
```

## Deployment (Fly.io)

```bash
# First time
fly launch --no-deploy
fly volumes create jobsearch_data --region nrt --size 1
fly deploy

# Upload database
./deploy_db.sh
```

## Configuration

Edit `scraper_config.json`:

```json
{
  "global": {
    "keywords": ["デザイナー"],
    "location": "東京",
    "max_pages": 20,
    "delay_range": [3.0, 5.0]
  },
  "scrapers": {
    "green": { "enabled": true },
    "wantedly": { "enabled": true }
  }
}
```

## License

MIT
