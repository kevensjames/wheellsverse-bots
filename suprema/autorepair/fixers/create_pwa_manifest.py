"""Auto-safe fixer for missing_pwa_manifest.

Creates frontend/manifest.json (minimum-viable PWA fields) and mounts a
FastAPI route if one doesn't exist. Idempotent."""

from __future__ import annotations

import json
from pathlib import Path

from suprema.autorepair.engine import FixResult
from suprema.autorepair.fixers._fastapi_route import (
    find_main_api,
    insert_route_after_anchor,
    route_exists,
)

MANIFEST_BODY = {
    "name": "SUPREMA",
    "short_name": "SUPREMA",
    "description": "SUPREMA workspace operator console.",
    "start_url": "/admin",
    "scope": "/",
    "display": "standalone",
    "orientation": "any",
    "background_color": "#0d0f14",
    "theme_color": "#0d0f14",
    "icons": [
        {"src": "/favicon.svg", "type": "image/svg+xml",
         "sizes": "any", "purpose": "any maskable"}
    ],
}

ROUTE_BLOCK = '''
@app.get("/manifest.json")
async def serve_manifest():
    """PWA manifest. Auto-mounted by SUPREMA autorepair."""
    from fastapi.responses import FileResponse, JSONResponse
    p = ROOT / "frontend" / "manifest.json"
    if not p.exists():
        return JSONResponse({"name": "SUPREMA"}, media_type="application/manifest+json")
    return FileResponse(p, media_type="application/manifest+json")
'''


def apply(project: Path, finding) -> FixResult:
    changed: list[str] = []
    manifest_path = finding.fix_payload.get("manifest_path", "/manifest.json")

    # 1. Create the JSON file
    target = project / "frontend" / manifest_path.lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        # Customize name/short_name from project folder
        body = dict(MANIFEST_BODY)
        body["name"] = f"{project.name.title().replace('-', ' ')} — Admin"
        body["short_name"] = project.name.split("-")[0].title()
        target.write_text(json.dumps(body, indent=2) + "\n")
        changed.append(str(target.relative_to(project)))

    # 2. Mount the route if FastAPI app detected
    api = find_main_api(project)
    if api and not route_exists(api, manifest_path):
        ok = insert_route_after_anchor(api, ROUTE_BLOCK)
        if ok:
            changed.append(str(api.relative_to(project)))

    if not changed:
        return FixResult(
            success=True,
            message="manifest already in place — no changes needed (idempotent)",
        )

    return FixResult(
        success=True,
        changed_files=changed,
        message=f"created manifest + route ({len(changed)} files touched)",
    )
