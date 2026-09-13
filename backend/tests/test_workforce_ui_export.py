"""Phase 5A — validates the generated UI view-model + that the committed
workforce-data.ts matches a fresh export. Pure (imports the inert catalog); no
network, no execution. This is the backend-side honesty gate for the dark console's
DATA; the Angular source honesty is checked by test_workforce_console_honesty.py
and (in the governed sandbox) by ng test.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_WF = Path(__file__).resolve().parents[1] / "app" / "services" / "workforce"
_DATA_TS = Path(__file__).resolve().parents[2] / "frontend-pilots" / "kai-angular" / "src" / "app" / "workforce" / "workforce-data.ts"


def _mod():
    spec = importlib.util.spec_from_file_location("ui_export", _WF / "ui_export.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def data():
    return _mod().build_ui_data()


def test_319_characters_all_inert(data):
    assert data["generatedFrom"]["characterCount"] == 319
    assert len(data["characters"]) == 319
    assert all(c["status"] == "INERT" for c in data["characters"])
    assert data["generatedFrom"]["allInert"] is True


def test_no_action_admitted_and_canonical_label(data):
    assert data["governance"]["actionsAdmitted"] is False
    assert data["governance"]["notAvailableLabel"] == "NOT AVAILABLE — GOVERNED EXECUTION NOT ADMITTED"


def test_every_example_proposal_is_inert(data):
    assert len(data["exampleProposals"]) >= 3
    for p in data["exampleProposals"]:
        assert p["executesAnything"] is False
        assert p["assignsAnyone"] is False
        assert p["proposalOnly"] is True
        assert p["allMembersInert"] is True
        assert len(p["members"]) <= 7
        if p["feasible"]:
            roles = [m["role"] for m in p["members"]]
            assert "VERIFIER" in roles and "PLANNER" in roles


def test_has_a_feasible_and_a_gap_example(data):
    feas = [p for p in data["exampleProposals"] if p["feasible"]]
    gaps = [p for p in data["exampleProposals"] if p["coverageGap"]["hasGap"]]
    assert feas and gaps  # the console demonstrates both a feasible team and an honest gap


def test_provenance_honest_in_view(data):
    for c in data["characters"]:
        assert c["provenance"]["reviewedBy"] is None  # nothing human-approved
        if c["sourceKind"] == "KAI_NATIVE":
            assert not c["provenance"]["sourceHash"]
        else:
            assert c["provenance"]["sourceHash"]


def test_matrices_and_org_present(data):
    assert len(data["orgChart"]) == 19  # 18 upstream divisions + KAI Native
    assert data["capabilityMatrix"] and data["workplaceMatrix"]
    assert sum(len(g["characterIds"]) for g in data["orgChart"]) == 319


def test_export_is_deterministic():
    m = _mod()
    assert m.build_ui_data() == m.build_ui_data()


def test_committed_ts_matches_fresh_export():
    import json
    m = _mod()
    fresh = m._HEADER + json.dumps(m.build_ui_data(), indent=2, sort_keys=True, ensure_ascii=False) + ";\n"
    assert _DATA_TS.read_text() == fresh, "workforce-data.ts is stale — re-run ui_export.main()"
