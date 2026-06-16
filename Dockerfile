FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    libcurl4-openssl-dev \
    curl \
    ffmpeg \
    libopus0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app

# Build-time deploy fingerprint. Callers pass --build-arg GIT_SHA=<sha>;
# the docker-push.yml workflow sets this from ${{ github.sha }}. Falls
# back to 'unknown' when not passed — the runtime resolver in core/api.py
# then checks RAILWAY_GIT_COMMIT_SHA env, /app/GIT_SHA file, or git CLI.
ARG GIT_SHA=unknown
RUN echo "${GIT_SHA}" > /app/GIT_SHA && date -u +%Y-%m-%dT%H:%M:%SZ > /app/BUILD_TIME

RUN python -c "from core.api import app; print('[BUILD CHECK] core.api imports OK')"

RUN mkdir -p outputs/content outputs/reports outputs/published \
    data memory logs projects /var/data

EXPOSE 8080

ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["sh", "-c", "echo \"${RAILWAY_GIT_COMMIT_SHA:-${GIT_SHA:-$(cat /app/GIT_SHA 2>/dev/null || echo unknown)}}\" > /app/GIT_SHA && uvicorn core.api:app --host 0.0.0.0 --port $PORT"]
