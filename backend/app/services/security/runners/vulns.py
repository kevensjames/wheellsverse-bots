from __future__ import annotations

import json
import time

from ..models import Finding, RunnerStatus
from .base import run_cmd

_SEV = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low", "UNKNOWN": "info"}


def parse_trivy(stdout: str) -> list[Finding]:
    stdout = stdout.strip()
    if not stdout:
        return []
    data = json.loads(stdout)
    out: list[Finding] = []
    for res in data.get("Results") or []:
        target = res.get("Target", "?")
        for v in res.get("Vulnerabilities") or []:
            vid = v.get("VulnerabilityID", "CVE-?")
            loc = f"{v.get('PkgName','?')}@{v.get('InstalledVersion','?')} ({target})"
            out.append(Finding.create(
                category="vuln", severity=_SEV.get(v.get("Severity", "UNKNOWN"), "info"),
                tool="trivy", title=f"{vid}: {v.get('Title','')}".strip(), location=loc,
                secret=None, metadata={"cve": vid, "pkg": v.get("PkgName")},
            ))
    return out


def scan_vulns(paths: list[str]) -> tuple[list[Finding], list[RunnerStatus]]:
    findings: list[Finding] = []
    t0 = time.time()
    ok, err = True, None
    for p in paths:
        rc, out, serr = run_cmd(["trivy", "fs", "--quiet", "--format", "json",
                                 "--scanners", "vuln,secret,misconfig", p])
        if rc == 127:
            ok, err = False, serr
            break
        try:
            findings.extend(parse_trivy(out))
        except Exception as e:
            ok, err = False, str(e)
            break
    return findings, [RunnerStatus(tool="trivy", ok=ok, error=err,
                                   duration_ms=int((time.time() - t0) * 1000))]
