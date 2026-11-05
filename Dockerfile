# --- Frontend React (Vite) : compilé à chaque build de l'image (Dokploy inclus). ---
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    curl \
    gettext \
    binutils \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    libcairo2 \
    libcairo2-dev \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libglib2.0-0 \
    shared-mime-info \
    fonts-dejavu-core \
    # PR-REC : audio recording + transcription
    ffmpeg \
    libsndfile1 \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt
RUN mkdir -p /app/staticfiles /app/media /app/logs \
    && chmod -R 755 /app/staticfiles /app/media /app/logs

# Build React hors de /app : le compose monte le code (.:/app) par-dessus /app.
# Servi sous /app/ (index.html) et /static/frontend/ (après collectstatic).
COPY --from=frontend /build/dist /opt/devflow/frontend
ENV DEVFLOW_FRONTEND_DIST=/opt/devflow/frontend

COPY . /app/

RUN mkdir -p /app/staticfiles /app/media /app/logs

EXPOSE 8000