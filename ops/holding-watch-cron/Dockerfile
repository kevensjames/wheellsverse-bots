# Holding continuous-watch cron image.
#
# Same dependency set + repo layout as App B (backend/Dockerfile.staging) — built from the REPO ROOT
# context so core/ + backend/ + ops/ are all present — but the CMD runs the read-only watch loop ONCE
# and EXITS. Paired with a Railway cron schedule (~*/15) + restartPolicy NEVER, it senses continuously.
# No alembic (kai-prod already migrated the shared DB; watch_store self-creates its table).
#
# Selected via the RAILWAY_DOCKERFILE_PATH env var (config-as-code is deprecated for new services).
FROM python:3.11

WORKDIR /app

COPY backend/requirements-staging.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir -r /tmp/backend-requirements.txt \
 && pip install --no-cache-dir 'openai>=1.30.0,<2.0.0' 'anthropic>=0.39.0,<1.0.0'

COPY . /app
ENV PYTHONPATH=/app/backend

CMD ["python", "/app/ops/holding-watch-cron/run.py"]
