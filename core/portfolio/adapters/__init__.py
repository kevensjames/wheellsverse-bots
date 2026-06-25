"""W-MOS adapters — each wraps one subsystem behind the engine's AgentAdapter
protocol (`run(action) -> dict`). Generative adapters take an injected
`generate` callable so they stay pure + testable. The registry + builders
(adapter_for / ctx_for) are appended in Task 3."""

from core.portfolio import llm
from core.portfolio.adapters.research import ResearchAdapter
from core.portfolio.adapters.workflow import WorkflowPackAdapter
from core.portfolio.adapters.leads import LeadsAdapter
from core.portfolio.adapters.outreach_draft import OutreachDraftAdapter
from core.portfolio.adapters.proposal import ProposalAdapter
from core.portfolio.adapters.outreach_send import OutreachSendAdapter
from core.portfolio.adapters.site import SiteAdapter
from core.portfolio.adapters.infra import InfraAdapter
from core.portfolio.adapters.enrich import LeadsEnrichAdapter


class NoopAdapter:
    def run(self, action) -> dict:
        return {"status": "noop", "verb": action.verb}


_g = llm.default_generate
ADAPTERS: dict[str, object] = {
    "research_niche": ResearchAdapter(generate=_g),
    "build_workflow_pack": WorkflowPackAdapter(generate=_g),
    "generate_lead_list": LeadsAdapter(),
    "enrich_leads": LeadsEnrichAdapter(),
    "draft_outreach": OutreachDraftAdapter(generate=_g),
    "draft_proposal": ProposalAdapter(generate=_g),
    "run_outreach_campaign": OutreachSendAdapter(),
    "publish_landing_page": SiteAdapter(generate=_g),
    "deploy_demo_instance": InfraAdapter(),
}
_NOOP = NoopAdapter()


def adapter_for(step):
    return ADAPTERS.get(step.verb, _NOOP)


def ctx_for(step) -> dict:
    return {}
