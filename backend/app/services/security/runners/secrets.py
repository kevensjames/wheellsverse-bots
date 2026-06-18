from __future__ import annotations

import json
import os
import tempfile
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


def _run_gitleaks(paths: list[str]) -> tuple[list[Finding], RunnerStatus]:
    t0 = time.time()
    findings: list[Finding] = []
    ok, err = True, None
    try:
        for p in paths:
            # gitleaks 8.x refuses to write its report to /dev/stdout, so we write
            # to a temp file and read it. --exit-code 0 keeps "leaks found" (which
            # otherwise exits 1) from looking like a tool failure.
            fd, report = tempfile.mkstemp(suffix=".json")
            os.close(fd)
            try:
                rc, _out, serr = run_cmd(["gitleaks", "dir", p, "-f", "json",
                                          "-r", report, "--exit-code", "0", "--no-banner"])
                if rc == 127:
                    ok, err = False, serr
                    break
                with open(report, encoding="utf-8") as fh:
                    findings.extend(parse_gitleaks(fh.read()))
            finally:
                try:
                    os.unlink(report)
                except OSError:
                    pass
    except Exception as e:  # IO/parse failure is isolated to this tool
        ok, err = False, str(e)
    return findings, RunnerStatus(tool="gitleaks", ok=ok, error=err,
                                  duration_ms=int((time.time() - t0) * 1000))


def _run_trufflehog(paths: list[str]) -> tuple[list[Finding], RunnerStatus]:
    t0 = time.time()
    findings: list[Finding] = []
    ok, err = True, None
    try:
        for p in paths:
            rc, out, serr = run_cmd(["trufflehog", "filesystem", p, "--json", "--no-update"])
            if rc == 127:
                ok, err = False, serr
                break
            findings.extend(parse_trufflehog(out))
    except Exception as e:
        ok, err = False, str(e)
    return findings, RunnerStatus(tool="trufflehog", ok=ok, error=err,
                                  duration_ms=int((time.time() - t0) * 1000))


def scan_secrets(paths: list[str]) -> tuple[list[Finding], list[RunnerStatus]]:
    gl_findings, gl_status = _run_gitleaks(paths)
    th_findings, th_status = _run_trufflehog(paths)
    return gl_findings + th_findings, [gl_status, th_status]
