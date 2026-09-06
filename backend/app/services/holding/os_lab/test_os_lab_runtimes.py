"""OS Lab Phase 10 / Cluster C checks — §40 Ultron, §42 virtme-ng, §43 syzkaller, §165 guard, §102/§150 rows.
Zero-framework (mirrors test_registry.py / test_omnipresence_phase5.py). Run (from backend/):
    python3 -m app.services.holding.os_lab.test_os_lab_runtimes
or:
    python3 backend/app/services/holding/os_lab/test_os_lab_runtimes.py
"""
import re
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))   # backend/ on path so `app` is a package

from app.services.holding.os_lab import runtimes as R, catalog as C   # noqa: E402

_HERE = Path(__file__).resolve().parent
# No code path in this package may reach the network, a shell, git, or a VM (§113/§115/§160 catalog-first).
_EXEC_RE = re.compile(r"^\s*(import|from)\s+(subprocess|socket|urllib|requests|httpx|shutil|asyncio|git|docker|"
                      r"paramiko|pexpect)\b|os\.(system|popen|exec\w*|spawn\w*)\(|qemu-system|\bgit clone\b",
                      re.M)


def _enforce_raises(guard, source) -> bool:
    try:
        guard.enforce(R.AuthorityClaim(source, "APPROVE_DEPLOY")); return False
    except R.OsLabAuthorityViolation:
        return True


