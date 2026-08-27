# Stage 1: Build React frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts
COPY index.html vite.config.ts tsconfig.json tailwind.config.js postcss.config.js ./
COPY src/renderer/ src/renderer/
RUN npx vite build

# Stage 2: Python runtime
FROM python:3.11-slim
WORKDIR /app

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ server/
COPY --from=frontend-build /app/dist/renderer/ dist/renderer/

ENV PORT=8080
EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120", "--chdir", "server", "app:app"]
