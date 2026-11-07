# ==============================================================================
# SolarSense — Backend Service Dockerfile (Render Web Service)
# ==============================================================================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install pinned Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only what is needed: backend service, model bundle, scripts, and config
COPY backend/ /app/backend/
COPY data/ /app/data/
COPY scripts/ /app/scripts/
COPY pyproject.toml /app/

# Expose default port
EXPOSE 8000

# Run Uvicorn ASGI server respecting dynamic $PORT from cloud platforms (e.g. Render)
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

