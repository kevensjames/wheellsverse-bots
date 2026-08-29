# Dedicated production-observability monitor — minimal, pure-stdlib image.
# Build context = repo ROOT (set RAILWAY_DOCKERFILE_PATH=ops/monitor/Dockerfile).
# Runs ONE scheduled tick and exits (Railway cron service invokes it on a schedule).
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# Only two source trees are needed — the monitor package and the (pure-stdlib) session minter.
COPY core/operator_session.py /app/core/operator_session.py
COPY ops /app/ops
# No pip install: the monitor uses only the Python standard library.
# Default command is one cron tick; Railway's cron schedule invokes the container repeatedly.
CMD ["python", "-m", "ops.monitor.run", "--cron"]
