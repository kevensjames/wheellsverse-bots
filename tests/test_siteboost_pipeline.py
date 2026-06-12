"""End-to-end and unit tests for the SiteBoost pipeline.

Runs entirely in dry-run mode — no API keys required, no network calls.
Validates that the 5-stage pipeline produces consistent, well-shaped output
across version upgrades.

Run with: pytest tests/test_siteboost_pipeline.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Make the project root importable when pytest runs from any dir
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import places_scanner, email_enricher, site_generator, cold_outreach
from core import siteboost_state, siteboost_onboarding


# ── Stage 1: Places Scanner ────────────────────────────────────────────────

class TestPlacesScanner:
    def test_dry_run_produces_realistic_prospects(self):
        results = places_scanner.scan("Boston, MA", limit=10, dry_run=True)
        assert len(results) == 10
        for p in results:
            assert p.name
            assert p.phone
            assert p.country_code == "US"
            assert not p.website  # Dry-run all targetable

    def test_dry_run_writes_scan_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(places_scanner, "SCANS_DIR", tmp_path)
        places_scanner.scan("Boston, MA", limit=5, dry_run=True)
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert "_meta" in data
        assert "targetable" in data
        assert data["_meta"]["dry_run"] is True

    def test_gdpr_country_codes_are_blocked(self):
        from core.places_scanner import Prospect
        p = Prospect(place_id="x", name="Bäckerei Schmidt", category="bakery",
                     address="Berlin, Germany", phone="+49...", country_code="DE")
        ok, reason = p.is_targetable()
        assert not ok
        assert reason == "gdpr-region"

    def test_prospect_with_website_is_rejected(self):
        from core.places_scanner import Prospect
        p = Prospect(place_id="x", name="N", category="c", address="a",
                     phone="555", website="https://example.com", country_code="US")
        ok, reason = p.is_targetable()
        assert not ok
        assert reason == "has-website"

    def test_prospect_without_phone_is_rejected(self):
        from core.places_scanner import Prospect
        p = Prospect(place_id="x", name="N", category="c", address="a",
                     phone="", country_code="US")
        ok, reason = p.is_targetable()
        assert not ok
        assert reason == "no-phone"


# ── Stage 2: Email Enricher ────────────────────────────────────────────────

class TestEmailEnricher:
    def test_dry_run_enrichment_is_deterministic(self):
        """Same prospect name → same enrichment result across runs."""
        p = {"name": "Mama Lupita's Tortilleria"}
        r1 = email_enricher._dry_run_enrich(p)
        r2 = email_enricher._dry_run_enrich(p)
        assert r1 == r2

    def test_dry_run_hit_rate_is_about_50pct(self):
        """Realistic dry-run should produce ~50% hit rate across many prospects."""
        from core.places_scanner import _dry_run_fixtures
        fixtures = _dry_run_fixtures("Test, MA", n=20)
        hits = [email_enricher._dry_run_enrich({"name": p.name}) for p in fixtures]
        hit_count = sum(1 for h in hits if h)
        # Should be between 30-70% (allowing for hash-based variance on small N)
        assert 0.3 <= hit_count / 20 <= 0.7

    def test_enrich_writes_separate_phone_only_bucket(self, tmp_path):
        """Non-enriched prospects go to 'phone_only', not silently dropped."""
        scan = {
            "_meta": {"location": "Test, MA"},
            "targetable": [
                {"name": "ABC Plumbing", "phone": "555-0100", "category": "plumber",
                 "address": "1 Main St, Boston, MA"},
                {"name": "XYZ Salon", "phone": "555-0101", "category": "salon",
                 "address": "2 Main St, Boston, MA"},
            ],
        }
        scan_path = tmp_path / "test-scan.json"
        scan_path.write_text(json.dumps(scan))
        enr_path = email_enricher.enrich_scan(scan_path, dry_run=True)
        data = json.loads(enr_path.read_text())
        assert "enriched" in data
        assert "phone_only" in data
        # Every prospect should be in exactly one bucket
        total = len(data["enriched"]) + len(data["phone_only"])
        assert total == 2


# ── Stage 3: Site Generator ────────────────────────────────────────────────

class TestSiteGenerator:
    def test_template_mapping_routes_by_category(self):
        # restaurant → restaurant template
        assert "restaurant" in site_generator._template_for("restaurant").name
        # plumber → service template
        assert "service" in site_generator._template_for("plumber").name
        # pet_store → retail template
        assert "retail" in site_generator._template_for("pet_store").name
        # unknown category → service fallback
        assert "service" in site_generator._template_for("unknown_xyz").name

    def test_slugify_handles_apostrophes_and_special_chars(self):
        assert site_generator._slugify("Mama Lupita's Café & Bar") == "mama-lupita-s-caf-bar"
        assert site_generator._slugify("ABC  ---  XYZ") == "abc-xyz"

    def test_dry_run_personalize_uses_defaults(self):
        p = {"name": "Test Biz", "category": "restaurant", "review_count": 50}
        copy = site_generator._personalize_copy(p, dry_run=True)
        assert "hero_headline" in copy
        assert "hero_sub" in copy
        assert "service_cards" in copy
        assert len(copy["service_cards"]) == 3
        # No HTML smuggled in
        assert "<" not in copy["hero_headline"]


# ── Stage 4: Cold Outreach ─────────────────────────────────────────────────

class TestColdOutreach:
    def test_can_spam_footer_is_present(self):
        footer = cold_outreach._can_spam_footer("siteboost.io")
        assert "unsubscribe" in footer.lower()
        assert "siteboost.io" in footer

    def test_city_extraction_picks_right_segment(self):
        assert cold_outreach._city_from_address("100 Main St, Boston, MA") == "Boston"
        assert cold_outreach._city_from_address("123 Oak Ave, Cambridge, MA 02139") == "Cambridge"
        assert cold_outreach._city_from_address("Boston, MA") == "Boston"
        assert cold_outreach._city_from_address("solo") == "your area"

    def test_category_friendly_lookup(self):
        assert cold_outreach._category_friendly("hair_salon") == "hair salon"
        assert cold_outreach._category_friendly("plumber") == "plumber"
        # Unknown → safe fallback
        assert cold_outreach._category_friendly("zorp") == "small business"

    def test_compose_refuses_apex_wheellsverse_domain(self, tmp_path, monkeypatch):
        """Guard: never use the apex wheellsverse.com for cold outbound."""
        monkeypatch.setenv("SITEBOOST_OUTBOUND_DOMAIN", "wheellsverse.com")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"previews": []}))
        with pytest.raises(RuntimeError, match="reputation-critical"):
            cold_outreach.compose_sequences(manifest, outbound_domain="wheellsverse.com")

    def test_compose_refuses_shop_and_app_subdomains(self, tmp_path):
        """shop.wheellsverse.com (Shopify) and app.wheellsverse.com (redirect handler) are critical too."""
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"previews": []}))
        for danger in ["shop.wheellsverse.com", "app.wheellsverse.com", "www.wheellsverse.com"]:
            with pytest.raises(RuntimeError, match="reputation-critical"):
                cold_outreach.compose_sequences(manifest, outbound_domain=danger)

    def test_compose_allows_hello_subdomain(self, tmp_path, monkeypatch):
        """hello.wheellsverse.com has separate sending reputation — safe to use."""
        # Need at least one preview and matching enriched data for compose to proceed
        enriched_dir = ROOT / "data" / "launches" / "siteboost" / "scans"
        enriched_dir.mkdir(parents=True, exist_ok=True)
        # Write a tiny enriched file
        enriched = enriched_dir / "test-enriched.json"
        enriched.write_text(json.dumps({
            "_meta": {"location": "Test, MA"},
            "enriched": [],  # empty is fine for the guard test
        }))
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"previews": []}))
        # Should NOT raise — hello.wheellsverse.com is allowed
        out = cold_outreach.compose_sequences(manifest, outbound_domain="hello.wheellsverse.com")
        assert out.exists()

    def test_send_refuses_without_confirm(self, tmp_path):
        sequences = tmp_path / "seq.json"
        sequences.write_text(json.dumps({
            "_meta": {"outbound_domain": "siteboost.io"},
            "sequences": [],
        }))
        result = cold_outreach.send_sequences(sequences, confirm=False, live=True)
        assert result["status"] == "blocked"
        assert "confirm" in result["reason"]

    def test_send_refuses_without_live(self, tmp_path):
        sequences = tmp_path / "seq.json"
        sequences.write_text(json.dumps({
            "_meta": {"outbound_domain": "siteboost.io"},
            "sequences": [],
        }))
        result = cold_outreach.send_sequences(sequences, confirm=True, live=False)
        assert result["status"] == "blocked"
        assert "live" in result["reason"]


# ── State (dedupe) ──────────────────────────────────────────────────────────

class TestSiteboostState:
    def test_state_load_creates_empty_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(siteboost_state, "STATE_FILE", tmp_path / "state.json")
        s = siteboost_state._load()
        assert s["seen_place_ids"] == []
        assert s["sent_emails"] == []

    def test_filter_unsent_emails_excludes_already_sent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(siteboost_state, "STATE_FILE", tmp_path / "state.json")
        siteboost_state.mark_emails_sent(["a@example.com", "b@example.com"])
        result = siteboost_state.filter_unsent_emails(
            ["a@example.com", "C@example.com", "B@EXAMPLE.COM"]
        )
        # case-insensitive dedup, only c@ remains
        assert [e.lower() for e in result] == ["c@example.com"]

    def test_blocklist_blocks_email(self, tmp_path, monkeypatch):
        monkeypatch.setattr(siteboost_state, "STATE_FILE", tmp_path / "state.json")
        siteboost_state.block_email("Spam@Example.com")
        result = siteboost_state.filter_unsent_emails(["spam@example.com", "ok@example.com"])
        assert result == ["ok@example.com"]

    def test_blocklist_blocks_domain(self, tmp_path, monkeypatch):
        monkeypatch.setattr(siteboost_state, "STATE_FILE", tmp_path / "state.json")
        siteboost_state.block_domain("nope.com")
        result = siteboost_state.filter_unsent_emails(
            ["x@nope.com", "y@NOPE.com", "z@yes.com"]
        )
        assert result == ["z@yes.com"]

    def test_least_recently_scanned_returns_unscanned_first(self, tmp_path, monkeypatch):
        monkeypatch.setattr(siteboost_state, "STATE_FILE", tmp_path / "state.json")
        siteboost_state.record_scan("Boston, MA", "restaurant")
        pairs = siteboost_state.least_recently_scanned(
            ["Boston, MA", "Cambridge, MA"], ["restaurant", "salon"], n=4
        )
        # Cambridge unscanned, should come before Boston/restaurant
        assert ("Cambridge, MA", "restaurant") in pairs[:2]


# ── Onboarding ──────────────────────────────────────────────────────────────

class TestOnboarding:
    def test_welcome_dry_run_prints_intake_link(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(siteboost_onboarding, "CUSTOMERS_DIR", tmp_path)
        r = siteboost_onboarding.send_welcome(
            "cust_001", "test@example.com", "Maria",
            business_name="Maria's Bakery", dry_run=True,
        )
        assert r["sent"]
        out = capsys.readouterr().out
        assert "intake" in out.lower()
        assert "cust_001" in out

    def test_nudge_skips_if_intake_already_submitted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(siteboost_onboarding, "CUSTOMERS_DIR", tmp_path)
        # Pre-mark intake as submitted
        siteboost_onboarding._record_event("cust_002", "intake_submitted")
        r = siteboost_onboarding.send_nudge(
            "cust_002", "x@example.com", "X", business_name="X Co", dry_run=True,
        )
        assert not r["sent"]
        assert "intake already submitted" in r["reason"]


# ── End-to-end smoke ────────────────────────────────────────────────────────

class TestEndToEnd:
    def test_full_pipeline_dry_run(self, tmp_path, monkeypatch):
        """The whole pipeline should run without errors in dry-run mode."""
        # Redirect all outputs to tmp_path
        monkeypatch.setattr(places_scanner, "SCANS_DIR", tmp_path / "scans")

        # Stage 1
        prospects = places_scanner.scan("Boston, MA", limit=5, dry_run=True)
        assert len(prospects) > 0

        scan_files = list((tmp_path / "scans").glob("*.json"))
        assert len(scan_files) == 1

        # Stage 2
        enr_path = email_enricher.enrich_scan(scan_files[0], dry_run=True)
        assert enr_path.exists()

        # If we have at least one enriched prospect, stages 3-4 should also pass
        enr = json.loads(enr_path.read_text())
        if enr["enriched"]:
            # Stage 3 requires real template files — skip if those aren't in tmp
            template_dir = ROOT / "local_prospect" / "templates"
            if template_dir.exists():
                # Stage 3
                manifest = site_generator.generate_previews(enr_path, dry_run=True)
                assert manifest.exists()
                # Stage 4
                seq = cold_outreach.compose_sequences(manifest, sender_name="Jay")
                assert seq.exists()
                seq_data = json.loads(seq.read_text())
                # Every sequence has 3 touches with CAN-SPAM footers
                for s in seq_data["sequences"]:
                    assert len(s["touches"]) == 3
                    for t in s["touches"]:
                        assert "unsubscribe" in t["body"].lower()
