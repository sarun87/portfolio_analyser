# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
# Build locally for the current architecture (Apple Silicon, ARM Linux, or x86 Linux):
#   docker build --tag portfolio-analyser:latest .
# Publish a multi-architecture image (requires a configured buildx builder and registry access):
#   docker buildx build --platform linux/amd64,linux/arm64 --tag <registry>/portfolio-analyser:latest --push .

FROM node:22-bookworm-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY LICENSE ./LICENSE
COPY THIRD_PARTY_NOTICES.md ./THIRD_PARTY_NOTICES.md
COPY backend/requirements.txt ./backend/requirements.txt
RUN python -m pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend-build /build/frontend/dist ./frontend/dist

RUN addgroup --gid 10001 portfolio \
    && adduser --uid 10001 --gid 10001 --disabled-password --gecos "" portfolio \
    && mkdir -p /app/data /app/logs \
    && chown -R portfolio:portfolio /app/data /app/logs

USER portfolio

EXPOSE 8000
VOLUME ["/app/data", "/app/logs"]

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
