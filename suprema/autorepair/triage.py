"""LLM-assisted triage of review-tier findings.

Calls the Anthropic API with each finding plus surrounding code context;
gets back a structured verdict (real / false-positive / uncertain) plus
confidence and reasoning. Findings classified as "real" with confidence
≥ promote_threshold can be auto-applied if the pattern also has a fixer.

Why this exists: review-tier scanners (frontend_backend_diff,
hardcoded_localhost, etc.) generate a lot of findings the operator has
to triage by hand. Even a 60% accurate LLM triage cuts the review
workload by half.

Env vars:
    ANTHROPIC_API_KEY      required
    SUPREMA_TRIAGE_MODEL   override model (default: claude-haiku-4-5)
    SUPREMA_TRIAGE_BUDGET  hard cap on total tokens per cycle (default: 50000)

Usage:
    suprema-autorepair fix --llm-triage --commit
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("suprema.autorepair")

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_VERSION = "2023-06-01"

SYSTEM_PROMPT = """You are a code-bug triage agent for the SUPREMA workspace
autorepair system. You receive a *finding* from a static scanner and must
decide whether it is a real bug worth fixing, a false positive from a
heuristic that fired incorrectly, or genuinely uncertain.

Respond with a single JSON object — no prose, no markdown fences:

{
  "verdict": "real_bug" | "false_positive" | "uncertain",
  "confidence": 0.0 to 1.0,
  "reasoning": "<one sentence, ≤200 chars>",
  "suggested_fix": "<optional, one-line fix description or empty string>"
}

Common false-positive shapes:
  - Frontend URL with template literals: api(`/foo/${id}`) — scanner regex
    truncates at the backtick, producing a fake "missing endpoint"
  - localhost references inside <!-- comments --> or behind dev guards
  - Routes mounted via include_router() that the regex scanner misses

