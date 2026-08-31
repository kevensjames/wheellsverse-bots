# Holding daily-briefing cron image.
#
# Same dependency set + repo layout as App B (backend/Dockerfile.staging) — built from the REPO
# ROOT context so core/ + backend/ + ops/ are all present — but the CMD runs the report-only
# briefing ONCE (persist=True) and EXITS, instead of serving uvicorn. Paired with a Railway cron
# schedule + restartPolicy NEVER, it fires daily. No alembic here: kai-prod already migrated the
# shared DB, and kpi_history self-creates its table.
#
# Selected via the RAILWAY_DOCKERFILE_PATH env var (config-as-code / railway.json is deprecated for
# new Railway services, so the path is set as a service variable, not in a config file).
FROM python:3.11

WORKDIR /app

COPY backend/requirements-staging.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir -r /tmp/backend-requirements.txt \
 && pip install --no-cache-dir 'openai>=1.30.0,<2.0.0' 'anthropic>=0.39.0,<1.0.0'

COPY . /app
ENV PYTHONPATH=/app/backend

# One-shot: run the flag-gated, report-only briefing (persist=True), then exit.
CMD ["python", "/app/ops/holding-briefing-cron/run.py"]
