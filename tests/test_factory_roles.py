from factory import roles


def test_registry_has_core_agent_roles():
    for key in ["architect", "engineer", "reviewer", "qa", "techlead"]:
        assert key in roles.ROLES
        assert isinstance(roles.ROLES[key].system_prompt, str)
        assert roles.ROLES[key].system_prompt.strip()


def test_no_role_has_a_forbidden_tool():
    for key, role in roles.ROLES.items():
        joined = " ".join(role.allowed_tools).lower()
        for bad in roles.FORBIDDEN_TOOL_SUBSTRINGS:
            assert bad not in joined, f"role {key} allowlist contains forbidden {bad!r}"


def test_models_are_valid_tiers():
    for role in roles.ROLES.values():
        assert role.model in {"haiku", "sonnet", "opus"}


def test_estimated_cost_by_tier():
    assert roles.estimated_cost("haiku") < roles.estimated_cost("sonnet") < roles.estimated_cost("opus")
    assert roles.estimated_cost("unknown") == 0.25
