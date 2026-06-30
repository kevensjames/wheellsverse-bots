from core.portfolio import registry, seed


def test_all_ten_businesses_fully_defined():
    bs = registry.list_businesses()
    assert len(bs) == 10
    for b in bs:
        # every business now has a real go-to-market definition, not a stub
        assert b.offer and b.price and b.icp and b.lead_niche and b.lead_geo
        assert b.outreach_hook and b.build_step
        assert b.phase == "defined"


def test_build_steps_are_unique_per_business():
    steps = [b.build_step for b in registry.list_businesses()]
    assert len(set(steps)) == len(steps)  # each business has its own pack verb


def test_seed_all_loops_writes_ten(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    paths = seed.seed_all_loops()
    assert len(paths) == 10
    import json
    for p in paths:
        loop = json.loads(p.read_text())
        assert loop["build_step"] in {b.build_step for b in registry.list_businesses()}
        assert loop["steps"][1]["verb"] == loop["build_step"]  # business-specific step wired in
