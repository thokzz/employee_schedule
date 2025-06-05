# Updated Dockerfile - preserving existing structure and adding backup support
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=run.py
ENV FLASK_ENV=production

WORKDIR /app

# Install system dependencies including wkhtmltopdf AND postgresql-client for backups
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    libpq-dev \
    curl \
    wkhtmltopdf \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create uploads directory and set permissions (PRESERVING EXISTING)
RUN mkdir -p app/static/uploads && \
    chmod -R 755 app/static/

# NEW: Create backup directory and set permissions
RUN mkdir -p /app/backups && \
    chmod -R 755 /app/backups

# Create non-root user (PRESERVING EXISTING)
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 5000

# Health check (PRESERVING EXISTING)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:5000/auth/login || exit 1

# Simple startup - just wait for DB and start app (PRESERVING EXISTING)
CMD ["sh", "-c", "while ! pg_isready -h db -p 5432 -U postgres; do sleep 1; done && gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 120 run:app"]