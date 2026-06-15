"""Auto-safe fixer for missing_service_worker.

Writes a minimal sw.js with sensible cache strategy and mounts a FastAPI
route. Idempotent."""

from __future__ import annotations

from pathlib import Path

from suprema.autorepair.engine import FixResult
from suprema.autorepair.fixers._fastapi_route import (
    find_main_api,
    insert_route_after_anchor,
    route_exists,
)

SW_BODY = """\
// SUPREMA service worker (auto-generated)
const CACHE_VERSION = 'suprema-v1';
const ASSETS = ['/manifest.json', '/favicon.svg', '/favicon.ico'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_VERSION)
    .then(c => c.addAll(ASSETS))
    .then(() => self.skipWaiting())
    .catch(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== CACHE_VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.origin !== self.location.origin) return;
  // Always-fresh paths
  if (url.pathname.startsWith('/admin') || url.pathname.startsWith('/api/')) return;
  e.respondWith(
    caches.match(e.request).then(c => {
      const net = fetch(e.request).then(r => {
        if (r && r.ok) {
          const copy = r.clone();
          caches.open(CACHE_VERSION).then(cache => cache.put(e.request, copy)).catch(()=>{});
        }
        return r;
      }).catch(() => c);
      return c || net;
    })
  );
});
"""

ROUTE_BLOCK = '''
@app.get("/sw.js")
async def serve_service_worker():
    """Service worker. Auto-mounted by SUPREMA autorepair."""
    from fastapi.responses import FileResponse, Response
    p = ROOT / "frontend" / "sw.js"
    if not p.exists():
        return Response(status_code=404)
    return FileResponse(
        p,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate",
                 "Service-Worker-Allowed": "/"},
    )
'''


def apply(project: Path, finding) -> FixResult:
    changed: list[str] = []
    sw_path = finding.fix_payload.get("sw_path", "/sw.js")

    target = project / "frontend" / sw_path.lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(SW_BODY)
        changed.append(str(target.relative_to(project)))

    api = find_main_api(project)
    if api and not route_exists(api, sw_path):
        ok = insert_route_after_anchor(api, ROUTE_BLOCK)
        if ok:
            changed.append(str(api.relative_to(project)))

    if not changed:
        return FixResult(success=True, message="sw.js already in place — no changes (idempotent)")

    return FixResult(
        success=True,
        changed_files=changed,
        message=f"created sw.js + route ({len(changed)} files touched)",
    )
