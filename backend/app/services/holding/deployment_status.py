"""DEPLOYMENT_STATUS runtime (Part A, §1-13) — authoritative deployment truth, ZERO deploy authority.

Answers: what is deployed, is it current, did it succeed, is it healthy, is it stale vs source, and is
the likely problem source/deployment/runtime. It CANNOT deploy/redeploy/restart/rollback/scale/change
variables/domains/settings — no such method exists in any adapter (§Part-A goal).

Provider is resolved from service metadata (§1), never hard-coded. The genuinely-certified provider is
LocalDeploymentProvider: source SHA from the local git repo + deployed SHA from a server-configured map
(register_deployment_source), compared via REAL git ancestry (never guessed §7). Railway/other providers
are declared with no certified adapter → BLOCKED_CAPABILITY (never a substituted provider §1). No env
var values / secrets are ever read or returned (§6/§9).
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, asdict
from enum import Enum

from app.services.holding.task_resolver import redact

_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")   # a real git object id — rejects flags / injection / refs


def _is_sha(s) -> bool:
    return isinstance(s, str) and bool(_SHA_RE.match(s))


class DeployOp(str, Enum):
    CURRENT_DEPLOYMENT = "CURRENT_DEPLOYMENT"
    DEPLOYMENT_STATUS = "DEPLOYMENT_STATUS"
    DEPLOYED_SHA = "DEPLOYED_SHA"
    SERVICE_HEALTH = "SERVICE_HEALTH"
    RECENT_DEPLOYMENTS = "RECENT_DEPLOYMENTS"
    BUILD_STATUS = "BUILD_STATUS"
    REPLICA_STATUS = "REPLICA_STATUS"


# §7 source-vs-deployed classification (real git ancestry, no branch-ancestry guessing)
MATCH = "MATCH"
DEPLOYMENT_BEHIND = "DEPLOYMENT_BEHIND"
DEPLOYMENT_AHEAD_OR_UNKNOWN = "DEPLOYMENT_AHEAD_OR_UNKNOWN"
UNCOMPARABLE = "UNCOMPARABLE"

# §8 diagnosis distinctions this capability CONTRIBUTES evidence toward (never decides alone)
DIAGNOSIS = ("SOURCE_DEFECT", "DEPLOYMENT_STALE", "DEPLOYMENT_FAILED", "RUNTIME_FAILURE",
             "TEST_FAILURE", "UNKNOWN")


class DeployDenied(Exception):
    """Raised for unknown/cross-company service, forged provider, or any mutation attempt."""


@dataclass
class DeploymentIdentity:
    holding_id: str
    company_id: str
    service_id: str
    provider: str            # RAILWAY | LOCAL | OTHER | UNAVAILABLE
    environment: str
    project_id: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# §1 server-owned service → deployment-source map (NOT task input). Empty default → real services BLOCK.
_DEPLOYMENT_SOURCES: dict[str, dict] = {}


def register_deployment_source(service_id: str, *, provider: str, deployed_sha: str = "",
                               deployment_id: str = "", status: str = "", environment: str = "production",
                               local_root: str = "") -> None:
    """Ops/config registers a service's authoritative deployment source (read-only facts only)."""
    _DEPLOYMENT_SOURCES[service_id] = {"provider": provider, "deployed_sha": deployed_sha,
                                       "deployment_id": deployment_id, "status": status,
                                       "environment": environment, "local_root": local_root}


def resolve_deployment(company_id: str, service_id: str = "", *, entities=None, sources: dict | None = None):
    """Resolve a company/service to a typed DeploymentIdentity from holding metadata (§1)."""
    if entities is None:
        from app.services.holding import registry as reg
        entities = reg.all_entities()
    ent = next((e for e in entities if getattr(e, "entity_id", None) == company_id), None)
    if ent is None:
        return None
    sid = service_id or company_id
    src = (sources if sources is not None else _DEPLOYMENT_SOURCES).get(sid)
    provider = (src or {}).get("provider", "UNAVAILABLE")
    return DeploymentIdentity(holding_id="wheellsverse", company_id=company_id, service_id=sid,
                              provider=provider, environment=(src or {}).get("environment", "production"))


def _git_is_ancestor(root: str, maybe_ancestor: str, descendant: str) -> bool:
    if not (_is_sha(maybe_ancestor) and _is_sha(descendant)):
        return False
    out = subprocess.run(["git", "-C", root, "merge-base", "--is-ancestor", maybe_ancestor, descendant],
                         capture_output=True, text=True, timeout=15)
    return out.returncode == 0


