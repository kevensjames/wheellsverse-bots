"""Celery worker entrypoint for Railway (staging).

Railway's deploy lifecycle waits for the container to bind $PORT and stops it
otherwise — a bare Celery worker binds no port, so Railway kills it ("Stopping
Container" with no app output). This wrapper binds $PORT with a trivial health
server in a daemon thread, then runs the Celery worker IN-PROCESS (blocking) so
both stay alive under one PID. The worker code is unchanged.
"""
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"worker-ok")

    def log_message(self, *args):  # silence access logging
        pass


def _serve_health():
    port = int(os.environ.get("PORT", "8080"))
    HTTPServer(("0.0.0.0", port), _Health).serve_forever()


if __name__ == "__main__":
    threading.Thread(target=_serve_health, daemon=True).start()
    # PYTHONPATH=/app/backend (set in the Dockerfile) makes `app` importable.
    from app.workers.celery_app import celery_app
    # solo pool: single-process, no fork — most robust in a container.
    celery_app.worker_main(
        argv=["worker", "--loglevel=INFO", "--pool=solo", "--concurrency=1"]
    )
