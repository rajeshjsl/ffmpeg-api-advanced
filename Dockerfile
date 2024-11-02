FROM python:3.11-slim

# Install FFmpeg and curl (for healthcheck)
RUN apt-get update && \
    apt-get install -y ffmpeg curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directory for temporary files
RUN mkdir -p /tmp/ffmpeg_api && \
    chmod 777 /tmp/ffmpeg_api

# Set PYTHONPATH to ensure consistent module loading
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Create entrypoint script for Gunicorn
RUN echo '#!/bin/bash\n\
export PYTHONPATH=/app\n\
exec gunicorn \
    --bind 0.0.0.0:8000 \
    --workers ${GUNICORN_WORKERS:-2} \
    --threads ${GUNICORN_THREADS:-2} \
    --timeout ${GUNICORN_TIMEOUT:-600} \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    --pythonpath /app \
    "app:create_app()"' > /app/entrypoint.sh && \
    chmod +x /app/entrypoint.sh

# Create entrypoint script for Celery worker
RUN echo '#!/bin/bash\n\
export PYTHONPATH=/app\n\
exec celery -A app.celery worker \
    --loglevel=info \
    --concurrency=${CELERY_CONCURRENCY:-2}' > /app/worker-entrypoint.sh && \
    chmod +x /app/worker-entrypoint.sh

# Set other environment variables
ENV GUNICORN_WORKERS=2
ENV GUNICORN_THREADS=2
ENV GUNICORN_TIMEOUT=600
ENV CELERY_BROKER_URL=redis://redis:6379/0
ENV CELERY_RESULT_BACKEND=redis://redis:6379/0
ENV FFMPEG_TIMEOUT=0
ENV FFMPEG_THREADS=auto
ENV KEEP_FILES=false
ENV CLEANUP_INTERVAL=3600
ENV FILE_RETENTION_PERIOD=86400
ENV CELERY_CONCURRENCY=2

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# Default to API entrypoint, but allow override
ENTRYPOINT ["/app/entrypoint.sh"]