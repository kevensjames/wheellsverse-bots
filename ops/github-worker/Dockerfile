# GitHub read-only worker — minimal, non-root. Only needs python + PySocks (SOCKS5 via the proxy).
FROM python:3.11-slim
WORKDIR /work
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN pip3 install --no-cache-dir "PySocks==1.7.1" && useradd -r -u 10002 ghworker
COPY runner.py /work/runner.py
USER ghworker
CMD ["python3", "/work/runner.py"]
