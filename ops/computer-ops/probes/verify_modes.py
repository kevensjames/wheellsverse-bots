"""Compose and attest EVERY KAI autonomy mode against the real harness.

Runs `dsh --dump-config` for each mode overlay and asserts the containment invariants
that mode is supposed to have. This is the check that would have caught the tool-bash
egress bypass: it verifies the composed tree, not the overlay's intent.

Exit non-zero if any mode fails.
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "connector"))
from attest import attest  # noqa: E402

HARNESS = "/Users/jhonwheeler/kai-harness-runtime/deepseek-harness"
DSH_HOME = "/Users/jhonwheeler/kai-harness-runtime/dsh-home"
OV = os.path.abspath(os.path.join(HERE, "..", "harness"))

# (label, mode overlay, expected sandbox mode, expected approval policy)
MODES = [
    ("OBSERVE",         "20-mode-observe.patch.yml",        "read-only",      "never"),
    ("ASSIST",          "21-mode-assist.patch.yml",         "read-only",      "ask"),
    ("EXECUTE_SCOPED",  "22-mode-execute-scoped.patch.yml", "workspace-write", "ask"),
]


def dump(mode_file: str) -> str:
    argv = [
        "node", "--import", "tsx/esm", os.path.join(HARNESS, "apps/cli/src/bin.ts"),
        "--profile", "acp",
        "--patch", os.path.join(OV, "00-containment.patch.yml"),
        "--patch", os.path.join(OV, "10-model-local-only.patch.yml"),
        "--patch", os.path.join(OV, mode_file),
        "--dump-config",
    ]
    env = {
        **os.environ,
        "CI": "true",
        "DSH_HOME": DSH_HOME,
        "KAI_TASK_WORKSPACE": "/Users/jhonwheeler/kai-harness-runtime/workspaces/probe",
        "KAI_LOCAL_LLM_BASE_URL": "http://127.0.0.1:11434/v1",
        "KAI_LOCAL_LLM_MODEL": "qwen2.5:7b",
        "KAI_LOCAL_LLM_API_KEY": "local-no-auth-required",
    }
    proc = subprocess.run(argv, cwd=HARNESS, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"dump-config failed for {mode_file}:\n{proc.stderr[-2000:]}")
    return proc.stdout


failed = []
for label, mode_file, sandbox, approval in MODES:
    result = attest(dump(mode_file), expect_sandbox_mode=sandbox,
                    expect_local_only=True, expect_approval_policy=approval)
    status = "PASS" if result.ok else "FAIL"
    print(f"{status}  {label:16s} sandbox={sandbox:15s} approval={approval:6s} {result.summary()}")
    if not result.ok:
        failed.append(label)
        for f in result.failures:
            print(f"        ! {f}")

# danger-full-access must be unreachable in every mode: KAI's preset table replaces
# upstream's, so the preset that pairs it with approval 'never' no longer exists.
for label, mode_file, _s, _a in MODES:
    text = dump(mode_file)
    if "danger-full-access" in text:
        print(f"FAIL  {label}: 'danger-full-access' still present in composed tree")
        failed.append(label)
print("\ndanger-full-access absent from every composed mode: "
      f"{'YES' if not any('danger' in str(f) for f in failed) else 'NO'}")

print("\nRESULT:", "ALL MODES PASS" if not failed else f"FAILED: {failed}")
sys.exit(1 if failed else 0)
