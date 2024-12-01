FROM linuxserver/ffmpeg:version-7.1-cli

# Set non-interactive mode for apt-get
ENV DEBIAN_FRONTEND=noninteractive

# Install necessary dependencies and Python 3.11
RUN apt-get update && \
    apt-get install -y \
    software-properties-common \
    curl \
    lsb-release \
    && add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    python3-apt \
    libapt-pkg-dev \
    build-essential \
    git \    
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install pip for Python 3.11 using get-pip.py
RUN curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \
    python3.11 get-pip.py && \
    rm get-pip.py

# Set Python 3.11 as the default Python version
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# Create symlink for pip
RUN ln -s /usr/local/bin/pip3.11 /usr/bin/pip3.11

# Manually build and install python-apt to ensure compatibility
RUN cd /tmp && \
    git clone https://salsa.debian.org/apt-team/python-apt.git && \
    cd python-apt && \
    python3.11 setup.py build && \
    python3.11 setup.py install && \
    cd .. && \
    rm -rf python-apt

# Accept MS fonts license before installing
RUN echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections && \
    apt-get update && \
    apt-get install -y ttf-mscorefonts-installer fontconfig && \
    fc-cache -fv && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN fc-cache -fv

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip3.11 install --no-cache-dir -r requirements.txt

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
ENV KEEP_OUTPUT_FILES=false
ENV CELERY_CONCURRENCY=2

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# Default to API entrypoint, but allow override
ENTRYPOINT ["/app/entrypoint.sh"]