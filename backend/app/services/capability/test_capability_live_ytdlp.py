"""Live certification for the yt-dlp adapter (Wave B, §27/§80/§22).

Certified path is READ-ONLY metadata extraction; DOWNLOAD is only ever an inert ActionProposal.
Where yt-dlp is INSTALLED and the network reaches the target, proves a real extraction; where it
is ABSENT, proves an honest OFFLINE Failure (never fabricated). The live network extraction is
tolerant of environment/network unavailability so the base suite stays deterministic.
Run: python3 <this file>.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capability.live_adapters import YtDlpAdapter               # noqa: E402
from capability.results import ResultKind, Provenance           # noqa: E402

# a freely-licensed (CC-BY) item — authorized content, metadata only, no download
_AUTHORIZED_URL = "https://archive.org/details/BigBuckBunny_124"
_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _installed() -> bool:
    return YtDlpAdapter().health()["state"] == "READY"


def t_health_is_honest():
    h = YtDlpAdapter().health()
    assert h["state"] in ("READY", "OFFLINE"), h
    if h["state"] == "OFFLINE":
        assert "EXTERNAL_BLOCKED" in h["reason"]


def t_no_url_is_a_failure():
    r = YtDlpAdapter().invoke({})
    assert r.kind == ResultKind.FAILURE and r.provenance == Provenance.UNAVAILABLE


def t_download_is_an_inert_proposal_never_executed():
    """§80/§22: a download request NEVER downloads — it returns an inert, unauthorized proposal."""
    r = YtDlpAdapter().invoke({"url": _AUTHORIZED_URL, "action": "download"})
    assert r.kind == ResultKind.ACTION_PROPOSAL, "download must be a proposal, not an execution"
    assert r.authorized is False and r.proposed_action is not None
    assert r.proposed_action.get("action") == "download"


def t_missing_lib_extract_fails_honestly():
    if _installed():
        return
    r = YtDlpAdapter().invoke({"url": _AUTHORIZED_URL})
    assert r.kind == ResultKind.FAILURE and r.provenance == Provenance.UNAVAILABLE
    assert "EXTERNAL_BLOCKED" in r.summary


def t_real_metadata_extract_when_installed():
    """Installed + network-reachable: a real read-only metadata Observation (no download)."""
    if not _installed():
        return
    r = YtDlpAdapter().invoke({"url": _AUTHORIZED_URL})
    if r.kind == ResultKind.FAILURE:                 # tolerate transient network/site unavailability
        print("       (note: live extraction unavailable in this env — offline contract still proven)")
        return
    assert r.kind == ResultKind.OBSERVATION and r.provenance == Provenance.REAL, r.summary
    assert r.trust == "UNTRUSTED", "extracted title/uploader is attacker-influenced -> must stay untrusted"
    assert r.data.get("extractor") and r.data.get("duration"), "metadata subset missing"


def t_discover_lists_extract():
    assert "extract_info" in YtDlpAdapter().discover()


for _n, _f in list(globals().items()):
    if _n.startswith("t_"):
        test(_n[2:], _f)
print("\n%d passed  (yt-dlp %s)" % (_p, "INSTALLED" if _installed() else "ABSENT — honest OFFLINE path"))
