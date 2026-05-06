"""CI guard: every tool in the default registry must be reviewable.

Phase B (audit Critical Issue #1) — replaced ``NARAI_POLICY.allowed_tools=None``
with an explicit allowlist. The "every new capability is a reviewable diff"
property only holds if a CI test fails the build whenever a tool gets
registered into the default registry without being added to NarAI's
allowlist (or whose declared capabilities exceed NarAI's allowed set).

This test does NOT enforce that every tool MUST be allowed by NarAI —
private/per-request registries are legitimate. It enforces the rule for
the **default** registry, which is the process-wide singleton every
``BrainClient(mode="narai")`` reads.
"""
from __future__ import annotations

from infra.brain.policy import NARAI_POLICY
from infra.brain.tools import default_registry
from infra.brain.tools.builtin import register_demo_tools


def test_every_default_registry_tool_has_a_name_in_narai_allowlist():
    """Hard guard: every tool in the default registry must be on
    NARAI_POLICY.allowed_tools.

    If you intentionally add a new tool to the default registry, also
    add its name to ``NARAI_POLICY.allowed_tools`` in
    ``infra/brain/policy.py`` and (separately) declare its capabilities
    on the :class:`Tool` instance. That two-line edit is the audit
    trail for granting NarAI a new capability.
    """
    register_demo_tools()  # idempotent, ensures the canonical demo state
    reg = default_registry()
    allowed = set(NARAI_POLICY.allowed_tools or ())

    leaked = [t.name for t in reg.all() if t.name not in allowed]
    assert not leaked, (
        f"The following tools are in the default registry but NOT in "
        f"NARAI_POLICY.allowed_tools: {leaked}\n\n"
        f"To allow them under NarAI, edit infra/brain/policy.py and append "
        f"each name to the NARAI_POLICY.allowed_tools tuple. This is the "
        f"reviewable diff that closes audit Critical Issue #1."
    )


def test_every_default_registry_tool_capability_within_narai_set():
    """Hard guard: every tool in the default registry must declare
    capabilities that are a subset of ``NARAI_POLICY.allowed_capabilities``
    (when the tool declares any at all).

    Tools that don't declare capabilities are exempt — that's the opt-in
    contract of the capability gate. But once a tool DOES declare
    capabilities, those declared capabilities must be allowed.

    If a future tool needs ``shell`` or ``mutating``, the deliberate
    edit lives in ``infra/brain/policy.py`` (broaden the policy) or
    in the tool definition (declare a different capability set). Either
    way, the change is reviewable in version control.
    """
    register_demo_tools()
    reg = default_registry()
    allowed = NARAI_POLICY.allowed_capabilities or frozenset()

    offenders: list[tuple[str, set[str]]] = []
    for tool in reg.all():
        if not tool.capabilities:
            continue  # opt-out — tool didn't declare any capabilities
        if not tool.capabilities <= allowed:
            offenders.append((tool.name, set(tool.capabilities) - allowed))

    assert not offenders, (
        f"The following tools declare capabilities outside "
        f"NARAI_POLICY.allowed_capabilities (={sorted(allowed)}): "
        f"{offenders}\n\n"
        f"Either narrow the tool's declared capabilities, or broaden "
        f"NARAI_POLICY.allowed_capabilities in infra/brain/policy.py."
    )


def test_demo_web_search_passes_both_guards():
    """Smoke test: the bundled demo tool should pass both governance
    rules out of the box. If this fails, the canonical example is broken
    and the rest of the guard tests can't be trusted."""
    register_demo_tools()
    reg = default_registry()
    web_search = reg.get("web_search")
    assert "web_search" in (NARAI_POLICY.allowed_tools or ())
    assert web_search.capabilities <= (NARAI_POLICY.allowed_capabilities or frozenset())
    assert web_search.capabilities, (
        "Demo web_search must declare its capabilities so the gate exercises "
        "the realistic path."
    )
