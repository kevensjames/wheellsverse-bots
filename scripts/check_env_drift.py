#!/usr/bin/env python3
"""
scripts/check_env_drift.py
Compare .env vs .env.example. If real .env has keys missing from the example,
print a punch-list and exit 1. Used by com.wheellsverse.envdrift.weekly plist
to keep onboarding docs honest.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).parent.parent
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"

KEY_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=")


def keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    found = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = KEY_RE.match(line)
        if m:
            found.add(m.group(1))
    return found


def main() -> int:
    env_keys = keys(ENV)
    ex_keys = keys(EXAMPLE)
    if not env_keys:
        print(f"!! .env not found or empty at {ENV}", file=sys.stderr)
        return 2
    missing = sorted(env_keys - ex_keys)
    extra = sorted(ex_keys - env_keys)
    if not missing and not extra:
        print(f"OK — .env and .env.example are in sync ({len(env_keys)} keys)")
        return 0
    print(f".env has {len(env_keys)} keys, .env.example has {len(ex_keys)} keys")
    if missing:
        print(f"\nMissing from .env.example ({len(missing)}):")
        for k in missing:
            print(f"  + {k}")
    if extra:
        print(f"\nIn .env.example but not .env ({len(extra)}) — possibly stale:")
        for k in extra:
            print(f"  - {k}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
