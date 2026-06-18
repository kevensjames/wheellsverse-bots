from __future__ import annotations

import json
import time

from ..models import Finding, RunnerStatus
from .base import run_cmd


def parse_gitleaks(stdout: str) -> list[Finding]:
    stdout = stdout.strip()
    if not stdout:
        return []
    data = json.loads(stdout)
    out: list[Finding] = []
    for item in data:
        loc = f"{item.get('File','?')}:{item.get('StartLine','?')}"
        out.append(Finding.create(
            category="secret", severity="high", tool="gitleaks",
            title=item.get("Description") or item.get("RuleID") or "secret",
            location=loc, secret=item.get("Secret") or item.get("Fingerprint") or loc,
            verified=False,
            metadata={"rule": item.get("RuleID")},
        ))
    return out


def parse_trufflehog(stdout: str) -> list[Finding]:
    out: list[Finding] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        if "DetectorName" not in item:
            continue
        fs = (item.get("SourceMetadata") or {}).get("Data", {}).get("Filesystem", {})
        loc = f"{fs.get('file','?')}:{fs.get('line','?')}"
        verified = bool(item.get("Verified"))
        out.append(Finding.create(
            category="secret", severity="critical" if verified else "high",
            tool="trufflehog", title=f"{item.get('DetectorName','secret')} credential",
            location=loc, secret=item.get("Raw") or item.get("Redacted") or loc,
            verified=verified, metadata={"detector": item.get("DetectorName")},
        ))
    return out


def scan_secrets(paths: list[str]) -> tuple[list[Finding], list[RunnerStatus]]:
    findings: list[Finding] = []
    statuses: list[RunnerStatus] = []
    for tool, argv_fn, parser in (
        ("gitleaks", lambda p: ["gitleaks", "detect", "--no-git", "-f", "json", "-r", "/dev/stdout", "-s", p], parse_gitleaks),
        ("trufflehog", lambda p: ["trufflehog", "filesystem", p, "--json", "--no-update"], parse_trufflehog),
    ):
        t0 = time.time()
        ok, err = True, None
        try:
            for p in paths:
                rc, out, serr = run_cmd(argv_fn(p))
                if rc == 127:
                    ok, err = False, serr
                    break
                findings.extend(parser(out))
        except Exception as e:  # parser/IO failure is isolated to this tool
            ok, err = False, str(e)
        statuses.append(RunnerStatus(tool=tool, ok=ok, error=err,
                                     duration_ms=int((time.time() - t0) * 1000)))
    return findings, statuses
