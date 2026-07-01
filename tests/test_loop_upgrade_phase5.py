"""Phase 5 — the 'works perfectly on loops' proof: every one of the 10 businesses
runs its full 9-step loop end to end. Green acquisition steps execute (real, per-
business artifacts incl. its own build step); the 3 operational steps queue (gated)."""
from core.portfolio import adapters, loops, registry, seed, state

_OPERATIONAL = {"run_outreach_campaign", "publish_landing_page", "deploy_demo_instance"}


def test_all_10_businesses_run_their_full_loop(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)  # dry-run, no real calls
    seed.seed_all_loops()

    for b in registry.list_businesses():
        r = loops.run_business_loop(b.slug, adapters.adapter_for, adapters.ctx_for)
        assert r["steps_total"] == 9, b.slug
        # 6 green steps executed, 3 operational steps queued (gated)
        assert len(r["completed"]) == 6, (b.slug, r["completed"])
        assert set(r["pending"]) == _OPERATIONAL, (b.slug, r["pending"])
        # the business's OWN build step ran (proves the no-op gap is closed for all 10)
        assert b.build_step in r["completed"], (b.slug, b.build_step)
        # every green step reports "executed" in the matrix (real work, not skipped)
        assert all(v == "executed" for k, v in r["matrix"].items() if k not in _OPERATIONAL), (b.slug, r["matrix"])
