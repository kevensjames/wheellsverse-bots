"""Immutable plugin allow-list and composition attestation.

The previous phase shipped a DENY-list: named plugins were disabled and asserted off.
That fails open. Anything upstream adds -- a new tool, a new provider, a renamed
package -- is simply absent from the deny-list and loads silently. It also failed in a
subtler way: the list said `tool-web`, `web-fetch-http` and `web-search-deepseek` were
off and called that "no network egress", while `tool-bash` sat mounted and reached the
network anyway.

So the model is inverted here. This file states the COMPLETE set of plugins permitted to
load. Anything not on it is a startup failure. A plugin that appears because upstream
added it, because a patch was mis-ordered, or because someone dropped a file into the
profile does not get the benefit of the doubt.

This is defence in depth, NOT the boundary. The boundary is the kernel jail
(worker-jail.sbpl + jail.py): network denied except one endpoint, writes confined to a
separate filesystem, desktop binaries unexecutable. The allow-list catches a composition
that is wrong; the jail catches everything the composition failed to.

Generated from `dsh --dump-config` at pinned harness commit
c389f96bf3a9b6807cb71ed6bdad5849be0df6d8. Regenerate deliberately on upgrade, by
reviewing the diff -- never by pasting whatever the new version happens to load.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

#: Every plugin permitted to be ENABLED, as (id, package). Both are checked: an id
#: keeping its name while its package changes underneath is exactly the substitution
#: this is meant to catch.
ALLOWED_ENABLED: frozenset[tuple[str, str]] = frozenset((
    ("acp", "@deepseek-ai/dsh-acp"),
    ("acp-app-startup", "@deepseek-ai/dsh-acp-app"),
    ("agent", "@deepseek-ai/dsh-agent"),
    ("agent-default-model", "@deepseek-ai/dsh-agent-default-model"),
    ("agent-instructions", "@deepseek-ai/dsh-agent-instructions"),
    ("agent-loop", "@deepseek-ai/dsh-agent-loop"),
    ("approval", "@deepseek-ai/dsh-user-approval"),
    ("attachment-local", "@deepseek-ai/dsh-attachment-local"),
    ("bash-sandbox", "@deepseek-ai/dsh-bash-sandbox"),
    ("command-compact", "@deepseek-ai/dsh-command-compact"),
    ("command-feedback", "@deepseek-ai/dsh-command-feedback"),
    ("command-goal", "@deepseek-ai/dsh-command-goal"),
    ("commands", "@deepseek-ai/dsh-commands"),
    ("compaction-basic", "@deepseek-ai/dsh-compaction-basic"),
    ("credentials", "@deepseek-ai/dsh-credentials-local"),
    ("deepseek-llm-api-extensions", "@deepseek-ai/dsh-deepseek-llm-api-extensions"),
    ("fs-observation-policy", "@deepseek-ai/dsh-fs-observation-policy"),
    ("fs-sandbox", "@deepseek-ai/dsh-fs-sandbox"),
    ("goal", "@deepseek-ai/dsh-goal"),
    ("goal-round-driver", "@deepseek-ai/dsh-goal-round-driver"),
    ("jobs", "@deepseek-ai/dsh-jobs-local"),
    ("llm", "@deepseek-ai/dsh-llm"),
    ("llm-pi-ai", "@deepseek-ai/dsh-llm-pi-ai"),
    ("llm-retry", "@deepseek-ai/dsh-llm-retry"),
    ("permission", "@deepseek-ai/dsh-permission-presets"),
    ("plan-mode", "@deepseek-ai/dsh-plan-mode"),
    ("plugin-package-inventory-deepseek", "@deepseek-ai/dsh-plugin-package-inventory-deepseek"),
    ("repeat-tool-reminder", "@deepseek-ai/dsh-repeat-tool-reminder"),
    ("sandbox", "@deepseek-ai/dsh-sandbox-local"),
    ("sandbox-policy", "@deepseek-ai/dsh-sandbox-policy"),
    ("session", "@deepseek-ai/dsh-session"),
    ("session-checkpoint-policy", "@deepseek-ai/dsh-session-checkpoint-policy"),
    ("session-log-deepseek", "@deepseek-ai/dsh-session-log-deepseek"),
    ("session-persistence-jsonl", "@deepseek-ai/dsh-session-persistence-jsonl"),
    ("session-projection", "@deepseek-ai/dsh-session-projection"),
    ("session-projection-cache", "@deepseek-ai/dsh-session-projection-cache"),
    ("session-query-sqlite", "@deepseek-ai/dsh-session-query-sqlite"),
    ("session-telemetry-otel", "@deepseek-ai/dsh-session-telemetry-otel"),
    ("session-title", "@deepseek-ai/dsh-session-title"),
    ("shell-env", "@deepseek-ai/dsh-shell-env"),
    ("skill", "@deepseek-ai/dsh-skill"),
    ("spill-local", "@deepseek-ai/dsh-spill-local"),
    ("spill-policy", "@deepseek-ai/dsh-spill-policy"),
    ("storage", "@deepseek-ai/dsh-storage"),
    ("storage-domain", "@deepseek-ai/dsh-storage-domain"),
    ("storage-json", "@deepseek-ai/dsh-storage-json"),
    ("subagent", "@deepseek-ai/dsh-subagent"),
    ("subprocess", "@deepseek-ai/dsh-subprocess-local"),
    ("system-prompt", "@deepseek-ai/dsh-system-prompt"),
    ("timeout-policy", "@deepseek-ai/dsh-tool-call-timeout-policy"),
    ("timer", "@deepseek-ai/cordis-plugin-timer"),
    ("token-meter", "@deepseek-ai/dsh-token-meter"),
    ("tool-fs", "@deepseek-ai/dsh-tool-fs"),
    ("tool-fs-search", "@deepseek-ai/dsh-tool-fs-search"),
    ("tool-goal", "@deepseek-ai/dsh-tool-goal"),
    ("tool-result-pruner", "@deepseek-ai/dsh-compaction-tool-result-pruner"),
    ("tool-todo", "@deepseek-ai/dsh-tool-todo"),
    ("tools", "@deepseek-ai/dsh-tools"),
    ("typert", "@deepseek-ai/dsh-typert-registry"),
    ("typert-gateway", "@deepseek-ai/dsh-api-gateway"),
    ("typert-loader", "@deepseek-ai/dsh-typert-loader"),
    ("user-questions", "@deepseek-ai/dsh-user-questions"),
    ("web", "@deepseek-ai/dsh-web"),
))

#: Plugins whose ABSENCE is itself a failure. Losing one of these silently removes a
#: control rather than adding a capability, which is the harder failure to notice:
#: without `approval` there is no permission channel to KAI at all, and without
#: `sandbox-policy` / `fs-sandbox` the file policy is whatever upstream defaults to.
REQUIRED_ENABLED: frozenset[str] = frozenset({
    "approval",         # routes every consequential call to KAI over ACP
    "permission",       # the KAI preset table; its absence restores upstream's
    "sandbox-policy",   # the file-policy mode a mission was attested with
    "fs-sandbox",       # workspace confinement for the fs tools
    "acp",              # the seam itself
    "llm-pi-ai",        # the local route under LOCAL_ONLY
})

#: Plugins that must be present but DISABLED. Listing them explicitly means an upstream
#: rename shows up as "missing" rather than as a silently absent denial.
REQUIRED_DISABLED: frozenset[str] = frozenset({
    "tool-bash", "tool-pwsh", "pwsh-sandbox",
    "tool-web", "web-fetch-http", "web-search-deepseek",
    "tool-ralph", "tool-subagent", "tool-subagent-fork", "tool-subagent-control",
    "tool-subagent-list-agents", "subagent-spawn-in-process", "subagent-fork-in-process",
    "tool-workflow", "workflow-worker-thread", "tool-jobs",
    "skill-filesystem", "tool-skill",
    "llm-deepseek", "settings",
})


@dataclass
class CompositionReport:
    ok: bool = True
    digest: str = ""
    enabled: list[tuple[str, str]] = field(default_factory=list)
    disabled: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{len(self.enabled)} enabled / {len(self.disabled)} disabled, "
                f"digest {self.digest[:16]}")


def parse_entries(dump: str) -> list[tuple[str, str, bool]]:
    """Parse `dsh --dump-config` into the EFFECTIVE (id, package, disabled) list.

    An id appears once per layer that touched it and the LAST occurrence wins -- the
    same rule the loader applies. So repetition in the dump is normal and is NOT a
    violation; `redefined_ids()` reports the case that actually matters.
    """
    blocks: dict[str, list[str]] = {}
    order: list[str] = []
    cur: str | None = None
    for line in dump.splitlines():
        m = re.match(r"^- id: (\S+)\s*$", line)
        if m:
            cur = m.group(1)
            blocks[cur] = [line]
            if cur not in order:
                order.append(cur)
        elif cur is not None:
            blocks[cur].append(line)
    out = []
    for pid in order:
        text = "\n".join(blocks[pid])
        name = re.search(r"name: '([^']+)'", text)
        out.append((pid, name.group(1) if name else "<unnamed>", "disabled: true" in text))
    return out


def redefined_ids(dump: str) -> dict[str, set[str]]:
    """Ids whose PACKAGE differs between layers.

    Layered config legitimately re-states an id to override its config, so counting
    repetitions would reject every valid composition. What is never legitimate is an id
    resolving to one package in one layer and a different package in another: that is a
    permitted id being used as a slot for a different implementation, which an id-only
    allow-list would not catch.
    """
    per_id: dict[str, set[str]] = {}
    cur: str | None = None
    for line in dump.splitlines():
        m = re.match(r"^- id: (\S+)\s*$", line)
        if m:
            cur = m.group(1)
            per_id.setdefault(cur, set())
            continue
        if cur is not None:
            nm = re.match(r"^\s+name: '([^']+)'\s*$", line)
            if nm:
                per_id[cur].add(nm.group(1))
    return {pid: names for pid, names in per_id.items() if len(names) > 1}


def composition_digest(entries: list[tuple[str, str, bool]]) -> str:
    """Stable digest of the effective composition.

    Covers id, package and enabled-state only. Config VALUES are deliberately excluded:
    they carry per-mission paths (volume mount, workspace) that change every run, so
    including them would make the digest unstable and therefore useless as a tripwire.
    Config is attested separately, by value, in attest.py.
    """
    canonical = json.dumps(sorted((pid, name, disabled) for pid, name, disabled in entries),
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_composition(dump: str) -> CompositionReport:
    """Fail closed on anything not explicitly permitted."""
    rep = CompositionReport()
    entries = parse_entries(dump)
    rep.digest = composition_digest(entries)

    for pid, names in sorted(redefined_ids(dump).items()):
        rep.violations.append(
            f"plugin id {pid!r} is redefined across layers to different packages "
            f"{sorted(names)} - a permitted id used as a slot for another implementation")

    for pid, name, disabled in entries:
        if disabled:
            rep.disabled.append(pid)
            continue
        rep.enabled.append((pid, name))
        if (pid, name) not in ALLOWED_ENABLED:
            known_id = any(pid == a for a, _ in ALLOWED_ENABLED)
            if known_id:
                expected = [n for i, n in ALLOWED_ENABLED if i == pid]
                rep.violations.append(
                    f"plugin {pid!r} is enabled with package {name!r}, expected {expected[0]!r} "
                    "- package substituted under a permitted id")
            else:
                rep.violations.append(
                    f"UNKNOWN plugin {pid!r} ({name}) is enabled and is not on the allow-list")

    present = {pid for pid, _n, _d in entries}
    for pid in sorted(REQUIRED_ENABLED):
        if pid not in present:
            rep.violations.append(f"required plugin {pid!r} is absent from the composition")
        elif pid in rep.disabled:
            rep.violations.append(f"required plugin {pid!r} is present but DISABLED")

    for pid in sorted(REQUIRED_DISABLED):
        if pid not in present:
            rep.violations.append(
                f"plugin {pid!r} expected present-but-disabled is ABSENT - upstream rename? "
                "Its denial can no longer be asserted.")
        elif pid not in rep.disabled:
            rep.violations.append(f"plugin {pid!r} MUST be disabled but is enabled")

    rep.ok = not rep.violations
    return rep
