"""OS Lab §41/§114 supply-chain certification pipeline + report, and the §143 safe-fixture static scanner.

CATALOG-FIRST (§113/§117/§160). This module DEFINES the full pipeline (typed, ordered steps) and can RUN
only its PURE STATIC checks over a supplied local inventory (in-memory ``RepoInventory`` or a read-only
walk of a local directory the operator already has). It never clones, downloads, installs, builds,
opens a network connection, or boots QEMU — the executable steps are always SKIPPED here with the
reason EXECUTION_GATED, and a test asserts the source contains no subprocess/socket/urllib/git imports.

Verdict vocabulary is the bounded catalog.Verdict (§114): NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE
/ SUSPICIOUS / REJECTED / UNVERIFIED. Because the build/exec steps cannot run in this phase, the static
runner can NEVER emit the clean-scope verdict — the best a static-only report can say is UNVERIFIED.

Zero-fabrication (§0 #16-19): every step starts PENDING; a check that cannot be decided from the supplied
inventory returns UNVERIFIED, never PASS. Snippets in findings pass through the shared ``redact``.

Reuses: catalog.Verdict + catalog._SHA_RE (§41 pin), runtimes.EXECUTED (what this phase executed = nothing),
security.models.Severity values, the core.security_scanner regex table (additively, when importable) and
task_resolver.redact. Pure stdlib otherwise; plain-python3 testable.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path, PurePosixPath

from app.services.holding.task_resolver import redact
from app.services.holding.os_lab.catalog import Verdict, _SHA_RE
from app.services.holding.os_lab.runtimes import EXECUTED

PIPELINE_VERSION = "1.0.0"
EXECUTION_GATED = "EXECUTION_GATED: requires isolated infra + supply-chain cert (§41 later gated step) — not run here"


# ── vocab ─────────────────────────────────────────────────────────────────────
class StepStatus(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    UNVERIFIED = "UNVERIFIED"


class Phase(str, Enum):
    STATIC = "STATIC"           # pure check over the supplied inventory — runnable in this phase
    BUILD = "BUILD"             # needs an isolated build host — gated
    EXECUTION = "EXECUTION"     # needs restricted network / QEMU / monitoring — gated
    ARTIFACT = "ARTIFACT"       # inspects build outputs — gated (there are none until BUILD runs)


@dataclass(frozen=True)
class StepDef:
    """One typed pipeline step. ``check`` names the pure static function (STATIC only); gated steps have none."""
    id: str
    title: str
    phase: Phase
    check: str = ""
    observes: tuple[str, ...] = ()     # what the gated step will record when it eventually runs


# The ONE ordered pipeline (§41). Position == order.
PIPELINE: tuple[StepDef, ...] = (
    StepDef("canonical_upstream", "Canonical upstream verified against the catalog", Phase.STATIC, "check_canonical_upstream"),
    StepDef("pin_sha", "Pinned to a full commit SHA / release", Phase.STATIC, "check_pin_sha"),
    StepDef("license", "License file present + identifier stated", Phase.STATIC, "check_license"),
    StepDef("file_inventory", "Full file inventory with digests", Phase.STATIC, "check_file_inventory"),
    StepDef("submodules", "Git submodules (each widens the supply chain)", Phase.STATIC, "check_submodules"),
    StepDef("git_lfs", "Git LFS pointers (content absent from inventory)", Phase.STATIC, "check_git_lfs"),
    StepDef("binary_blobs", "Binary blobs in a source repository", Phase.STATIC, "check_binary_blobs"),
    StepDef("package_manifests", "Package manifests pinned by lockfiles", Phase.STATIC, "check_package_manifests"),
    StepDef("install_hooks", "Install-time hooks (lifecycle scripts, cmdclass)", Phase.STATIC, "check_install_hooks"),
    StepDef("build_scripts", "Build scripts inventoried + swept", Phase.STATIC, "check_build_scripts"),
    StepDef("dockerfiles", "Dockerfiles inventoried + swept", Phase.STATIC, "check_dockerfiles"),
    StepDef("ci_workflows", "CI workflows inventoried + swept", Phase.STATIC, "check_ci_workflows"),
    StepDef("shell_scripts", "Shell scripts inventoried + swept", Phase.STATIC, "check_shell_scripts"),
    StepDef("network_destinations", "Network clients + outbound destinations vs. expected hosts", Phase.STATIC, "check_network_destinations"),
    StepDef("telemetry", "Telemetry / analytics / crash reporting", Phase.STATIC, "check_telemetry"),
    StepDef("privileged_ops", "Privileged operations", Phase.STATIC, "check_privileged_ops"),
    StepDef("credential_reads", "Credential-file / secret-store reads + embedded credential material", Phase.STATIC, "check_credential_reads"),
    StepDef("persistence", "Persistence mechanisms", Phase.STATIC, "check_persistence"),
    StepDef("downloaded_binaries", "Binaries downloaded at build/install time", Phase.STATIC, "check_downloaded_binaries"),
    StepDef("obfuscation", "Obfuscation / encoded payloads", Phase.STATIC, "check_obfuscation"),
    # ── gated: never executed in this phase ──
    StepDef("isolated_build", "Isolated build (no host access)", Phase.BUILD,
            observes=("build_log_digest", "toolchain", "exit_status")),
    StepDef("restricted_network", "Build/run under restricted (default-deny) network", Phase.EXECUTION,
            observes=("egress_policy", "attempted_destinations")),
    StepDef("qemu_vm_exec", "Execution in a disposable QEMU/VM", Phase.EXECUTION,
            observes=("image_digest", "boot_status", "snapshot_discarded")),
    StepDef("resource_monitoring", "CPU/RAM/disk/IO monitoring during execution", Phase.EXECUTION,
            observes=("cpu_peak", "ram_peak_mb", "disk_delta_mb", "io_bytes")),
    StepDef("dynamic_behavior", "Dynamic behavior observation", Phase.EXECUTION,
            observes=("fs_mutations", "network_attempts", "process_tree", "persistence_attempts", "credential_access")),
    StepDef("artifact_inspection", "Inspection of produced artifacts", Phase.ARTIFACT,
            observes=("artifact_digests", "unexpected_artifacts", "embedded_binaries")),
)
STATIC_STEPS = tuple(s for s in PIPELINE if s.phase == Phase.STATIC)
GATED_STEPS = tuple(s for s in PIPELINE if s.phase != Phase.STATIC)


# ── inventory (supplied; never fetched) ───────────────────────────────────────
@dataclass
class InvFile:
    path: str
    size: int = 0
    sha256: str = ""
    content: str | None = None      # text content when readable; None = binary or not read
    is_binary: bool = False

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name

    @property
    def ext(self) -> str:
        return PurePosixPath(self.path).suffix.lower()


@dataclass
class RepoInventory:
    """What the operator's tooling observed in a LOCAL checkout. Nothing here was fetched by this module."""
    name: str
    canonical_source: str                # expected (from the catalog entry)
    files: list[InvFile] = field(default_factory=list)
    observed_source: str = ""            # the checkout's origin as supplied; "" = not supplied
    source_verified_at: str = ""         # evidence from the §113 SOURCE_VERIFIED transition; "" = none
    pinned_sha: str = ""
    license_id: str = ""                 # SPDX id as stated by operator/tooling; "" = not stated
    expected_hosts: tuple[str, ...] = () # extra hosts the operator declares legitimate (e.g. website)

    def text_files(self) -> list[InvFile]:
        return [f for f in self.files if f.content is not None and not f.is_binary]


