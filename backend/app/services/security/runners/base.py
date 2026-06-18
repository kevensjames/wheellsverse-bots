from __future__ import annotations

import hashlib
import subprocess


def run_cmd(argv: list[str], cwd: str | None = None, timeout: int = 600) -> tuple[int, str, str]:
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"binary not found: {argv[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s: {argv[0]}"


def sha256_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
