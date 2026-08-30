# Egress-allowlist proxy sidecar — minimal, self-contained (stdlib only), non-root.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY proxy.py /app/proxy.py
RUN useradd -r -u 10001 proxyusr
USER proxyusr
CMD ["python3", "/app/proxy.py"]
