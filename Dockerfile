FROM python:3.11-slim
# cache-bust: 2026-04-16-v2

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    libcurl4-openssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Layer 1: dependencies — only re-runs when requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Layer 2: app code — re-runs on every deploy (fast, no pip work)
COPY . .

# Add /app to PYTHONPATH so 'core.api' is importable regardless of CWD
ENV PYTHONPATH=/app

# Verify Python can import the app before the image is finalised
RUN python -c "from core.api import app; print('[BUILD CHECK] core.api imports OK')"

# Create required runtime directories
RUN mkdir -p outputs/content outputs/reports outputs/published \
    data memory logs projects /var/data

# Note: /var/data is mounted as a Railway persistent volume (configured in railway.json)
# Do NOT use VOLUME keyword — Railway bans it

# Expose default port (Railway/Render overrides with $PORT env var)
EXPOSE 8080

# Environment defaults
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["sh", "-c", "uvicorn core.api:app --host 0.0.0.0 --port $PORT"]
