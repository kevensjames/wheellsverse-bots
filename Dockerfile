FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    libcurl4-openssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code (secrets stay out via .dockerignore)
COPY . .

# Create required directories
RUN mkdir -p outputs/content outputs/reports outputs/published \
    data memory logs projects /var/data

# Note: /var/data is mounted as a Railway persistent volume (configured in railway.json)
# Do NOT use VOLUME keyword — Railway bans it

# Expose default port (Railway/Render overrides with $PORT env var)
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=5 \
    CMD curl -f http://localhost:${PORT:-8080}/api/health || exit 1

# Environment defaults
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# main.py reads $PORT automatically via argparse default
CMD ["python", "main.py", "--dashboard"]
