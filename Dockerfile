FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY scripts/ ./scripts/

# Create data directory for SQLite
RUN mkdir -p /data

# Set environment variables
ENV DATABASE_URL=sqlite:////data/jobs.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Run the web app
CMD ["python", "-m", "uvicorn", "src.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
