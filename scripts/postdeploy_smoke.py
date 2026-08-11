#!/usr/bin/env python3
"""Post-deploy smoke test — READ-ONLY, no money movement.

Hits health + a couple of safe read endpoints on a running deployment and checks
they respond sanely. It never creates users, moves money, writes data, or sends
webhooks. Use it after a deploy to confirm the service is alive before expanding
rollout.

    python scripts/postdeploy_smoke.py --base-url https://kai.example.com

Exit non-zero if any required probe fails.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request

FAILS: list[str] = []


def probe(base: str, path: str, *, expect_status: int = 200,
          required: bool = True, check=None) -> None:
    url = base.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            status = r.status
            body = r.read(65536).decode("utf-8", "replace")
    except Exception as e:
        msg = f"{path}: request failed — {e}"
        (FAILS.append(msg) if required else None)
        print(f"[{'FAIL' if required else 'warn'}] {msg}")
        return
    ok = status == expect_status and (check is None or check(body))
    if not ok and required:
        FAILS.append(f"{path}: status={status}")
    print(f"[{'ok' if ok else ('FAIL' if required else 'warn')}] {path} -> {status}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="e.g. https://kai.example.com")
    args = ap.parse_args()
    base = args.base_url
    print(f"== post-deploy smoke: {base} (read-only) ==\n")

    # /health returns {"status":"ok","env":...}
    probe(base, "/health", check=lambda b: '"status"' in b and "ok" in b)
    # /version is a harmless JSON blob
    probe(base, "/version", required=False)
    # an admin route with NO token must be refused (403/401) — proves the gate is up
    probe(base, "/admin/audit", expect_status=403, required=False)

    print("\n" + "=" * 60)
    if FAILS:
        print(f"SMOKE FAILED — {len(FAILS)} probe(s). Consider rollback (ROLLBACK_RUNBOOK.md).")
        return 1
    print("SMOKE OK — service is alive. Continue monitoring before expanding rollout.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
