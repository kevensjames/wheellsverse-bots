"""Prove the startup gate admits a correct mission and refuses a tampered one."""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "connector"))
from jail import JailSpec  # noqa: E402
from startup_gate import GateFailed, run_gate  # noqa: E402
import workspace_volume as wv  # noqa: E402

HARNESS = "/Users/jhonwheeler/kai-harness-runtime/deepseek-harness"
DSH_HOME = "/Users/jhonwheeler/kai-harness-runtime/dsh-home"
OV = os.path.abspath(os.path.join(HERE, "..", "harness"))
SCRATCH = os.environ.get("KAI_SCRATCH", "/tmp")
MID = "gate-probe"

failures = []


def dump_for(vol, mode_patch, extra=None):
    argv = ["node", "--import", "tsx/esm", os.path.join(HARNESS, "apps/cli/src/bin.ts"),
            "--profile", "acp",
            "--patch", os.path.join(OV, "00-containment.patch.yml"),
            "--patch", os.path.join(OV, "05-volume-roots.patch.yml"),
            "--patch", os.path.join(OV, "10-model-local-only.patch.yml"),
            "--patch", os.path.join(OV, mode_patch)]
    if extra:
        argv += ["--patch", extra]
    argv += ["--dump-config"]
    env = {**os.environ, "CI": "true", "DSH_HOME": vol.dsh_home,
           "KAI_TASK_WORKSPACE": vol.workspace,
           "KAI_MISSION_SESSION_ROOT": vol.session_root,
           "KAI_MISSION_STORAGE_ROOT": vol.storage_root,
           "KAI_LOCAL_LLM_BASE_URL": "http://127.0.0.1:11434/v1",
           "KAI_LOCAL_LLM_MODEL": "qwen2.5:7b",
           "KAI_LOCAL_LLM_API_KEY": "local-no-auth-required"}
    r = subprocess.run(argv, cwd=HARNESS, env=env, capture_output=True, text=True, timeout=180)
    return r.stdout


try:
    wv.destroy(wv.MissionVolume(MID, f"/Users/jhonwheeler/kai-harness-runtime/volumes/{MID}.sparseimage",
                                f"/Volumes/KAI-{MID}"))
except Exception:
    pass
vol = wv.create(MID, size_mb=128)
try:
    os.makedirs(vol.storage_root, exist_ok=True)
    os.makedirs(vol.tmpdir, exist_ok=True)
    wv.seed_dsh_home(vol, DSH_HOME)
    spec = JailSpec(volume=vol.mount_point, dsh_home=vol.dsh_home,
                    harness_dir=HARNESS, model_base_url="http://127.0.0.1:11434/v1")

    print("=== A. correct missions must be ADMITTED ===")
    for mode, patch in (("OBSERVE", "20-mode-observe.patch.yml"),
                        ("ASSIST", "21-mode-assist.patch.yml"),
                        ("EXECUTE_SCOPED", "22-mode-execute-scoped.patch.yml")):
        try:
            rec = run_gate(mission_id=MID, mode=mode, model_mode="LOCAL_ONLY",
                           dump=dump_for(vol, patch), jail_spec=spec, harness_dir=HARNESS)
            print(f"  PASS  {mode:15s} composition={rec.composition_digest[:12]} "
                  f"config={rec.config_checks_passed}/{rec.config_checks_total} "
                  f"attestation={rec.digest()[:12]}")
        except GateFailed as exc:
            failures.append(f"{mode} rejected")
            print(f"  FAIL  {mode}: {exc}")

    print("\n=== B. tampered missions must be REFUSED ===")
    evil = os.path.join(SCRATCH, "gate-evil.patch.yml")
    with open(evil, "w") as fh:
        fh.write("- insert:\n    - id: kai-rogue-shell\n      name: '@deepseek-ai/dsh-tool-bash'\n")
    try:
        run_gate(mission_id=MID, mode="OBSERVE", model_mode="LOCAL_ONLY",
                 dump=dump_for(vol, "20-mode-observe.patch.yml", evil),
                 jail_spec=spec, harness_dir=HARNESS)
        failures.append("injected plugin admitted")
        print("  FAIL  injected shell plugin was ADMITTED")
    except GateFailed as exc:
        print(f"  PASS  injected shell plugin refused: {str(exc).splitlines()[-1].strip()[:80]}")

    # Mode/policy mismatch: run OBSERVE's gate against EXECUTE_SCOPED's composition.
    try:
        run_gate(mission_id=MID, mode="OBSERVE", model_mode="LOCAL_ONLY",
                 dump=dump_for(vol, "22-mode-execute-scoped.patch.yml"),
                 jail_spec=spec, harness_dir=HARNESS)
        failures.append("mode/policy mismatch admitted")
        print("  FAIL  a write-enabled composition was admitted as OBSERVE")
    except GateFailed as exc:
        print(f"  PASS  write-enabled composition refused as OBSERVE: "
              f"{str(exc).splitlines()[-1].strip()[:80]}")

    # Unimplemented model mode must be refused rather than silently downgraded.
    try:
        run_gate(mission_id=MID, mode="OBSERVE", model_mode="CLOUD_APPROVED",
                 dump=dump_for(vol, "20-mode-observe.patch.yml"),
                 jail_spec=spec, harness_dir=HARNESS)
        failures.append("CLOUD_APPROVED admitted")
        print("  FAIL  CLOUD_APPROVED admitted though no overlay exists")
    except GateFailed as exc:
        print(f"  PASS  CLOUD_APPROVED refused: {str(exc).splitlines()[0][:80]}")
finally:
    wv.destroy(vol)

print("\nRESULT:", "GATE VERIFIED" if not failures else f"FAILED {failures}")
sys.exit(1 if failures else 0)
