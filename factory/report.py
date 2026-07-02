"""Render a cycle record into a human morning report (markdown)."""
from __future__ import annotations

from pathlib import Path

from factory import paths


def render_report(cycle: dict) -> str:
    pr = cycle.get("pr_url") or "no PR"
    lines = [
        f"# Factory report — {cycle.get('slug')} ({cycle.get('at', '')})",
        "",
        f"- **Status:** {cycle.get('status')}",
        f"- **Task:** {cycle.get('task_id')}",
        f"- **PR:** {pr}",
        f"- **Cost:** ${float(cycle.get('cost_usd', 0.0)):.2f}",
        "",
        "## Stages",
    ]
    for s in cycle.get("stages", []):
        lines.append(f"- `{s.get('verb')}` → {s.get('status')} ({s.get('detail')})")
    return "\n".join(lines) + "\n"


def write_report(slug: str, cycle: dict, *, date: str) -> Path:
    target = paths.project_dir(slug) / "reports" / f"{date}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_report(cycle), encoding="utf-8")
    return target
