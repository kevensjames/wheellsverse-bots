import re

from factory import roles

_ALLOWED_BASH_PREFIXES = {"python", "python3", "pytest", "pip",
                          "gitleaks", "trivy", "npm", "node", "ruff", "mypy"}
_NET_PUSH = re.compile(r"git push|git remote|curl|wget|ssh|scp|\bnc\b|telnet", re.I)
_PLAIN_TOOLS = {"Read", "Edit", "Write", "Grep", "Glob"}


def test_allowlists_are_capability_safe():
    for key, role in roles.ROLES.items():
        for tool in role.allowed_tools:
            assert not tool.startswith("-"), f"{key}: flag-shaped tool {tool!r}"
            assert not _NET_PUSH.search(tool), f"{key}: network/push tool {tool!r}"
            m = re.fullmatch(r"Bash\((\S+).*\)", tool)
            if m:
                assert m.group(1) in _ALLOWED_BASH_PREFIXES, f"{key}: unscoped/odd Bash {tool!r}"
            else:
                assert tool in _PLAIN_TOOLS, f"{key}: unknown tool {tool!r}"


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