_MAX_READ = 1_000_000
DOTFILES_KEPT = frozenset({".github", ".gitlab", ".circleci", ".gitlab-ci.yml", ".travis.yml", ".gitmodules",
                           ".gitattributes", ".npmrc", ".yarnrc", ".yarnrc.yml", ".cargo"})


def inventory_from_dir(root: str | Path, *, name: str, canonical_source: str, max_files: int = 5000,
                       **kw) -> RepoInventory:
    """Read-only walk of a LOCAL directory the operator already has (never a clone). Dotfiles are skipped
    (.git internals are not source) EXCEPT the supply-chain-relevant ones below: CI definitions, submodule /
    LFS declarations, and package-registry configs (a shipped .npmrc can redirect installs). Reads only."""
    r = Path(root).resolve()
    files: list[InvFile] = []
    for p in sorted(r.rglob("*")):
        if len(files) >= max_files:
            break
        rel = p.relative_to(r).as_posix()
        parts = rel.split("/")
        if any(x.startswith(".") and x not in DOTFILES_KEPT for x in parts):
            continue
        if not p.is_file():
            continue
        raw = p.read_bytes()[:_MAX_READ]
        binary = b"\0" in raw[:8192]
        files.append(InvFile(rel, p.stat().st_size, hashlib.sha256(raw).hexdigest(),
                             None if binary else raw.decode("utf-8", errors="replace"), binary))
    return RepoInventory(name=name, canonical_source=canonical_source, files=files, **kw)


