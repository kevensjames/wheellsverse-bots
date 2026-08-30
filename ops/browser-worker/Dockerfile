# Deterministic browser worker — isolated, non-root, pinned Playwright (Chromium preinstalled).
# Pinned image (never :latest). Runs one read-only task and exits.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy
WORKDIR /work
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# Pin the playwright python package (Chromium already ships in the base image).
RUN pip3 install --no-cache-dir playwright==1.47.0
COPY runner.py /work/runner.py
# The base image ships the `pwuser` non-root account + Chromium. Run as non-root.
USER pwuser
CMD ["python3", "/work/runner.py"]
