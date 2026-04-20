"""Sales/CRM — lead scoring, outreach drafting, pipeline tracking."""
from narai.core.sales.lead import score_lead, Lead
from narai.core.sales.outreach import draft_outreach, OutreachBrief
from narai.core.sales.pipeline import Pipeline, Deal, DealStage

__all__ = [
    "score_lead", "Lead",
    "draft_outreach", "OutreachBrief",
    "Pipeline", "Deal", "DealStage",
]
