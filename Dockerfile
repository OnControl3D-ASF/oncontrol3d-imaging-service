# OnControl Imaging Service — FastAPI lung-segmentation microservice.
# Deployable as a Docker web service on Render (or Azure Container Apps).
FROM python:3.11-slim

WORKDIR /app

# Runtime libs needed by scipy / scikit-image / SimpleITK wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Installers are not needed at runtime; removing them also removes their vulnerabilities.
RUN python -m pip uninstall -y pip setuptools wheel

# App code.
COPY app ./app

# Storage for raw/derived volumes. On Render's free tier this is EPHEMERAL
# (wiped on redeploy/restart); attach a persistent disk here for durability.
ENV STORAGE_DIR=/app/storage
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/storage \
    && chown app:app /app/storage

USER app

# Render injects $PORT; default to 8001 for local `docker run`.
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://localhost:' + os.getenv('PORT', '8001') + '/health', timeout=4)"]
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8001}"]
