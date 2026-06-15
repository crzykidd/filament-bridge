# Stage 1 — build the React SPA
FROM node:22-alpine AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2 — runtime image
FROM python:3.12-slim-bookworm

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ ./backend/

# Copy built frontend into the location main.py looks for: /app/static/
COPY --from=frontend-builder /build/dist ./static/

# Copy repo docs so /docs-md/<slug>.md is serveable by the SPA fallback
COPY docs/ ./static/docs-md/

# Runtime config
ENV DATA_DIR=/data
ENV PYTHONPATH=/app/backend
ENV PYTHONDONTWRITEBYTECODE=1

# Install gosu for privilege drop in entrypoint
RUN apt-get update && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and own /app and /data
RUN groupadd -g 1000 app && useradd -u 1000 -g 1000 -m -s /usr/sbin/nologin app \
    && mkdir -p /data && chown -R 1000:1000 /data \
    && chown -R 1000:1000 /app

# Entrypoint chowns /data then drops to PUID:PGID (default 1000:1000) via gosu
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Build-channel and git-commit baked in near the end so they don't bust earlier cache layers.
# Stamp with: BUILD_CHANNEL=dev GIT_COMMIT=$(git rev-parse --short HEAD) docker build ...
ARG BUILD_CHANNEL=release
ARG GIT_COMMIT=""
ENV BRIDGE_CHANNEL=$BUILD_CHANNEL \
    BRIDGE_COMMIT=$GIT_COMMIT

EXPOSE 8090

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
