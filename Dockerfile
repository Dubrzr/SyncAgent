# SyncAgent Server Container Image
#
# Build:
#   docker build -t syncagent-server .
#
# Run:
#   docker run -d -p 8000:8000 \
#     -v syncagent-data:/data \
#     syncagent-server
#
# With S3 storage:
#   docker run -d -p 8000:8000 \
#     -v syncagent-data:/data \
#     -e SYNCAGENT_S3_BUCKET=your-bucket \
#     -e SYNCAGENT_S3_ENDPOINT=https://s3.region.ovh.net \
#     -e SYNCAGENT_S3_ACCESS_KEY=your-key \
#     -e SYNCAGENT_S3_SECRET_KEY=your-secret \
#     syncagent-server

FROM python:3.13-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ src/

# Install package with server dependencies
RUN pip install --no-cache-dir -e ".[server]"


FROM python:3.13-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 1000 -s /sbin/nologin syncagent

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy source code
COPY --from=builder /build/src /app/src
COPY --from=builder /build/pyproject.toml /app/

# Create data directories
RUN mkdir -p /data/storage /data/logs && \
    chown -R syncagent:syncagent /data /app

# Environment configuration
ENV SYNCAGENT_DB_PATH=/data/syncagent.db
ENV SYNCAGENT_LOG_PATH=/data/logs/syncagent-server.log
ENV SYNCAGENT_STORAGE_PATH=/data/storage
ENV SYNCAGENT_TRASH_RETENTION_DAYS=30
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Expose HTTP port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/health', timeout=5).raise_for_status()" || exit 1

# Run as non-root user
USER syncagent

# Run with uvicorn
CMD ["uvicorn", "syncagent.server.app:app", "--host", "0.0.0.0", "--port", "8000"]