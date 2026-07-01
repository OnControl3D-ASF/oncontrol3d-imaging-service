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

# App code.
COPY app ./app

# Storage for raw/derived volumes. On Render's free tier this is EPHEMERAL
# (wiped on redeploy/restart); attach a persistent disk here for durability.
ENV STORAGE_DIR=/app/storage
RUN mkdir -p /app/storage

# Render injects $PORT; default to 8001 for local `docker run`.
EXPOSE 8001
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8001}"]
