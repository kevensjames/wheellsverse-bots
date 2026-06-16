"""Outreach drafter — generates personalized cold emails via NarAI _brain.router."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any

from infra.brain.interface import BrainClient

# Scheduler-driven module: not per-request. Uses the synthetic "system"
# user_id so telemetry + memory are scoped distinctly from any human user.
_brain = BrainClient(user_id="system", mode="narai")


@dataclass
class OutreachBrief:
    recipient_name: str
    recipient_role: str
    recipient_company: str
    value_prop: str                    # what you're offering
    pain_point: str = ""               # their likely problem
    cta: str = "book a 15-min call"
    sender_name: str = "J.K. Blaze"
    hook: str = ""                     # recent company news / trigger event
    prior_context: str = ""            # any prior interaction
    template: str = "cold"             # cold | warm | reengage


_TEMPLATE_PROMPTS = {
    "cold": (
        "Write a cold outreach email. Max 80 words. Hook in the first line with "
        "a specific observation (not generic flattery). One clear value prop tied "
        "to the recipient's role. One soft CTA as a question."
    ),
    "warm": (
        "Write a warm follow-up after a prior interaction. Reference the prior "
        "context specifically. 100 words max. Clear next step."
    ),
    "reengage": (
        "Write a reengagement email to a lead who went dark. Low pressure, "
        "pattern-interrupt subject line, one-sentence CTA. 60 words max."
    ),
}


def _build_prompt(brief: OutreachBrief) -> str:
    tpl_prompt = _TEMPLATE_PROMPTS.get(brief.template, _TEMPLATE_PROMPTS["cold"])
    parts = [
        tpl_prompt,
        f"Recipient: {brief.recipient_name}, {brief.recipient_role} at {brief.recipient_company}",
        f"Value prop: {brief.value_prop}",
        f"CTA: {brief.cta}",
        f"Sender: {brief.sender_name}",
    ]
    if brief.pain_point:
        parts.append(f"Likely pain point: {brief.pain_point}")
    if brief.hook:
        parts.append(f"Hook (recent trigger): {brief.hook}")
    if brief.prior_context:
        parts.append(f"Prior context: {brief.prior_context}")
    parts.append(
        "Output format:\n"
        "Subject: <line>\n\n"
        "<email body>\n\n"
        "-- <sender>"
    )
    return "\n\n".join(parts)


async def draft_outreach(brief: OutreachBrief) -> dict[str, Any]:
    prompt = _build_prompt(brief)
    system = _brain.skills.build_system_prompt(
        base=("You are NarAI writing cold/warm outreach for J.K. Blaze. "
              "Style: direct, specific, zero fluff, one clear CTA. No AI tells."),
        skill="writer",
        memory_context=_brain.memory.recall_context(brief.recipient_company),
    )
    result = await _brain.router.call(prompt, tier="fast", system=system)
    text = result.get("content", "")

    # Parse subject line
    subject = ""
    body = text
    first_line = text.split("\n", 1)[0] if text else ""
    if first_line.lower().startswith("subject:"):
        subject = first_line.split(":", 1)[1].strip()
        body = text.split("\n", 1)[1].lstrip() if "\n" in text else ""

    return {
        "subject": subject,
        "body": body,
        "raw": text,
        "model": result.get("model", ""),
        "tokens": result.get("tokens", 0),
        "template": brief.template,
    }