# ── findings / results / report ───────────────────────────────────────────────
SEVERITIES = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")      # security.models.Severity values
ESCALATES = frozenset({"MEDIUM", "HIGH", "CRITICAL"})            # a finding at this level FAILs its step
REJECTS = frozenset({"HIGH", "CRITICAL"})                        # ... and this level yields verdict REJECTED


@dataclass(frozen=True)
class Finding:
    step: str
    severity: str
    path: str
    detail: str          # redacted
    line: int = 0


@dataclass
class StepResult:
    id: str
    title: str
    phase: str
    status: StepStatus = StepStatus.PENDING
    findings: list[Finding] = field(default_factory=list)
    note: str = ""
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class CertificationReport:
    """§41/§114 standardized report. ``new_report`` is the TEMPLATE: every step PENDING, verdict UNVERIFIED."""
    subject: str
    canonical_source: str
    pinned_sha: str = "UNVERIFIED"
    pipeline_version: str = PIPELINE_VERSION
    scope: str = "NOT_RUN"                   # NOT_RUN | STATIC_ONLY | FULL (FULL only after gated steps)
    steps: list[StepResult] = field(default_factory=list)
    verdict: Verdict = Verdict.UNVERIFIED
    executed: dict = field(default_factory=lambda: dict(EXECUTED))
    generated_at: str = "UNKNOWN"            # caller stamps (no clock here)
    authority_plane: str = "KAI"             # §165 — a report is evidence, never an authority

    def step(self, step_id: str) -> StepResult:
        return next(s for s in self.steps if s.id == step_id)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        d["steps"] = [s.to_dict() for s in self.steps]
        d["findings_by_severity"] = {sev: sum(1 for s in self.steps for f in s.findings if f.severity == sev)
                                     for sev in SEVERITIES}
        return d


def new_report(subject: str, canonical_source: str) -> CertificationReport:
    return CertificationReport(subject=subject, canonical_source=canonical_source,
                               steps=[StepResult(s.id, s.title, s.phase.value) for s in PIPELINE])


def derive_verdict(steps: list[StepResult]) -> Verdict:
    """Bounded + deterministic. Any HIGH/CRITICAL finding → REJECTED; any FAIL → SUSPICIOUS; every step PASS →
    NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE; anything else (PENDING/SKIPPED/UNVERIFIED) → UNVERIFIED."""
    if any(f.severity in REJECTS for s in steps for f in s.findings):
        return Verdict.REJECTED
    if any(s.status == StepStatus.FAIL for s in steps):
        return Verdict.SUSPICIOUS
    if steps and all(s.status == StepStatus.PASS for s in steps):
        return Verdict.NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE
    return Verdict.UNVERIFIED


# ── pattern tables (compact; core.security_scanner's table is added when importable) ──────
def _rx(*pats: str) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p, re.IGNORECASE | re.MULTILINE) for p in pats)


