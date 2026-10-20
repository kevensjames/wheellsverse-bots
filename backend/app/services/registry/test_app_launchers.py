"""App launcher contract. Run: python3 backend/app/services/registry/test_app_launchers.py."""
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from backend.app.services.registry.catalog import (  # noqa: E402
    systems, Status, DeployState, DataClass, TIER_PLATFORM,
)

APPS = {
    "signalproof": ("SignalProof", "https://signalproof-5utpqh.v2.appdeploy.ai/"),
    "kai-review-desk": ("KAI Review Desk", "https://kai-review-desk-ssmof1.v2.appdeploy.ai/"),
    "creator-studio": ("WheellsVerse Creator Studio", "https://wheellsverse-creator-studio-vcspjf.v2.appdeploy.ai/"),
}


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs))


def test_launchers():
    for page in ("holding.html", "index.html"):
        html = (ROOT / "frontend" / "admin" / page).read_text()
        links = Links(html).links
        assert 'id="h-apps"' in html
        assert "Sign in separately in each app to access private work." in html
        for name, url in APPS.values():
            matches = [link for link in links if link.get("href") == url]
            assert len(matches) == 1, (page, name, "must have exactly one exact app URL")
            link = matches[0]
            assert link.get("target") == "_blank", (page, name)
            assert {"noopener", "noreferrer"} <= set(link.get("rel", "").split()), (page, name)
            assert name in link.get("aria-label", "") and "opens in a new tab" in link["aria-label"], (page, name)
        assert len([link for link in links if ".appdeploy.ai" in link.get("href", "")]) == len(APPS)
    holding = (ROOT / "frontend" / "admin" / "holding.html").read_text()
    assert holding.index('id="p-companies"') < holding.index('id="p-apps"') < holding.index('id="p-missions"')
    assert "label:'Open WheellsVerse Apps', kind:'nav', run:()=>jump('p-apps')" in holding


def test_catalog():
    by_id = {node.id: node for node in systems()}
    for app_id, (name, url) in APPS.items():
        node = by_id[app_id]
        assert (node.name, node.url) == (name, url), app_id
        assert (node.tier, node.status, node.deploy) == (TIER_PLATFORM, Status.EXTERNAL, DeployState.EXTERNAL_SERVICE), app_id
        assert node.probe is None and node.route is None, app_id
        assert node.metrics_class == DataClass.UNAVAILABLE, app_id
        assert node.repo == "AppDeploy managed source" and "AppDeploy app " in node.evidence, app_id


if __name__ == "__main__":
    test_launchers()
    print("  ok  exact accessible app launchers on Holding and hub")
    test_catalog()
    print("  ok  matching external catalog nodes without health or SSO claims")
    print("\n2/2 app launcher contract tests passed")
