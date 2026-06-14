"""github_scout — search GitHub for open-source projects that could make KAI
more capable, and EVALUATE each candidate for adoption.

This is a *capability scout*, NOT an auto-installer. It performs a read-only
GitHub repository search (official Search API) and ranks the results by
adoption, maintenance, and license — the things that actually decide whether a
repo is safe to integrate. It returns a structured PROPOSAL for the operator.

SECURITY (load-bearing): KAI does NOT clone, install, import, or execute any
discovered code. An agent that autonomously pulled and ran arbitrary GitHub
repos inside this daemon (which holds production secrets) would be
remote-code-execution-by-design. Adoption stays propose-then-approve: this tool
surfaces candidates + an integration assessment; a human reviews and integrates.

Keyless (GitHub Search API allows ~10 unauth req/min). Set GITHUB_TOKEN (or
GH_TOKEN) to lift the rate limit to ~30 req/min — never required.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from app.services.tools.base import ToolContext, ToolError

_SEARCH = "https://api.github.com/search/repositories"
_UA = "KAI capability scout (admin@wheellsverse.com)"

# SPDX ids we treat as safe-to-adopt for a proprietary product.
_PERMISSIVE = frozenset({
    "mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc",
    "mpl-2.0", "unlicense", "0bsd", "bsl-1.0", "zlib",
})
# Copyleft — usable but legally significant for a closed-source daemon; flag
# for review rather than silently recommending.
_COPYLEFT = frozenset({
    "gpl-2.0", "gpl-3.0", "agpl-3.0", "lgpl-2.1", "lgpl-3.0",
})


def _license_class(spdx: str | None) -> tuple[str, bool]:
    """(human label, is_blocker). No license = legal blocker: 'all rights
    reserved' by default, so KAI legally cannot reuse the code."""
    key = (spdx or "").strip().lower()
    if not key or key in ("noassertion", "other"):
        return ("none / unclear — legal blocker, cannot reuse", True)
    if key in _PERMISSIVE:
        return (f"{spdx} (permissive)", False)
    if key in _COPYLEFT:
        return (f"{spdx} (copyleft — review for proprietary use)", False)
    return (f"{spdx} (review terms)", False)


def _months_since(iso_ts: str | None) -> float | None:
    """Whole-ish months between an ISO8601 timestamp and now (UTC). None if
    unparseable. Used for staleness — coarse on purpose."""
    if not iso_ts:
        return None
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - ts
        return delta.days / 30.4
    except Exception:
        return None


def _assess(repo: dict[str, Any]) -> dict[str, Any]:
    """Turn a raw GitHub repo record into an adoption assessment: license,
    maintenance, adoption, risk flags, and a coarse recommendation."""
    stars = int(repo.get("stargazers_count") or 0)
    archived = bool(repo.get("archived"))
    license_obj = repo.get("license") or {}
    spdx = license_obj.get("spdx_id") if isinstance(license_obj, dict) else None
    license_label, license_blocker = _license_class(spdx)
    age = _months_since(repo.get("pushed_at"))
    stale = age is not None and age > 18

    risk: list[str] = []
    if license_blocker:
        risk.append("no usable license (legal blocker)")
    if archived:
        risk.append("archived (unmaintained)")
    if stale:
        risk.append(f"stale (~{int(age)}mo since last push)")
    if "copyleft" in license_label:
        risk.append("copyleft license — review for a closed-source product")
    if stars < 100:
        risk.append("low adoption (<100 stars) — vet carefully")

    if license_blocker or archived:
        recommendation = "avoid"
    elif stale or stars < 100 or "copyleft" in license_label:
        recommendation = "caution"
    else:
        recommendation = "evaluate"

    return {
        "license": license_label,
        "maintained": (age is not None and age <= 12 and not archived),
        "months_since_push": round(age, 1) if age is not None else None,
        "stars": stars,
        "risk_flags": risk,
        "recommendation": recommendation,
    }


class GithubScoutTool:
    name = "github_scout"
    description = (
        "Search GitHub for open-source projects that could extend KAI's "
        "capabilities (e.g. agent frameworks, memory, planning, tool-use, "
        "evals) and EVALUATE each for adoption — adoption (stars), maintenance "
        "(archived/stale), and license (permissive vs copyleft vs none). "
        "Returns ranked candidates with an integration assessment and a "
        "recommendation (evaluate/caution/avoid). DISCOVERY ONLY: this does "
        "NOT clone, install, or run any code — surface candidates for the "
        "operator to review and integrate via an approved, audited plan."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "What capability to search for, e.g. 'autonomous agent "
                    "framework', 'long-term memory for LLM agents', "
                    "'LLM tool calling orchestration'."
                ),
            },
            "language": {
                "type": "string",
                "description": "Optional language filter, e.g. 'python'.",
            },
            "min_stars": {
                "type": "integer",
                "description": "Minimum stars to include. Default 50.",
            },
            "max_results": {
                "type": "integer",
                "description": "Default 6, max 15.",
            },
        },
        "required": ["query"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        query = (kwargs.get("query") or "").strip()
        if not query:
            raise ToolError("query is required")
        n = max(1, min(int(kwargs.get("max_results") or 6), 15))
        min_stars = max(0, int(kwargs.get("min_stars") if kwargs.get("min_stars") is not None else 50))

        # Build the GitHub search qualifier string. Qualifiers live inside `q`.
        q = query
        language = (kwargs.get("language") or "").strip()
        if language:
            q += f" language:{language}"
        if min_stars > 0:
            q += f" stars:>={min_stars}"
        params = {"q": q, "sort": "stars", "order": "desc", "per_page": n}
        url = f"{_SEARCH}?{urllib.parse.urlencode(params)}"

        headers = {
            "User-Agent": _UA,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
        except Exception as e:
            raise ToolError(f"GitHub search failed: {e}")

        items = (data.get("items") or [])[:n]
        results: list[dict[str, Any]] = []
        for repo in items:
            assessment = _assess(repo)
            results.append({
                "repo": repo.get("full_name") or "",
                "description": (repo.get("description") or "").strip(),
                "url": repo.get("html_url") or "",
                "language": repo.get("language") or "",
                "topics": (repo.get("topics") or [])[:8],
                "last_push": repo.get("pushed_at") or "",
                **assessment,
            })

        # Rank: recommendation tier first (evaluate > caution > avoid),
        # then stars. Keeps blockers from topping the list just because
        # they're popular.
        tier = {"evaluate": 0, "caution": 1, "avoid": 2}
        results.sort(key=lambda r: (tier.get(r["recommendation"], 3), -r["stars"]))

        return {
            "query": q,
            "count": len(results),
            "results": results,
            "note": (
                "DISCOVERY ONLY — KAI does not clone, install, or run any of "
                "these repos. Each candidate is a PROPOSAL: the operator "
                "reviews license/risk/fit and integrates via an approved, "
                "audited plan. Treat unfamiliar code as untrusted until "
                "reviewed."
                if results else
                "No repositories matched — try broader terms or lower min_stars."
            ),
        }