def run() -> bool:
    res = []
    def ck(n, ok):
        res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    # ── nothing executed: static scan of the whole package (catalog + runtimes + this file's siblings) ──
    for py in sorted(_HERE.glob("*.py")):
        if py.name.startswith("test_"):
            continue
        ck(f"{py.name}: no subprocess/network/git/QEMU code path (catalog-first)",
           not _EXEC_RE.search(py.read_text(encoding="utf-8")))
    ck("EXECUTED ledger is all False (no clone/download/install/build/qemu/network/new dependency)",
       not any(R.EXECUTED.values()) and set(R.EXECUTED) >= {"clone", "install", "build", "qemu_boot", "new_dependency"})

    # ── L1 round 4: the ledger is the SOLE gate catalog.advance() consults — it must not be writable ──
    def _write(mapping, key, value):        # item assignment as a statement, so _raises can catch it
        mapping[key] = value

    def _raises(exc, fn):
        try:
            fn()
        except exc:
            return True
        except Exception as ex:
            print(f"      (raised {type(ex).__name__}: {ex})")
        return False

    real = R.EXECUTED
    ck("L1: EXECUTED is a READ-ONLY mapping — item assignment / update / pop / clear / setdefault all refused, "
       "so no in-process importer can flip the build/qemu_boot gate in place",
       _raises(TypeError, lambda: _write(R.EXECUTED, "build", True))
       and all(_raises(AttributeError, fn) for fn in (lambda: R.EXECUTED.update(build=True),
                                                      lambda: R.EXECUTED.pop("build"),
                                                      lambda: R.EXECUTED.clear(),
                                                      lambda: R.EXECUTED.setdefault("x", 1)))
       and R.EXECUTED["build"] is False and not any(R.EXECUTED.values()))
    with R.simulated_ledger(build=True) as led:
        ck("L1: simulated_ledger REBINDS the module attribute (a different, still read-only mapping) instead of "
           "mutating the real one; only the named key changes",
           R.EXECUTED is led and R.EXECUTED is not real and R.EXECUTED["build"] is True
           and R.EXECUTED["qemu_boot"] is False and _raises(TypeError, lambda: _write(R.EXECUTED, "qemu_boot", True)))
    ck("L1: the real all-False ledger is restored on exit — the identical object, not a rebuilt copy",
       R.EXECUTED is real and not any(R.EXECUTED.values()))
    ck("L1: an unknown ledger key is refused — the seam cannot invent a gate, and the real ledger is untouched",
       _raises(ValueError, lambda: R.simulated_ledger(bogus=True).__enter__())
       and R.EXECUTED is real and not any(R.EXECUTED.values()))

    # ── §40 Ultron — EDUCATIONAL_OS_SANDBOX, all verification fields UNVERIFIED, production_use=NO ──
    u = R.ULTRON
    ck("Ultron: every verification field UNVERIFIED (pinned_sha/license/build/static_scan/qemu/network/risk/"
       "last_verified/malware_scan)", u.all_unverified() and len(R.ULTRON_VERIFICATION_FIELDS) == 9)
    ck("Ultron: production_use=NO, installed=False, disposition EDUCATIONAL_OS_SANDBOX, trust UNTRUSTED",
       u.production_use == "NO" and u.installed is False
       and u.disposition == R.RuntimeRole.EDUCATIONAL_OS_SANDBOX and u.trust == "UNTRUSTED")
    ck("M5: Ultron source is the catalog's OPERATOR-STATED canonical_source (ONE spine, read not fetched); note says operator-stated + unverified; "
       "no UNRESOLVED constant remains",
       u.source == C.get("Ultron OS", C.initial_catalog()).canonical_source == "https://github.com/aswinmohanme/ultronOS"
       and "operator-stated" in u.source_note and "unverified" in u.source_note.lower() and "NOT fetched" in u.source_note
       and not hasattr(R, "UNRESOLVED") and "UNRESOLVED" not in (_HERE / "runtimes.py").read_text(encoding="utf-8"))
    c = u.constraints
    ck("Ultron constraints: isolated QEMU/container only, no credentials, bounded host fs, no prod network",
       c.isolation == "ISOLATED_QEMU_OR_CONTAINER_ONLY" and c.credentials_allowed is False
       and c.host_fs_access == "BOUNDED_WORKSPACE_ONLY" and c.production_network_allowed is False
       and c.network_default == "NONE")
    for bad in ({"malware_scan": "MALWARE_FREE"}, {"static_scan": "CLEAN"}, {"production_use": "YES"},
                {"build_status": "SAFE"}):
        try:
            R.UltronSandboxRecord(**bad); ok = False
        except ValueError:
            ok = True
        ck(f"Ultron record rejects {bad}", ok)
    ck("Ultron to_dict carries all_unverified=True", u.to_dict()["all_unverified"] is True)
    # L2: forbidden claims are refused in ANY spelling, on EVERY verification field (normalized token match)
    SPELLINGS = ("malware free", "Malware-Free", "MALWARE_FREE_2026", "malware\tfree", "verified-safe", "Verified Safe",
                 " clean ", "Clean", "safe_2026", "SAFE", "not safe", "safe-ish",
                 # L2 round 2: any non-alphanumeric separator, and the separator-STRIPPED spelling
                 "MALWARE.FREE", "malware/free", "malware(free)", "malwarefree", "MalwareFree", "VerifiedSafe",
                 "SAFE!", "clean.", "#clean", "safe.2026")

    def _refused_claim(field, value):
        try:
            R.UltronSandboxRecord(**{field: value}); return False
        except ValueError:
            return True
    ck("L2: every FORBIDDEN_CLAIMS spelling (case/space/dash/dot/slash/punctuation, separator-stripped "
       "'malwarefree'/'VerifiedSafe', MALWARE_FREE substring) is refused on all 9 verification fields",
       len(R.ULTRON_VERIFICATION_FIELDS) == 9
       and all(_refused_claim(f, v) for f in R.ULTRON_VERIFICATION_FIELDS for v in SPELLINGS))
    ck("L2: a bounded, non-claim value still constructs (risk=HIGH, build_status=FAILED, last_verified=date); static_scan outside the §114 vocab does not",
       R.UltronSandboxRecord(risk="HIGH", build_status="FAILED", last_verified="2026-09-04").risk == "HIGH"
       and _refused_claim("static_scan", "HIGH") and _refused_claim("malware_scan", "PASSED") and _refused_claim("pinned_sha", "safe"))

    # ── §42 virtme-ng — type MCP / KERNEL_TEST_RUNTIME, default OFF, prod DISABLED, typed allow/deny ──
    v = R.VIRTME_NG
    ck("virtme-ng: installed=False until supply-chain cert PASSES; cert_status UNVERIFIED",
       v.installed is False and v.install_precondition == "SUPPLY_CHAIN_CERT_PASS" and v.cert_status == R.UNVERIFIED)
    ck("virtme-ng: manifest type MCP, activation DISABLED, DISCOVERED, RESTRICTED, sandbox+approval required",
       v.manifest.type.value == "MCP" and v.manifest.activation.value == "DISABLED"
       and v.manifest.availability.value == "DISCOVERED" and v.manifest.risk_class.value == "RESTRICTED"
       and v.manifest.sandbox_required and v.manifest.operator_approval_required
       and v.manifest.automatic_activation_allowed is False and v.manifest.selectable() is False)
    ck("virtme-ng: provenance is a NOTE — verified=False, license/ref UNVERIFIED, install_method NONE_YET",
       v.manifest.provenance.verified is False and v.manifest.provenance.license == R.UNVERIFIED
       and v.manifest.provenance.ref == R.UNVERIFIED and v.manifest.provenance.install_method == "NONE_YET")
    p = v.policy
    allow = {"BOUNDED_KERNEL_BUILD", "ISOLATED_VM_BOOT", "KERNEL_TEST_RUN", "DMESG_READ", "KERNEL_COMPARISON"}
    deny = {"HOST_KERNEL_REPLACEMENT", "PRODUCTION_REBOOT", "HOST_ARBITRARY_SHELL", "PRODUCTION_MODULE_LOAD",
            "CREDENTIAL_ACCESS"}
    ck("virtme-ng allow-list = bounded build/boot/test/dmesg/comparison", {k.value for k in p.allow} == allow)
    ck("virtme-ng deny-list = host kernel replacement/prod reboot/host shell/prod module load/credential access",
       {k.value for k in p.deny} == deny)
    ck("deny-list enforced: every denied op → DENIED", all(p.decide(op) == "DENIED" for op in deny))
    ck("allow-list: every allowed op → ALLOWED (policy only — not a run)", all(p.decide(op) == "ALLOWED" for op in allow))
    ck("unknown op → DENIED_UNKNOWN_OP (default-deny)", p.decide("rm -rf /") == "DENIED_UNKNOWN_OP")
    def _no_policy(**kw):
        try:
            R.KernelTestPolicy(**kw); return False
        except ValueError:
            return True
    ck("a policy cannot allow and deny the same op",
       _no_policy(allow=frozenset({R.KernelOp.DMESG_READ}), deny=R.KERNEL_DENY | {R.KernelOp.DMESG_READ}))
    # M4: the deny-list is an INVARIANT hoisted to KERNEL_DENY — no policy can allow or un-deny those ops
    ck("M4: KERNEL_DENY is hoisted, is exactly the 5 §42 never-ops, and the default policy's deny == KERNEL_DENY",
       {k.value for k in R.KERNEL_DENY} == deny and R.KernelTestPolicy().deny == R.KERNEL_DENY)
    ck("M4: a permissive policy that allows HOST_ARBITRARY_SHELL (or any KERNEL_DENY op) refuses to construct",
       all(_no_policy(allow=frozenset({op})) for op in R.KERNEL_DENY)
       and _no_policy(allow=R.KernelTestPolicy().allow | {R.KernelOp.HOST_ARBITRARY_SHELL}))
    ck("M4: a policy whose deny-list drops any KERNEL_DENY op refuses to construct",
       _no_policy(deny=frozenset()) and all(_no_policy(deny=R.KERNEL_DENY - {op}) for op in R.KERNEL_DENY))
    hacked = R.KernelTestPolicy()
    object.__setattr__(hacked, "allow", hacked.allow | R.KERNEL_DENY)     # force past the frozen dataclass
    object.__setattr__(hacked, "deny", frozenset())
    ck("M4: even with frozen fields forced permissive (allow ⊇ KERNEL_DENY, deny = ∅), decide() still DENIES every KERNEL_DENY op — invariant checked first",
       all(hacked.decide(op) == "DENIED" for op in R.KERNEL_DENY) and hacked.decide("DMESG_READ") == "ALLOWED")
    off = NS()                                                     # flags absent from config → OFF
    staging_on = NS(APP_ENV="staging", KAI_OS_LAB_ENABLED=True, KAI_OS_LAB_VIRTME_NG_ENABLED=True,
                    KAI_OS_LAB_ULTRON_RUNTIME_ENABLED=True, KAI_OS_LAB_SYZKALLER_ENABLED=True)
    prod_on = NS(APP_ENV="production", KAI_OS_LAB_ENABLED=True, KAI_OS_LAB_VIRTME_NG_ENABLED=True,
                 KAI_OS_LAB_ULTRON_RUNTIME_ENABLED=True, KAI_OS_LAB_SYZKALLER_ENABLED=True)
    ck("virtme-ng default OFF (flags absent)", R._runtime_on(off, R.FLAG_VIRTME_NG) is False
       and v.to_dict(off)["runtime_enabled"] is False)
    ck("virtme-ng production DISABLED even with every flag on", R._runtime_on(prod_on, R.FLAG_VIRTME_NG) is False
       and v.to_dict(prod_on)["runtime_enabled"] is False)
    # L1: _is_production fails CLOSED — only an explicitly known non-production env is non-production
    ck("L1: absent / '' / None / 'prod' / 'PRODUCTION ' / 'stage' / 'qa' APP_ENV → production",
       all(R._is_production(NS(**kw)) for kw in ({}, {"APP_ENV": ""}, {"APP_ENV": None}, {"APP_ENV": "prod"},
                                                 {"APP_ENV": "PRODUCTION "}, {"APP_ENV": "stage"}, {"APP_ENV": "qa"})))
    ck("L1: only development/dev/local/test/staging (trimmed, case-insensitive) are non-production",
       not any(R._is_production(NS(APP_ENV=v)) for v in ("development", "dev", "local", "test", "staging", " Staging ", "DEV")))
    ck("L1: every flag on but APP_ENV absent → runtime still OFF (fail closed)",
       R._runtime_on(NS(KAI_OS_LAB_ENABLED=True, KAI_OS_LAB_VIRTME_NG_ENABLED=True), R.FLAG_VIRTME_NG) is False
       and all(r["runtime_enabled"] is False for r in R.os_lab_feature_registry(NS(KAI_OS_LAB_ENABLED=True, KAI_OS_LAB_VIRTME_NG_ENABLED=True))))
    ck("virtme-ng can_run: False for an ALLOWED op even in staging with flags on (not installed, not selectable)",
       v.can_run("DMESG_READ", staging_on) is False)
    ck("virtme-ng can_run: False for a DENIED op under every settings",
       all(v.can_run("HOST_KERNEL_REPLACEMENT", s) is False for s in (off, staging_on, prod_on)))
    ck("virtme-ng to_dict: production_use NO, selectable False, installed False",
       v.to_dict(staging_on)["production_use"] == "NO" and v.to_dict(staging_on)["selectable"] is False
       and v.to_dict(staging_on)["installed"] is False)

    # ── §43 syzkaller — RESTRICTED_SECURITY_LAB, never production, NEVER auto-selected ──
    s = R.SYZKALLER
    ck("syzkaller: selectable()==False and automatic_activation_allowed==False",
       s.selectable() is False and s.automatic_activation_allowed is False)
    ck("syzkaller: availability DISABLED, activation DISABLED, RESTRICTED/DESTRUCTIVE, tier 4, target allowlist",
       s.manifest.availability.value == "DISABLED" and s.manifest.activation.value == "DISABLED"
       and s.manifest.risk_class.value == "RESTRICTED" and s.manifest.default_action_class.value == "DESTRUCTIVE"
       and s.manifest.security_tier == 4 and s.manifest.target_allowlist_required)
    lp = s.lab_policy
    ck("syzkaller lab policy: no prod, no prod creds/network, no host-kernel fuzzing, disposable isolated VM only",
       lp.production_allowed is False and lp.prod_credentials_allowed is False and lp.prod_network_allowed is False
       and lp.host_kernel_fuzzing_allowed is False and lp.target_kind == "ISOLATED_DISPOSABLE_VM_ONLY"
       and lp.requires_authorized_mission is True)
    ck("syzkaller admit(None) → DENIED", lp.admit(None)["decision"] == "DENIED")
    good = {"authorized": True, "kind": "security", "operator_approval_ref": "APR-1", "target_kind": "ISOLATED_DISPOSABLE_VM"}
    ck("syzkaller: a fully authorized security mission on a disposable VM is ADMISSIBLE_NOT_RUNNABLE (never RUN)",
       lp.admit(good)["decision"] == "ADMISSIBLE_NOT_RUNNABLE")
    for k, bad in (("kind", "marketing"), ("authorized", "yes"), ("target_kind", "HOST"), ("operator_approval_ref", "")):
        ck(f"syzkaller mission with {k}={bad!r} → DENIED", lp.admit({**good, k: bad})["decision"] == "DENIED")
    for extra in ({"target_is_host": True}, {"target_is_production": True}, {"uses_prod_credentials": True},
                  {"uses_prod_network": True}):
        ck(f"syzkaller mission with {extra} → DENIED", lp.admit({**good, **extra})["decision"] == "DENIED")
    ck("syzkaller can_run is False under every settings (no allow-list exists in this phase)",
       all(s.can_run(op, st) is False for op in ("KERNEL_TEST_RUN", "fuzz") for st in (off, staging_on, prod_on)))
    ck("syzkaller to_dict: never_auto_selected True, production_use NO, installed False",
       s.to_dict(staging_on)["never_auto_selected"] is True and s.to_dict(staging_on)["production_use"] == "NO"
       and s.to_dict(staging_on)["installed"] is False)

    # ── §165 KAI remains the brain — OsLabAuthorityGuard ──
    g = R.GUARD
    for src in ("ultron_os", "virtme_ng", "syzkaller", "os_lab:anything"):
        ck(f"guard: {src} APPROVE → REJECTED", g.check(R.AuthorityClaim(src, "APPROVE")) == "REJECTED")
    ck("guard: every AUTHORITY_ACTION from an OS source → REJECTED",
       all(g.check(R.AuthorityClaim("syzkaller", a)) == "REJECTED" for a in R.AUTHORITY_ACTIONS))
    ck("guard: REPORT_RESULT from an OS source → EVIDENCE_ONLY (data, never authority)",
       g.check(R.AuthorityClaim("virtme_ng", "REPORT_RESULT")) == "EVIDENCE_ONLY")
    ck("guard: an unknown action from an OS source → REJECTED_UNKNOWN_ACTION (fail closed)",
       g.check(R.AuthorityClaim("ultron_os", "PLEASE_MERGE")) == "REJECTED_UNKNOWN_ACTION")
    try:
        g.enforce(R.AuthorityClaim("os_lab:ultron", "REWRITE_GOVERNANCE")); ok = False
    except R.OsLabAuthorityViolation as e:
        ok = isinstance(e, PermissionError) and "§165" in str(e)
    ck("guard.enforce raises OsLabAuthorityViolation(PermissionError) on OS-sourced governance rewrite", ok)
    ck("guard: a non-OS principal is NOT judged here (existing seams govern it)",
       g.check(R.AuthorityClaim("operator", "APPROVE")) == "NOT_OS_LAB_SOURCE")
    # L3: the source is normalized (strip / lower / '-' and ' ' → '_') against runtime ids, display names, and the os_lab prefix
    ck("L3: 'SYZKALLER' / ' syzkaller ' / 'OS_LAB:ultron' / 'os-lab:ultron' / 'virtme-ng' / 'Ultron OS' / 'ultron-os' / 'Virtme NG' / 'OS LAB' → REJECTED on APPROVE",
       all(g.is_os_lab_source(s) and g.check(R.AuthorityClaim(s, "APPROVE")) == "REJECTED"
           for s in ("SYZKALLER", " syzkaller ", "OS_LAB:ultron", "os-lab:ultron", "virtme-ng", "Ultron OS", "ultron-os", "Virtme NG", "OS LAB")))
    ck("L3: normalized variants also raise on enforce() and stay EVIDENCE_ONLY for evidence actions",
       all(g.check(R.AuthorityClaim(s, "REPORT_RESULT")) == "EVIDENCE_ONLY" for s in ("Ultron OS", "SYZKALLER", "os-lab:x"))
       and all(_enforce_raises(g, s) for s in ("Ultron OS", " syzkaller ", "os-lab:ultron")))
    ck("L3: non-OS principals stay NOT_OS_LAB_SOURCE after normalization",
       all(g.check(R.AuthorityClaim(s, "APPROVE")) == "NOT_OS_LAB_SOURCE" for s in ("operator", " Operator ", "kai", "KAI")))
    # L3 round 2: exact-match let decorated ids through — match by token containment of the runtime stems, fail closed
    ck("L3: DECORATED ids ('ultron-os-runtime', 'syzkaller_vm_1', 'OS-Lab/qemu', 'virtme_ng_vm2', 'oslab:x') are "
       "OS-lab sources → APPROVE REJECTED + enforce() raises (no fall-through to NOT_OS_LAB_SOURCE)",
       all(g.is_os_lab_source(s) and g.check(R.AuthorityClaim(s, "APPROVE")) == "REJECTED" and _enforce_raises(g, s)
           for s in ("ultron-os-runtime", "syzkaller_vm_1", "OS-Lab/qemu", "virtme_ng_vm2", "oslab:x", "ULTRON.OS")))
    # L1 round 3: 'oslab' was matched ANYWHERE in the normalized source, annexing unrelated principals
    ck("L1: the os_lab/oslab prefix is ANCHORED — 'chaos_labs' / 'chaos-lab' / 'photos_lab' / 'labs_os' are NOT "
       "OS-lab sources (left to the existing seams), while every documented decorated case still matches and "
       "the ultron/virtme/syzkaller runtime-stem containment is unchanged",
       not any(g.is_os_lab_source(s) for s in ("chaos_labs", "chaos-lab", "photos_lab", "labs_os"))
       and all(g.check(R.AuthorityClaim(s, "APPROVE")) == "NOT_OS_LAB_SOURCE"
               for s in ("chaos_labs", "chaos-lab", "photos_lab"))
       and all(g.is_os_lab_source(s) for s in ("OS-Lab/qemu", "oslab:x", "OS LAB", "os_lab:anything",
                                               "ultron-os-runtime", "syzkaller_vm_1", "virtme_ng_vm2", "ULTRON.OS")))
    ck("L3: the governed-principal allowlist (operator / kai / owner:*) still stays NOT_OS_LAB_SOURCE, and an "
       "unrelated principal does too",
       all(g.check(R.AuthorityClaim(s, "APPROVE")) == "NOT_OS_LAB_SOURCE"
           for s in ("operator", "kai", "owner", "owner:alice", "OWNER:kevens", "github_actions", "postgres")))
    ck("guard: AUTHORITY_ACTIONS covers grant/approve/deploy/financial/governance/flag/role/host/auto-select",
       {"GRANT_AUTHORITY", "APPROVE", "APPROVE_DEPLOY", "APPROVE_FINANCIAL", "REWRITE_GOVERNANCE", "SET_POLICY",
        "ENABLE_FLAG", "ESCALATE_ROLE", "EXECUTE_ON_HOST", "AUTO_SELECT_RUNTIME"} <= R.AUTHORITY_ACTIONS)
    cat = C.initial_catalog()
    ck("§165 catalog entries carry no permissions/action_class/activation/authority field; authority_plane=KAI",
       all(not ({"permissions", "action_class", "activation", "authority", "grants"} & set(e.to_dict()))
           and e.to_dict()["authority_plane"] == "KAI" for e in cat))
    ck("§165 os_lab_view.authority_plane == KAI", R.os_lab_view(off)["authority_plane"] == "KAI")

    # ── catalog binding: installed is DERIVED from the §113 lifecycle, all gates closed today ──
    b = R.catalog_binding(cat)
    ck("binding: all three runtimes resolve to a catalog entry, DISCOVERED/UNVERIFIED, disposition consistent",
       set(b) == {"ultron_os", "virtme_ng", "syzkaller"}
       and all(x["catalog_state"] == "DISCOVERED" and x["catalog_verdict"] == "UNVERIFIED"
               and x["catalog_source_status"] == "UNVERIFIED" and x["disposition_consistent"] for x in b.values()))
    ck("binding: install_allowed False for all, with named reasons (§113 state, §114 verdict, §117 justification)",
       all(x["install_allowed"] is False and len(x["reasons"]) == 3 for x in b.values()))
    # M5: ONE spine — the source each runtime record carries must equal the catalog's canonical_source
    ck("M5: binding.source_consistent is True for all three runtimes (record source == catalog canonical_source)",
       all(x["source_consistent"] is True and x["catalog_source"].startswith("https://") for x in b.values())
       and b["ultron_os"]["catalog_source"] == R.ULTRON.source
       and b["virtme_ng"]["catalog_source"] == R.VIRTME_NG.manifest.provenance.upstream
       and b["syzkaller"]["catalog_source"] == R.SYZKALLER.manifest.provenance.upstream)
    cat2 = C.initial_catalog(); C.get("Ultron OS", cat2).canonical_source = "https://example.invalid/forked"
    b2 = R.catalog_binding(cat2)
    ck("M5: a drifted catalog source → source_consistent False for that runtime only (drift is visible, never silent)",
       b2["ultron_os"]["source_consistent"] is False and b2["virtme_ng"]["source_consistent"] is True
       and b2["syzkaller"]["source_consistent"] is True)
    ck("install_gate(None) → not allowed", R.install_gate(None)["install_allowed"] is False)
    # a hypothetical adopted entry opens the gate only with ALL three: adopted state + verdict + justification
    e = C.get("virtme-ng", cat)
    e.gap_justification = C.GapJustification("g", "w", ("a",))
    e.certification = C.Verdict.NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE
    ck("install_gate stays closed while state is not ADOPTED, even with verdict + justification",
       R.install_gate(e)["install_allowed"] is False)
    e.state = C.LabState.RESTRICTED
    ck("install_gate opens only for ADOPTED + verdict + justification (typed, not hand-set)",
       R.install_gate(e)["install_allowed"] is True)
    e.certification = C.Verdict.SUSPICIOUS
    ck("install_gate closes again on a SUSPICIOUS verdict", R.install_gate(e)["install_allowed"] is False)

    # ── §102/§150 feature-registry rows: present, additive, DEPLOYED-dark ──
    ids = {"os_lab", "os_lab_ultron_sandbox", "os_lab_virtme_ng", "os_lab_syzkaller"}
    rows = {r["feature_id"]: r for r in R.os_lab_feature_registry(off)}
    ck("feature rows present (os_lab, ultron, virtme_ng, syzkaller)", set(rows) == ids)
    ck("feature rows: deployed=True, runtime_enabled=False (dark), production_use NO — flags absent",
       all(r["deployed"] is True and r["runtime_enabled"] is False and r["production_use"] == "NO" for r in rows.values()))
    ck("feature rows: only the framework is 'installed'; every runtime installed=False + UNVERIFIED",
       rows["os_lab"]["installed"] is True and rows["os_lab"]["verification"] == "SELF_TEST"
       and all(rows[i]["installed"] is False and rows[i]["verification"] == "UNVERIFIED" for i in ids - {"os_lab"}))
    ck("feature rows: dispositions match the runtime records (Ultron sandbox / kernel-test / security-lab)",
       rows["os_lab_ultron_sandbox"]["disposition"] == "EDUCATIONAL_OS_SANDBOX"
       and rows["os_lab_virtme_ng"]["disposition"] == "RESTRICTED_KERNEL_TEST_RUNTIME"
       and rows["os_lab_syzkaller"]["disposition"] == "RESTRICTED_SECURITY_LAB")
    ck("feature rows: syzkaller is P3 (authority-class), the rest P2 (dormant execution capability)",
       rows["os_lab_syzkaller"]["risk_class"] == "P3" and all(rows[i]["risk_class"] == "P2" for i in ids - {"os_lab_syzkaller"}))
    prod_rows = {r["feature_id"]: r for r in R.os_lab_feature_registry(prod_on)}
    ck("feature rows: production with every flag on → runtime_enabled still False for all",
       all(r["runtime_enabled"] is False for r in prod_rows.values()))
    ck("feature rows use the holding_deployment.Feature shape (same keys + extras), additive — FEATURE_REGISTRY untouched",
       {"feature_id", "name", "risk_class", "certification", "runtime_flag", "introduced_sha", "runtime_enabled", "deployed"}
       <= set(rows["os_lab"]) and not any(f.feature_id.startswith("os_lab") for f in __import__(
           "app.services.holding.holding_deployment", fromlist=["FEATURE_REGISTRY"]).FEATURE_REGISTRY))
    ck("no OS-lab flag is declared in app/config.py (absent → OFF everywhere, §102)",
       not any(f in (Path(__file__).resolve().parents[3] / "config.py").read_text(encoding="utf-8")
               for f in (R.FLAG_OS_LAB, R.FLAG_ULTRON, R.FLAG_VIRTME_NG, R.FLAG_SYZKALLER)))

    # ── assembled view ──
    view = R.os_lab_view(staging_on, cat)
    ck("os_lab_view: state CATALOG_ONLY, executed all False, catalog_binding + features present",
       view["state"] == "CATALOG_ONLY" and not any(view["executed"].values())
       and set(view["catalog_binding"]) == {"ultron_os", "virtme_ng", "syzkaller"} and len(view["features"]) == 4)
    ck("os_lab_view never says MALWARE_FREE/SAFE/CLEAN anywhere",
       not re.search(r"\b(MALWARE_FREE|VERIFIED_SAFE)\b", repr(view)))

    n = len(res); ok = sum(res)
    print(f"\nOS LAB RUNTIMES TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


def test_os_lab_runtimes():
    assert run()


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