def _git_has_commit(root: str, sha: str) -> bool:
    if not _is_sha(sha):                                     # reject flags / refs / injection
        return False
    out = subprocess.run(["git", "-C", root, "cat-file", "-e", sha + "^{commit}"],
                         capture_output=True, text=True, timeout=15)
    return out.returncode == 0


def compare_shas(root: str, source_sha: str, deployed_sha: str) -> str:
    """§7: classify deployed vs source using REAL git ancestry. Unknown/non-SHA input → UNCOMPARABLE."""
    if not _is_sha(source_sha) or not _is_sha(deployed_sha):
        return UNCOMPARABLE                                 # non-hex (incl. a '-flag') is never compared
    if source_sha == deployed_sha:
        return MATCH
    try:
        if not (_git_has_commit(root, source_sha) and _git_has_commit(root, deployed_sha)):
            return UNCOMPARABLE
        if _git_is_ancestor(root, deployed_sha, source_sha):
            return DEPLOYMENT_BEHIND          # deployed is an ancestor of source → source has newer commits
        return DEPLOYMENT_AHEAD_OR_UNKNOWN
    except Exception:
        return UNCOMPARABLE


class LocalDeploymentProvider:
    """CERTIFIED read-only provider: deployed facts from the configured source, source SHA from local
    git, compared by real ancestry. No mutation method exists here."""
    name = "LOCAL"

    def health(self, src: dict) -> dict:
        return {"state": "READY"} if src and src.get("deployed_sha") else {"state": "UNAVAILABLE",
                                                                           "reason": "no deployed sha configured"}

    def read(self, ident: DeploymentIdentity, src: dict, source_root: str) -> dict:
        deployed = src.get("deployed_sha", "")
        source_sha = ""
        try:
            from app.services.holding.repo_inspect import LocalGitProvider
            if source_root:
                source_sha = LocalGitProvider(source_root).repository_status().get("commit_sha", "")
        except Exception:
            source_sha = ""
        comparison = compare_shas(source_root, source_sha, deployed) if source_root else UNCOMPARABLE
        return {"deployment_id": src.get("deployment_id", "UNAVAILABLE"),
                "deployment_status": src.get("status", "UNAVAILABLE"),
                "deployed_sha": deployed, "source_sha": source_sha or "UNAVAILABLE",
                "sha_comparison": comparison}


def make_deployment_provider(*, providers: dict | None = None, sources: dict | None = None, entities=None):
    """Return provider(args) -> redacted evidence for the composite executor. Fails closed for unknown
    company/service, unconfigured/uncertified provider, unknown/mutation operation. Never returns env
    vars/secrets (§6/§9)."""
    impls = {"LOCAL": LocalDeploymentProvider(), **(providers or {})}

    def provider(args: dict) -> dict:
        args = args or {}
        ident = resolve_deployment(args.get("company_id", ""), args.get("service_id", ""),
                                   entities=entities, sources=sources)
        if ident is None:
            raise DeployDenied("unknown company / no service")
        src = (sources if sources is not None else _DEPLOYMENT_SOURCES).get(ident.service_id)
        if src is None:
            raise DeployDenied(f"no configured deployment source for '{ident.service_id}'")
        impl = impls.get(ident.provider)
        if impl is None:
            raise DeployDenied(f"no certified read adapter for provider '{ident.provider}'")   # never substitute
        if impl.health(src).get("state") != "READY":
            raise DeployDenied("deployment provider unhealthy")
        op = args.get("operation", DeployOp.DEPLOYMENT_STATUS.value)
        try:
            DeployOp(op)
        except ValueError:
            raise DeployDenied(f"unknown/mutation operation '{op}' not permitted")   # only read ops exist
        data = impl.read(ident, src, src.get("local_root", ""))
        evidence = {"provider": ident.provider, "service_id": ident.service_id,
                    "environment": ident.environment, "company_id": ident.company_id,
                    "operation": op, "observed_at": "now",
                    **{k: v for k, v in data.items()
                       # §6/§9 whitelist — never leak env vars / tokens / raw provider blobs
                       if k in ("deployment_id", "deployment_status", "deployed_sha", "source_sha",
                                "sha_comparison", "health", "created_at", "completed_at")}}
        return redact(evidence)

    return provider


if __name__ == "__main__":
    from app.services.holding.test_deployment_status import run
    run()
