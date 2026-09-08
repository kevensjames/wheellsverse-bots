"""The single gate every KAI computer-operations mission passes before it runs.

Layered, in order, each layer catching what the one before it cannot:

  1. JAIL          kernel-enforced: network denied except the approved model endpoint,
                   writes confined to a separate filesystem, desktop binaries
                   unexecutable. Holds regardless of what the harness loads.
  2. ALLOW-LIST    the composed plugin graph must be exactly what was reviewed. Catches
                   a composition that is wrong -- an upstream addition, a mis-ordered
                   patch, a substituted package.
  3. CONFIG        the policy VALUES the mission was attested with: sandbox mode,
                   approval policy, model route, telemetry.
  4. WORKSPACE     identity and hygiene of the directory the mission will write to.

The order is deliberate. The jail is checked first because it is the only layer that
still holds if the others are wrong, and a mission that cannot be confined must not run
at all. The previous phase's failure was having only layer 3, and a green result from it
while the model executed shell commands unobserved.

Every gate produces an AttestationRecord, which is what KAI stores as mission evidence.
"Nothing could reach the network" then becomes a verifiable claim rather than a belief.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass, field

from allowlist import verify_composition
from attest import attest
from jail import JailSpec, preflight, workspace_identity


class GateFailed(RuntimeError):
    """A mission that fails any layer does not run. There is no override flag."""


@dataclass
class AttestationRecord:
    mission_id: str
    mode: str
    model_mode: str
    harness_commit: str
    composition_digest: str
    config_checks_passed: int
    config_checks_total: int
    plugins_enabled: int
    plugins_disabled: int
    jail_enforced: bool
    volume_mount: str
    volume_is_separate_fs: bool
    workspace_dev_ino: tuple[int, int]
    model_endpoint: str
    violations: list[str] = field(default_factory=list)

    def digest(self) -> str:
        """One value summarising the whole attested posture, for the panel and audit."""
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


#: sandbox mode / approval policy each autonomy mode must compose to. Held here rather
#: than read from the overlay so a changed overlay is detected instead of believed.
MODE_POLICY = {
    "OBSERVE": ("read-only", "never"),
    "ASSIST": ("read-only", "ask"),
    "EXECUTE_SCOPED": ("workspace-write", "ask"),
}


def run_gate(*, mission_id: str, mode: str, model_mode: str, dump: str,
             jail_spec: JailSpec, harness_dir: str) -> AttestationRecord:
    if mode not in MODE_POLICY:
        raise GateFailed(f"unknown autonomy mode {mode!r}")
    if model_mode != "LOCAL_ONLY":
        raise GateFailed(
            f"model mode {model_mode!r} is not implemented; only LOCAL_ONLY has been "
            "verified end to end. CLOUD_APPROVED requires its own overlay and a recorded "
            "operator egress consent.")
    sandbox_mode, approval_policy = MODE_POLICY[mode]
    violations: list[str] = []

    # 1. Jail first: if the boundary does not hold, nothing else matters.
    preflight(jail_spec)
    vol_dev = os.stat(jail_spec.volume).st_dev
    separate_fs = vol_dev != os.stat(os.path.expanduser("~")).st_dev
    if not separate_fs:
        violations.append(
            "mission volume shares a filesystem with the home volume; cross-device link "
            "protection would not apply")

    # 2. Composition allow-list.
    comp = verify_composition(dump)
    violations.extend(comp.violations)

    # 3. Config values.
    cfg = attest(dump, expect_sandbox_mode=sandbox_mode, expect_local_only=True,
                 expect_approval_policy=approval_policy)
    violations.extend(cfg.failures)

    head = subprocess.run(["git", "-C", harness_dir, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    record = AttestationRecord(
        mission_id=mission_id, mode=mode, model_mode=model_mode,
        harness_commit=head,
        composition_digest=comp.digest,
        config_checks_passed=sum(1 for _n, ok, _r in cfg.checks if ok),
        config_checks_total=len(cfg.checks),
        plugins_enabled=len(comp.enabled), plugins_disabled=len(comp.disabled),
        jail_enforced=True,
        volume_mount=jail_spec.volume, volume_is_separate_fs=separate_fs,
        workspace_dev_ino=workspace_identity(jail_spec.workspace),
        model_endpoint=jail_spec.model_base_url,
        violations=violations,
    )
    if violations:
        raise GateFailed(
            f"{len(violations)} containment violation(s); mission {mission_id} will not run:\n"
            + "\n".join(f"  - {v}" for v in violations))
    return record
