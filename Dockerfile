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

# Runtime config
ENV DATA_DIR=/data
ENV PYTHONPATH=/app/backend

EXPOSE 8090

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
