from core.portfolio import adapters, loop_context, registry
from core.portfolio.actions import Action, ActionClass
from core.portfolio.adapters.build_pack import BuildPackAdapter


class _Step:
    def __init__(self, verb):
        self.verb = verb


def test_business_ctx_is_real_per_business():
    c = loop_context.business_ctx("coolify")
    assert c["known"] and c["offer"]
    assert c["lead_niche"] == "web design and development agencies"
    assert c["build_step"] == "build_migration_blueprint" and c["has_kit"]


def test_kit_section_extracts_service_pack_for_all_10():
    for b in registry.list_businesses():
        sec = loop_context.kit_section(b.slug, "Service Pack")
        assert len(sec) > 200, f"{b.slug}: Service Pack section missing/short"


def test_all_build_verbs_route_to_buildpack_no_more_noop():
    for b in registry.list_businesses():
        a = adapters.adapter_for(_Step(b.build_step))
        assert isinstance(a, BuildPackAdapter), (b.slug, b.build_step)


def test_buildpack_writes_business_specific_artifact_from_kit(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    a = BuildPackAdapter()  # no generate -> proves content came from the kit, not generation
    for slug in ("n8n", "coolify", "penpot", "medusa", "appflowy"):
        act = Action(verb="build_x", agent="", action_class=ActionClass.GREEN,
                     preconditions=[], business=slug, payload={})
        r = a.run(act)
        assert r["source"] == "gtm_kit" and r["bytes"] > 200, slug


def test_non_build_verbs_unaffected():
    assert not isinstance(adapters.adapter_for(_Step("research_niche")), BuildPackAdapter)
    assert not isinstance(adapters.adapter_for(_Step("generate_lead_list")), BuildPackAdapter)
