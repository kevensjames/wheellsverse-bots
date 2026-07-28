"""Shared slowapi Limiter for the whole app.

Why this lives in its own module: `@limiter.limit("...")` decorators in
routers/*.py and the `app.state.limiter = limiter` line in app/main.py must
reference the *same* instance — otherwise their in-memory counters live in
separate dicts and the rate limit never triggers. main.py imports routers,
so the limiter can't live in main.py without a circular import.

In-memory storage is fine for the single-worker uvicorn we ship (--workers 1
in the launchd plist). Multi-worker / multi-host deployments must set
storage_uri="redis://..." so all workers see the same counters.
"""
from __future__ import annotations

from slowapi import Limiter

from app.core.client_ip import client_ip


# Default key = the REAL client IP (CF-Connecting-IP when the socket peer is the
# trusted local tunnel, else the socket address). slowapi's get_remote_address
# keys on the loopback tunnel peer, collapsing every user into one bucket.
# headers_enabled=True makes the 429 carry Retry-After + X-RateLimit-* so a
# well-behaved client can back off instead of retrying blindly.
limiter = Limiter(key_func=client_ip, default_limits=[], headers_enabled=True)
