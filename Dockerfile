# AE Compass — standalone AppFoundry container.
# This image belongs to AE Compass only; it has no Vision application dependency.
FROM node:20-bookworm-slim AS frontend
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    AE_COMPASS_LIVE_SOURCES=0 \
    AE_COMPASS_DATA_DIR=/app/runtime-data \
    AE_COMPASS_STATE_DIR=/app/runtime-state
WORKDIR /app
COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt
COPY server ./server
COPY --from=frontend /app/dist/renderer ./dist/renderer
RUN mkdir -p /app/runtime-data /app/runtime-state
EXPOSE 8080
CMD ["sh", "-c", "gunicorn --bind=0.0.0.0:${PORT:-8080} --workers=2 --threads=4 --timeout=120 server.app:app"]
