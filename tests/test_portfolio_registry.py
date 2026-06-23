from core.portfolio import registry


def test_exactly_ten_businesses_with_unique_slugs():
    businesses = registry.list_businesses()
    assert len(businesses) == 10
    slugs = [b.slug for b in businesses]
    assert len(set(slugs)) == 10
    assert "n8n" in slugs


def test_get_business_found_and_missing():
    n8n = registry.get_business("n8n")
    assert n8n is not None
    assert n8n.name == "n8n Automation Agency"
    assert n8n.phase == "planning"
    assert registry.get_business("does-not-exist") is None


def test_every_business_has_thesis_and_repo():
    for b in registry.list_businesses():
        assert b.thesis.strip()
        assert b.oss_repo.startswith("https://")
