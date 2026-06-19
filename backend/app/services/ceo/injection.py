from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def ceo_preamble() -> str:
    """The company/CEO context block for the system prompt, or "" when the
    feature is off / no company goal is set / on any error."""
    try:
        from app.services.governance import is_scope_enabled
        if not is_scope_enabled("ceo"):
            return ""
        from app.services.ceo import store
        company = store.get_company()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("ceo.injection: skipped (%s)", e)
        return ""
    if not company or not (company.get("goal") or "").strip():
        return ""
    return (
        "You operate as the autonomous CEO of WheellsVerse. Company north-star: "
        f"{company['goal']}. When the operator asks about strategy, priorities, "
        "or 'the company', answer from this goal and the CEO board (ceo_query tool)."
    )