_PIPE_TO_SHELL = _rx(r"(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba|z|k|da)?sh\b")
# Every table below is swept REPO-WIDE (all non-doc text files) by its categorical step, so an embedded key,
# reverse shell or disk wipe in an ordinary source file is found — not only in scripts.
_NET_CLIENT = _rx(r"bash\s+-i\s+>&\s*/dev/tcp", r"nc\s+(?:-e|-c)\s", r"python[23]?\s+-c\s+.*import\s+socket")
_DESTRUCTIVE = _rx(r"rm\s+-rf\s+/(?:\s|$|\*)", r"dd\s+if=.*of=/dev/", r"\bmkfs\.")
_CRED = _rx(r"~/\.ssh/", r"\bid_(?:rsa|ed25519|ecdsa|dsa)\b", r"\.aws/credentials", r"\.netrc\b", r"/etc/shadow\b",
            r"\.docker/config\.json", r"\.kube/config", r"\.gnupg/", r"\bkeychain\b", r"Login Data\b",
            r"\.git-credentials", r"\.npmrc\b", r"\.pypirc\b",
            # embedded credential MATERIAL (not just a path to it)
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_PERSIST = _rx(r"\bcrontab\b", r"@reboot\b", r"/etc/cron\.", r"systemctl\s+enable", r"\.(?:bashrc|zshrc|profile|bash_profile)\b",
               r"Launch(?:Agents|Daemons)", r"/etc/rc\.local", r"/etc/init\.d/", r"CurrentVersion\\+Run")
_PRIV = _rx(r"\bsudo\b", r"\bset(?:uid|gid)\b", r"chmod\s+(?:[ugo]*\+s|[2467][0-7]{3})\b", r"--privileged\b", r"CAP_SYS_ADMIN",
            r"/dev/(?:k?mem|sd[a-z]|nvme)", r"\b(?:insmod|modprobe|rmmod)\b", r"\biptables\b", r"^\s*mount\s+")
_TELEMETRY = _rx(r"\btelemetry\b", r"\banalytics\b", r"crash[_ -]?report", r"usage[_ -]?stat", r"sentry\.io", r"segment\.io",
                 r"\bmixpanel\b", r"\bposthog\b", r"google-analytics")
_DOWNLOAD = _rx(r"(?:curl|wget)\b[^\n|]*\.(?:tar\.gz|tgz|tar\.xz|zip|deb|rpm|bin|exe|dmg|pkg|AppImage|run)\b",
                r"^\s*ADD\s+https?://")
_OBFUSC_HIGH = _rx(r"eval\s*\(\s*(?:base64|atob)", r"exec\s*\(\s*(?:base64|compile)", r"String\.fromCharCode\s*\((?:\s*\d+\s*,){8,}",
                   r"(?:\\x[0-9a-f]{2}){12,}")
# ponytail: 160+ contiguous base64 chars = "blob"; skips sha512-hex (128). Tune if lockfile integrity strings ever exceed it.
_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{160,}={0,2}")
_URL_HOST = re.compile(r"https?://([A-Za-z0-9.-]+\.[A-Za-z]{2,})", re.IGNORECASE)
_CI_RISK = _rx(r"pull_request_target", r"\$\{\{\s*secrets\.")
_HOOK = _rx(r"\"(?:pre|post)?install\"\s*:", r"\bcmdclass\b")

KNOWN_REGISTRY_HOSTS = frozenset({
    "github.com", "raw.githubusercontent.com", "objects.githubusercontent.com", "gitlab.com", "pypi.org",
    "files.pythonhosted.org", "registry.npmjs.org", "crates.io", "static.crates.io", "proxy.golang.org", "sum.golang.org",
    "kernel.org", "git.kernel.org", "cdn.kernel.org", "www.freebsd.org", "git.freebsd.org", "docs.python.org",
    "opensource.org", "www.gnu.org", "spdx.org", "www.apache.org", "creativecommons.org",
})
DOC_EXTS = frozenset({".md", ".rst", ".txt", ".adoc", ".html", ".htm"})
BINARY_EXTS = frozenset({".exe", ".dll", ".so", ".dylib", ".bin", ".elf", ".o", ".a", ".jar", ".wasm", ".img", ".iso",
                         ".pyc", ".class", ".dmg", ".pkg", ".deb", ".rpm"})
# media/fonts are binary too but not executable: reported (LOW), not escalated — otherwise every repo with a
# README screenshot is SUSPICIOUS and the step carries no signal.
MEDIA_EXTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".woff", ".woff2", ".ttf", ".otf"})
LICENSE_NAMES = ("license", "licence", "copying", "unlicense", "notice")
LOCKFILES = {  # manifest name -> acceptable lockfiles
    "package.json": ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json", "bun.lockb"),
    "requirements.txt": ("requirements.txt",),           # pinned-by-convention; content pinning is a later audit
    "pyproject.toml": ("poetry.lock", "uv.lock", "pdm.lock", "requirements.txt"),
    "Cargo.toml": ("Cargo.lock",), "go.mod": ("go.sum",), "Gemfile": ("Gemfile.lock",),
    "composer.json": ("composer.lock",), "Pipfile": ("Pipfile.lock",),
}
BUILD_NAMES = ("makefile", "gnumakefile", "cmakelists.txt", "configure", "configure.ac", "meson.build", "build.sh",
               "build.py", "setup.py", "build.gradle", "build.rs", "justfile", "bazel", "build", "workspace")
SHELL_EXTS = frozenset({".sh", ".bash", ".zsh", ".ksh"})