Common real-bug shapes:
  - api(url, {method:'POST'}) when helper signature is api(path, method, body)
  - hardcoded http://localhost:N/path in a file the production build serves
  - missing static asset (/sw.js, /manifest.json) that the page references"""


@dataclass
class TriageResult:
    verdict: str          # "real_bug" | "false_positive" | "uncertain"
    confidence: float     # 0.0 - 1.0
    reasoning: str
    suggested_fix: str = ""
    tokens_used: int = 0
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "confidence": round(self.confidence, 3),
            "reasoning": self.reasoning,
            "suggested_fix": self.suggested_fix,
            "tokens_used": self.tokens_used,
            "error": self.error,
        }


def _load_api_key() -> str:
    """Resolve ANTHROPIC_API_KEY in this order:

      1. process env (set by the operator or daemon)
      2. wheellsverse-bots/.env
      3. wheellsverse_bots.OLD_PRE_MIGRATION/.env  (legacy)
      4. narai/.env
      5. ~/.anthropic/api_key

    Returns "" if none found — caller will gracefully degrade triage."""
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key

    candidate_envs = [
        Path("/Volumes/Wheellsverse/wheellsverse-bots/.env"),
        Path("/Volumes/Wheellsverse/wheellsverse_bots.OLD_PRE_MIGRATION/.env"),
        Path("/Volumes/Wheellsverse/narai/.env"),
    ]
    for env_file in candidate_envs:
        if not env_file.is_file():
            continue
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s.startswith("ANTHROPIC_API_KEY="):
                    val = s.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val
        except Exception:
            continue

    # ~/.anthropic/api_key — standard Anthropic CLI location
    home_key = Path.home() / ".anthropic" / "api_key"
    if home_key.is_file():
        try:
            val = home_key.read_text(encoding="utf-8").strip()
            if val:
                return val
        except Exception:
            pass

    return ""


def _read_context(project: Path, location: str, context_lines: int = 10) -> str:
    """Pull ±N lines around `location` (e.g. 'dashboard/index.html:15750')."""
    try:
        rel, line_str = location.rsplit(":", 1)
        line_no = int(line_str)
    except Exception:
        return ""
    f = project / rel
    if not f.is_file():
        return ""
    try:
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    lo = max(0, line_no - 1 - context_lines)
    hi = min(len(lines), line_no - 1 + context_lines + 1)
    snippet = []
    for i in range(lo, hi):
        marker = " → " if i == line_no - 1 else "   "
        snippet.append(f"{marker}{i + 1:5}  {lines[i]}")
    return "\n".join(snippet)


def _call_claude(payload: dict, api_key: str, timeout: float = 20.0) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _extract_json(text: str) -> dict | None:
    """Tolerate a Claude reply that has prose + json, fenced or not."""
    text = text.strip()
    # Strip ``` fences
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    # Find first { ... } that parses
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def triage_finding(
    finding: dict,
    project: Path,
    pattern_meta: dict,
    api_key: str,
    model: str = DEFAULT_MODEL,
) -> TriageResult:
    """Single-finding triage. Synchronous."""
    context = _read_context(project, finding.get("location", ""), context_lines=8)
    user_msg = (
        f"Pattern: {finding.get('pattern')}\n"
        f"Title: {pattern_meta.get('title', '(no title)')}\n"
        f"Severity: {finding.get('severity', 'medium')}\n"
        f"Location: {finding.get('location')}\n"
        f"Evidence: {finding.get('evidence', '')}\n\n"
        f"Code context:\n{context if context else '(no context available)'}\n\n"
        f"Respond with the JSON verdict object."
    )

    try:
        resp = _call_claude({
            "model": model,
            "max_tokens": 400,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_msg}],
        }, api_key)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        return TriageResult("uncertain", 0.0, "", "", 0, f"HTTP {e.code}: {body}")
    except Exception as e:
        return TriageResult("uncertain", 0.0, "", "", 0, f"call failed: {e}")

    # Anthropic Messages API returns content as a list of blocks
    text = ""
    for block in resp.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")
    parsed = _extract_json(text) or {}
    tokens = resp.get("usage", {})
    total_tokens = int(tokens.get("input_tokens", 0)) + int(tokens.get("output_tokens", 0))

    verdict = str(parsed.get("verdict", "uncertain")).strip()
    if verdict not in ("real_bug", "false_positive", "uncertain"):
        verdict = "uncertain"

    return TriageResult(
        verdict=verdict,
        confidence=float(parsed.get("confidence", 0.0)),
        reasoning=str(parsed.get("reasoning", ""))[:300],
        suggested_fix=str(parsed.get("suggested_fix", ""))[:300],
        tokens_used=total_tokens,
    )


def triage_batch(
    findings: list[dict],
    project_path_fn,
    catalog: dict,
    *,
    max_workers: int = 5,
    token_budget: int = 50000,
    model: str | None = None,
) -> dict[int, TriageResult]:
    """Triage a list of findings concurrently. Returns {finding_index: TriageResult}.

    Stops sending requests once the cumulative token usage exceeds
    token_budget — the rest are returned as uncertain/error."""
    api_key = _load_api_key()
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — triage skipped, all findings stay as-is")
        return {}

    model = model or os.getenv("SUPREMA_TRIAGE_MODEL", DEFAULT_MODEL)
    budget = int(os.getenv("SUPREMA_TRIAGE_BUDGET", str(token_budget)))

    results: dict[int, TriageResult] = {}
    tokens_so_far = 0

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {}
        for i, f in enumerate(findings):
            if tokens_so_far >= budget:
                results[i] = TriageResult("uncertain", 0.0,
                                          "token budget exhausted before triage", "")
                continue
            meta = catalog.get(f.get("pattern"), {})
            futures[ex.submit(
                triage_finding,
                f, project_path_fn(f.get("project", "")), meta, api_key, model,
            )] = i

        for fut in as_completed(futures):
            i = futures[fut]
            try:
                tr = fut.result()
            except Exception as e:
                tr = TriageResult("uncertain", 0.0, "", "", 0, f"exception: {e}")
            results[i] = tr
            tokens_so_far += tr.tokens_used

    log.info(f"LLM triage: {len(results)} findings, "
             f"{tokens_so_far} tokens, "
             f"{sum(1 for r in results.values() if r.verdict == 'real_bug')} real, "
             f"{sum(1 for r in results.values() if r.verdict == 'false_positive')} fp, "
             f"{sum(1 for r in results.values() if r.verdict == 'uncertain')} uncertain")
    return results
