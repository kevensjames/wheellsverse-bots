"""Auto-safe fixer for missing_favicon.

Writes a branded SVG favicon and mounts /favicon.ico + /favicon.svg routes.
Idempotent."""

from __future__ import annotations

from pathlib import Path

from suprema.autorepair.engine import FixResult
from suprema.autorepair.fixers._fastapi_route import (
    find_main_api,
    insert_route_after_anchor,
    route_exists,
)

SVG_BODY = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="12" fill="#0d0f14"/>
  <path d="M32 8 L54 20 L54 44 L32 56 L10 44 L10 20 Z"
        fill="none" stroke="#7df9ff" stroke-width="4" stroke-linejoin="round"/>
  <circle cx="32" cy="32" r="6" fill="#7df9ff"/>
</svg>
'''

ROUTE_BLOCK = '''
@app.get("/favicon.svg")
async def serve_favicon_svg():
    """Canonical favicon. Auto-mounted by SUPREMA autorepair."""
    from fastapi.responses import FileResponse, Response
    p = ROOT / "frontend" / "favicon.svg"
    if not p.exists():
        return Response(status_code=404)
    return FileResponse(p, media_type="image/svg+xml")


@app.get("/favicon.ico")
async def serve_favicon_ico():
    """Legacy favicon path — serve the SVG. Auto-mounted by SUPREMA autorepair."""
    from fastapi.responses import FileResponse, Response
    p = ROOT / "frontend" / "favicon.svg"
    if not p.exists():
        return Response(status_code=204)
    return FileResponse(p, media_type="image/svg+xml")
'''


def apply(project: Path, finding) -> FixResult:
    changed: list[str] = []
    target = project / "frontend" / "favicon.svg"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(SVG_BODY)
        changed.append(str(target.relative_to(project)))

    api = find_main_api(project)
    if api and not route_exists(api, "/favicon.svg"):
        ok = insert_route_after_anchor(api, ROUTE_BLOCK)
        if ok:
            changed.append(str(api.relative_to(project)))

    if not changed:
        return FixResult(success=True, message="favicon already in place — no changes (idempotent)")

    return FixResult(
        success=True,
        changed_files=changed,
        message=f"created favicon + routes ({len(changed)} files touched)",
    )