def _core_patterns() -> list[tuple[re.Pattern, str, str]]:
    """core.security_scanner's regex table, added to the generic sweep when importable (it needs the repo root
    on the path; absent it the sweep runs on the built-in table and the report says so)."""
    try:
        from core.security_scanner import _COMPILED_PATTERNS
        return list(_COMPILED_PATTERNS)
    except Exception:
        return []


def _hit(step: str, sev: str, f: InvFile, m: re.Match, label: str = "") -> Finding:
    line = f.content.count("\n", 0, m.start()) + 1 if f.content else 0
    snippet = f.content[max(0, m.start() - 20):m.end() + 20].replace("\n", " ").strip() if f.content else ""
    return Finding(step, sev, f.path, redact(f"{label + ': ' if label else ''}…{snippet[:100]}…"), line)


def _sweep(step: str, files: list[InvFile], pats, sev: str, label: str = "") -> list[Finding]:
    out = []
    for f in files:
        for p in pats:
            for m in p.finditer(f.content):
                out.append(_hit(step, sev, f, m, label))
    return out


def _generic_sweep(step: str, files: list[InvFile]) -> tuple[list[Finding], str]:
    """Script-type files (build/docker/CI/shell) get pipe-to-shell + the whole core.security_scanner table as a
    second opinion; the categorical tables above already cover every text file repo-wide."""
    fnd = _sweep(step, files, _PIPE_TO_SHELL, "HIGH", "pipe-to-shell")
    core = _core_patterns()
    for f in files:
        for p, sev, desc in core:
            m = p.search(f.content)
            if m:
                fnd.append(_hit(step, sev, f, m, desc))
    src = f"built-in + core.security_scanner ({len(core)} patterns)" if core else "built-in only (core.security_scanner not importable)"
    return fnd, src


def _status(findings: list[Finding]) -> StepStatus:
    return StepStatus.FAIL if any(f.severity in ESCALATES for f in findings) else StepStatus.PASS


def _code(inv: RepoInventory) -> list[InvFile]:
    return [f for f in inv.text_files() if f.ext not in DOC_EXTS]


# ── the pure static checks (each: inventory -> (status, findings, note, evidence)) ─────────
def _norm_origin(u: str) -> str:
    u = u.strip().rstrip("/").lower()
    return u[:-4] if u.endswith(".git") else u     # https://host/o/r.git == https://host/o/r


def check_canonical_upstream(inv):
    if not inv.observed_source:
        return StepStatus.UNVERIFIED, [], "no observed origin supplied — cannot compare to the catalog's canonical_source", {}
    if _norm_origin(inv.observed_source) != _norm_origin(inv.canonical_source):
        return StepStatus.FAIL, [Finding("canonical_upstream", "HIGH", "", redact(
            f"origin {inv.observed_source!r} != canonical {inv.canonical_source!r}"))], "origin mismatch", {}
    if not inv.source_verified_at:
        return StepStatus.UNVERIFIED, [], "origin matches but no SOURCE_VERIFIED evidence (§113) — not fetched here", {}
    return StepStatus.PASS, [], "", {"verified_at": inv.source_verified_at}


def check_pin_sha(inv):
    if not inv.pinned_sha:
        return StepStatus.UNVERIFIED, [], "no pin supplied", {}
    if not _SHA_RE.fullmatch(inv.pinned_sha):
        return StepStatus.FAIL, [Finding("pin_sha", "MEDIUM", "", f"pin {inv.pinned_sha[:12]!r} is not a full 40-hex commit sha (§41)")], "", {}
    return StepStatus.PASS, [], "", {"sha": inv.pinned_sha}


def check_license(inv):
    lic = [f.path for f in inv.files if f.name.lower().split(".")[0] in LICENSE_NAMES]
    if not lic:
        return StepStatus.FAIL, [Finding("license", "MEDIUM", "", "no LICENSE/COPYING file — unlicensed code cannot be adopted")], "", {}
    if not inv.license_id:
        return StepStatus.UNVERIFIED, [], f"license file present ({lic[0]}) but identifier not stated", {"files": lic}
    return StepStatus.PASS, [], "", {"files": lic, "license_id": inv.license_id}


