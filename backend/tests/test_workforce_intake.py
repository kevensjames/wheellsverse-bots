"""Validates the committed upstream-intake manifest (Workforce Phase 2) — the
integrity invariants the intake must uphold, each with a negative control proving
the check has teeth. Pure (json + stdlib); no network, no upstream execution.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

INVENTORY_PATH = (
    Path(__file__).resolve().parents[1]
    / "app" / "services" / "workforce" / "generated" / "upstream_inventory.json"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_REASONS = {
    "INJECTION_PATTERN", "SECRET_EXFIL_PATTERN", "EXEC_CONTENT_PRESENT",
    "PATH_ANOMALY", "NO_FRONTMATTER",
}


def _load():
    return json.loads(INVENTORY_PATH.read_text())


def _validate(inv: dict) -> None:
    """Raise ValueError on any intake-integrity violation."""
    agents = inv["agents"]
    # count is derived, not asserted from a separate literal
    if inv["counts"]["agent_files"] != len(agents):
        raise ValueError("counts.agent_files does not match len(agents)")
    ids = [a["id"] for a in agents]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate agent ids")
    declared = set(inv["reconciliation"].get("declared_not_on_disk", [])) | {a["division"] for a in agents}
    for a in agents:
        if not _SHA256.match(a.get("sha256", "")):
            raise ValueError(f"agent {a['id']} missing/invalid sha256")
        if not a.get("path") or ".." in a["path"]:
            raise ValueError(f"agent {a['id']} has missing/traversing path")
        if not a["path"].startswith(a["division"] + "/"):
            raise ValueError(f"agent {a['id']} path does not match its division")
    # reconciliation must be clean (no undeclared dir, no missing declared dir)
    rec = inv["reconciliation"]
    if rec["declared_not_on_disk"] or rec["on_disk_not_declared"]:
        raise ValueError("filesystem/divisions.json reconciliation not clean")
    # every flag reason code is recognized
    for f in inv["quarantine_findings"]:
        bad = set(f["reason_codes"]) - _ALLOWED_REASONS
        if bad:
            raise ValueError(f"unknown reason codes {bad}")
    # provenance / license present
    if inv["source"]["license"] != "MIT":
        raise ValueError("license is not MIT")
    if not re.match(r"^[0-9a-f]{40}$", inv["source"]["pinned_commit"]):
        raise ValueError("pinned_commit is not a full SHA")
    # file accounting: nothing disappeared — the reconciliation equation balances
    acc = inv["accounting"]
    if acc["included_agent_files"] != len(agents):
        raise ValueError("accounting.included_agent_files != len(agents)")
    if acc["total_files_inspected"] != (
        acc["included_agent_files"] + acc["rejected_agent_candidates"]
        + acc["excluded_non_agent_file_count"]
    ):
        raise ValueError("reconciliation equation does not balance (a file is unaccounted)")
    if not acc["reconciliation_holds"]:
        raise ValueError("reconciliation equation does not balance (reconciliation_holds is False)")


def test_committed_inventory_passes_validation():
    _validate(_load())


def test_count_is_derived_and_nonzero():
    inv = _load()
    assert inv["counts"]["agent_files"] == len(inv["agents"]) == 279  # recursive true count
    assert inv["accounting"]["included_agent_files"] == 279


def test_accounting_equation_holds():
    acc = _load()["accounting"]
    assert acc["reconciliation_holds"] is True
    assert acc["total_files_inspected"] == (
        acc["included_agent_files"] + acc["rejected_agent_candidates"]
        + acc["excluded_non_agent_file_count"]
    )


def test_nc_unaccounted_division_file_breaks_reconciliation():
    # An unclassified markdown introduced inside a declared division would raise
    # total_files_inspected without being counted as included/rejected/excluded,
    # so the equation no longer balances and validation fails closed.
    inv = _load()
    inv["accounting"]["total_files_inspected"] += 1
    with pytest.raises(ValueError, match="reconciliation equation does not balance"):
        _validate(inv)


def test_no_duplicate_ids():
    inv = _load()
    ids = [a["id"] for a in inv["agents"]]
    assert len(set(ids)) == len(ids)
    assert inv["counts"]["duplicate_ids"] == 0 and inv["duplicates"] == {}


def test_provenance_recorded():
    s = _load()["source"]
    assert s["repo_url"].endswith("agency-agents")
    assert s["license"] == "MIT" and "AgentLand" in s["license_holder"]
    assert _SHA256.match(s["pinned_commit"] + "0" * 24)  # 40-hex pinned commit


def test_reconciliation_clean():
    rec = _load()["reconciliation"]
    assert rec["declared_not_on_disk"] == [] and rec["on_disk_not_declared"] == []


def test_every_agent_has_path_and_hash():
    for a in _load()["agents"]:
        assert _SHA256.match(a["sha256"]) and a["path"] and a["division"]


# ─── negative controls: _validate must reject corrupted manifests ──────────


def test_nc_duplicate_id_rejected():
    inv = _load()
    inv["agents"].append(dict(inv["agents"][0]))  # duplicate the first agent
    inv["counts"]["agent_files"] = len(inv["agents"])
    with pytest.raises(ValueError, match="duplicate agent ids"):
        _validate(inv)


def test_nc_missing_hash_rejected():
    inv = _load()
    inv["agents"][0] = {**inv["agents"][0], "sha256": ""}
    with pytest.raises(ValueError, match="sha256"):
        _validate(inv)


def test_nc_count_mismatch_rejected():
    inv = _load()
    inv["counts"]["agent_files"] += 1
    with pytest.raises(ValueError, match="counts.agent_files"):
        _validate(inv)


def test_nc_dirty_reconciliation_rejected():
    inv = _load()
    inv["reconciliation"]["on_disk_not_declared"] = ["rogue_division"]
    with pytest.raises(ValueError, match="reconciliation not clean"):
        _validate(inv)


def test_nc_unknown_reason_code_rejected():
    inv = _load()
    inv["quarantine_findings"] = [{"id": "x", "path": "p", "reason_codes": ["MADE_UP"]}]
    with pytest.raises(ValueError, match="unknown reason codes"):
        _validate(inv)


def test_nc_path_traversal_rejected():
    inv = _load()
    inv["agents"][0] = {**inv["agents"][0], "path": "../escape.md"}
    with pytest.raises(ValueError, match="path"):
        _validate(inv)
