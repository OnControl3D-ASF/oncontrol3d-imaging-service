# OnControl Imaging Service — FastAPI lung-segmentation microservice.
#
# Multi-stage build:
#   1. builder  — installs dependencies into an isolated venv.
#   2. runtime  — slim image with only the interpreter, runtime libs, the venv
#                 and the app code. No pip/setuptools/wheel, non-root user.
#
# Base image choice: python:3.11-slim (Debian 13 "trixie") was measured with
# Trivy against gcr.io/distroless/python3-debian12 and -debian13. Distroless
# ships Debian's packaged CPython (libpython3.x) and, for debian12, an older
# OS baseline, so it reported MORE OS vulnerabilities (debian12: 427 incl. 2
# CRITICAL; debian13: 311) than python:3.11-slim (223, 0 CRITICAL). Distroless
# debian13 would also force Python 3.13 while CI and ruff target 3.11.

ARG PYTHON_IMAGE=python:3.11-slim

# ---------- Stage 1: build dependencies ----------
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Dependencies first for better layer caching.
COPY requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -r /tmp/requirements.txt \
    # Installers are not needed at runtime; removing them also removes their CVEs.
    && /opt/venv/bin/pip uninstall -y pip setuptools wheel

# ---------- Stage 2: runtime ----------
FROM ${PYTHON_IMAGE} AS runtime

# Runtime libs needed by scipy / scikit-image / SimpleITK wheels.
# The base interpreter's pip/setuptools/wheel are removed for the same reason.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall -y pip setuptools wheel \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY app ./app

# Storage for raw/derived volumes. Ephemeral inside the container; mount a
# persistent volume at /app/storage for durability.
ENV PATH=/opt/venv/bin:$PATH \
    STORAGE_DIR=/app/storage \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN mkdir -p /app/storage && chown app:app /app/storage

USER app

# The platform may inject $PORT; defaults to 8001 for local `docker run`.
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://localhost:' + os.getenv('PORT', '8001') + '/health', timeout=4)"]
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8001}"]