def check_file_inventory(inv):
    bad = [f.path for f in inv.files if not f.path or not f.sha256]
    if not inv.files:
        return StepStatus.FAIL, [Finding("file_inventory", "MEDIUM", "", "empty inventory")], "", {}
    if bad:
        return StepStatus.FAIL, [Finding("file_inventory", "MEDIUM", p or "?", "file without path/digest") for p in bad], "", {}
    return StepStatus.PASS, [], "", {"files": len(inv.files), "bytes": sum(f.size for f in inv.files)}


def check_submodules(inv):
    gm = next((f for f in inv.files if f.name == ".gitmodules"), None)
    if gm is None:
        return StepStatus.PASS, [], "no .gitmodules", {}
    urls = re.findall(r"url\s*=\s*(\S+)", gm.content or "")
    return StepStatus.UNVERIFIED, [Finding("submodules", "LOW", gm.path, redact(f"submodule: {u}")) for u in urls], \
        f"{len(urls)} submodule(s) — each is a separate supply chain needing its own certification", {"urls": urls}


def check_git_lfs(inv):
    ptr = [f.path for f in inv.text_files() if f.content.startswith("version https://git-lfs.github.com/spec/")]
    ga = next((f for f in inv.files if f.name == ".gitattributes"), None)
    tracked = bool(ga and ga.content and "filter=lfs" in ga.content)
    if not ptr and not tracked:
        return StepStatus.PASS, [], "no LFS", {}
    return StepStatus.UNVERIFIED, [Finding("git_lfs", "LOW", p, "LFS pointer — content not in inventory") for p in ptr], \
        "LFS content is outside the inventory; must be fetched + hashed under the gated step", {"pointers": ptr}


def check_binary_blobs(inv):
    blobs = [f for f in inv.files if f.is_binary or f.ext in BINARY_EXTS]
    fnd = [Finding("binary_blobs", "LOW" if f.ext in MEDIA_EXTS else "MEDIUM", f.path,
                   f"binary blob ({f.size} bytes) in a source repo — unreviewable statically") for f in blobs]
    return _status(fnd), fnd, "", {"count": len(blobs)}


def check_package_manifests(inv):
    names = {f.name for f in inv.files}
    fnd, seen = [], []
    for man, locks in LOCKFILES.items():
        if man in names:
            seen.append(man)
            if not any(l in names for l in locks):
                fnd.append(Finding("package_manifests", "MEDIUM", man, f"{man} without a lockfile ({'/'.join(locks)}) — dependencies unpinned"))
    return _status(fnd), fnd, "" if seen else "no package manifests", {"manifests": seen}


def check_install_hooks(inv):
    targets = [f for f in inv.text_files() if f.name in ("package.json", "setup.py")]
    fnd = _sweep("install_hooks", targets, _HOOK, "MEDIUM", "install-time hook")
    return _status(fnd), fnd, "", {}


def _swept(step, files, extra=(), extra_sev="MEDIUM"):
    fnd, src = _generic_sweep(step, files)
    if extra:
        fnd += _sweep(step, files, extra, extra_sev)
    return _status(fnd), fnd, f"{len(files)} file(s) swept; contents still require BUILD_REVIEW" if files else "none present", \
        {"files": [f.path for f in files], "sweep": src}


def check_build_scripts(inv):
    return _swept("build_scripts", [f for f in _code(inv) if f.name.lower() in BUILD_NAMES])


def check_dockerfiles(inv):
    return _swept("dockerfiles", [f for f in _code(inv) if f.name.lower().startswith("dockerfile") or f.ext == ".dockerfile"],
                  _DOWNLOAD)     # --privileged / sudo etc. are caught repo-wide by check_privileged_ops


def check_ci_workflows(inv):
    ci = [f for f in _code(inv) if f.path.startswith((".github/workflows/", ".gitlab-ci", ".circleci/", ".travis"))
          or f.name in ("Jenkinsfile", ".gitlab-ci.yml", "azure-pipelines.yml")]
    return _swept("ci_workflows", ci, _CI_RISK)


def check_shell_scripts(inv):
    return _swept("shell_scripts", [f for f in _code(inv) if f.ext in SHELL_EXTS or f.content.startswith("#!")])


