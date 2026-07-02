from core.portfolio import org


def test_full_org_chart_present():
    assert len(org.list_supervisors()) == 10
    assert len(org.list_agents()) >= 19


def test_every_agent_is_complete_and_reports_to_a_real_supervisor():
    sup_slugs = {s.slug for s in org.list_supervisors()}
    for a in org.list_agents():
        assert a.reports_to in sup_slugs, a.slug
        assert a.role.strip() and a.prompt.strip()


def test_supervisor_managed_agents_all_exist():
    agent_slugs = {a.slug for a in org.list_agents()}
    for s in org.list_supervisors():
        for managed in s.manages:
            assert managed in agent_slugs, (s.slug, managed)


def test_agent_types_are_real_subagent_types():
    known = {"general-purpose", "architect", "executor", "code-reviewer", "debugger",
             "security-reviewer", "test-engineer", "designer", "writer", "planner", "analyst"}
    for a in org.list_agents():
        assert a.agent_type in known, (a.slug, a.agent_type)


def test_agents_for_supervisor_resolves():
    eng = org.agents_for("startup_factory")
    assert any(a.slug == "architect" for a in eng)
    assert all(a.reports_to == "startup_factory" for a in eng)
