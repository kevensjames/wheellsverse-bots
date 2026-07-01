from core.portfolio import registry
from core.portfolio.actions import Action, ActionClass
from core.portfolio.adapters.leads import LeadsAdapter
from core.portfolio.adapters.outreach_draft import OutreachDraftAdapter
from core.portfolio.adapters.proposal import ProposalAdapter
from core.portfolio.adapters.research import ResearchAdapter
from core.portfolio.adapters.site import SiteAdapter


def _act(slug):
    return Action(verb="x", agent="", action_class=ActionClass.GREEN,
                  preconditions=[], business=slug, payload={})


def test_content_adapters_consume_kit_for_all_10(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    # no generate injected -> if it returns real bytes, the content came from the kit
    steps = {"research": ResearchAdapter(), "outreach": OutreachDraftAdapter(),
             "site": SiteAdapter(), "proposal": ProposalAdapter()}
    for b in registry.list_businesses():
        for name, a in steps.items():
            r = a.run(_act(b.slug))
            assert r["source"] == "gtm_kit" and r["bytes"] > 100, (b.slug, name)


def test_leads_adapter_scopes_to_each_business_niche_and_geo(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)  # -> dry-run
    a = LeadsAdapter()
    r = a.run(_act("coolify"))
    assert r["mode"] == "dry_run"
    assert r["niche"] == "web design and development agencies"
    assert r["geo"] == "Austin, Texas"
    r2 = a.run(_act("medusa"))
    assert r2["geo"] == "Portland, Oregon"   # different business -> different geo