def check_network_destinations(inv):
    expected = {h.lower() for h in inv.expected_hosts} | KNOWN_REGISTRY_HOSTS
    for u in (inv.canonical_source, inv.observed_source):
        m = _URL_HOST.search(u or "")
        if m:
            expected.add(m.group(1).lower())
    fnd, hosts = _sweep("network_destinations", _code(inv), _NET_CLIENT, "HIGH", "reverse-shell network client"), {}
    for f in inv.text_files():
        for m in _URL_HOST.finditer(f.content):
            h = m.group(1).lower()
            hosts.setdefault(h, f.path)
            if h not in expected:
                fnd.append(_hit("network_destinations", "LOW" if f.ext in DOC_EXTS else "MEDIUM", f, m, "unexpected outbound host"))
    return _status(fnd), fnd, "", {"hosts": sorted(hosts), "expected": sorted(expected)}


def check_telemetry(inv):
    fnd = _sweep("telemetry", _code(inv), _TELEMETRY, "MEDIUM", "telemetry")
    return _status(fnd), fnd, "", {}


def check_privileged_ops(inv):
    fnd = _sweep("privileged_ops", _code(inv), _PRIV, "MEDIUM", "privileged op") \
        + _sweep("privileged_ops", _code(inv), _DESTRUCTIVE, "HIGH", "destructive op")
    return _status(fnd), fnd, "", {}


def check_credential_reads(inv):
    fnd = _sweep("credential_reads", _code(inv), _CRED, "HIGH", "credential path/material")
    return _status(fnd), fnd, "", {}


def check_persistence(inv):
    fnd = _sweep("persistence", _code(inv), _PERSIST, "HIGH", "persistence")
    return _status(fnd), fnd, "", {}


def check_downloaded_binaries(inv):
    fnd = _sweep("downloaded_binaries", _code(inv), _DOWNLOAD, "MEDIUM", "download") \
        + _sweep("downloaded_binaries", _code(inv), _PIPE_TO_SHELL, "HIGH", "pipe-to-shell")
    return _status(fnd), fnd, "", {}


def check_obfuscation(inv):
    fnd = _sweep("obfuscation", _code(inv), _OBFUSC_HIGH, "HIGH", "obfuscation")
    for f in _code(inv):
        for m in _B64_BLOB.finditer(f.content):
            fnd.append(Finding("obfuscation", "MEDIUM", f.path, f"base64-like blob ({m.end() - m.start()} chars) — encoded payload candidate",
                               f.content.count("\n", 0, m.start()) + 1))
    return _status(fnd), fnd, "", {}


# ── runner ────────────────────────────────────────────────────────────────────
def run_static(inv: RepoInventory, *, at: str = "UNKNOWN") -> CertificationReport:
    """Run every STATIC step in pipeline order over the supplied inventory; every gated step is SKIPPED
    (EXECUTION_GATED). Verdict is derived, bounded, and can never be the clean-scope verdict from here."""
    rep = new_report(inv.name, inv.canonical_source)
    rep.pinned_sha = inv.pinned_sha or "UNVERIFIED"
    rep.scope = "STATIC_ONLY"
    rep.generated_at = at
    for sd, sr in zip(PIPELINE, rep.steps):
        if sd.phase != Phase.STATIC:
            sr.status, sr.note = StepStatus.SKIPPED, EXECUTION_GATED
            sr.evidence = {"observes": list(sd.observes)}
            continue
        sr.status, sr.findings, sr.note, sr.evidence = globals()[sd.check](inv)
    rep.verdict = derive_verdict(rep.steps)
    return rep


# ── §143 safe fixtures (benign mimics; nothing here functions as malware) ─────
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "mimic_repo"
FIXTURE_CANONICAL = "https://example.invalid/os-lab/mimic-repo"    # RFC 2606 reserved: can never resolve
# fixture file -> the step that must FAIL because of it
FIXTURE_EXPECT = {
    "install.sh": "downloaded_binaries",     # literal 'curl … | bash'
    "keyreader.py": "credential_reads",      # '~/.ssh/id_rsa' path string
    "persist.sh": "persistence",             # crontab @reboot string
    "blob.js": "obfuscation",                # base64-like blob
    "telemetry.py": "network_destinations",  # unexpected outbound hostname
    "package.json": "install_hooks",         # postinstall lifecycle hook
}


def fixture_inventory() -> RepoInventory:
    return inventory_from_dir(FIXTURE_DIR, name="mimic_repo (§143 fixture)", canonical_source=FIXTURE_CANONICAL)


def to_json(rep: CertificationReport) -> str:
    return json.dumps(rep.to_dict(), indent=2, sort_keys=True, default=str)
