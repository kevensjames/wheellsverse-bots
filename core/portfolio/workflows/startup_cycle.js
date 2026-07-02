export const meta = {
  name: 'startup-cycle',
  description: 'One acquisition cycle for a portfolio business: research -> pack spec -> GTM kit (propose mode, no send/deploy)',
  phases: [
    { title: 'Research', detail: 'market + niche brief' },
    { title: 'Build kit', detail: 'pack spec + outreach + landing + proposal, in parallel' },
    { title: 'Assemble', detail: 'single GTM kit' },
  ],
}

// Default = n8n; accepts an args override (string or object) for any of the 10.
const _N8N = {
  slug: "n8n", name: "n8n Automation Agency",
  offer: "Done-for-you 'Lead-to-Booking Engine' on self-hosted n8n: speed-to-lead instant SMS/email reply, missed-call text-back, no-show recovery, and 5-star review requests, wired into the med spa's booking system + Twilio. Setup build + monthly managed retainer.",
  price: "$1,500 setup + $400/mo managed",
  icp: "Owner-operator of a 1-3 location medical spa doing $40k-150k/mo, non-technical, leaking leads from slow response times",
  lead_niche: "medical spas", lead_geo: "Scottsdale, Arizona",
  landing_headline: "Stop Losing Botox Bookings to Slow Replies — Every Lead Texted Back in 60 Seconds",
  outreach_hook: "I filled out your med spa's contact form Tuesday at 2pm and never heard back — I built a 60-second auto-reply flow that books those leads before they ghost.",
  build_step: "build_workflow_pack",
}
let b
try { b = (typeof args === 'string') ? JSON.parse(args) : args } catch (e) { b = null }
if (!b || !b.offer) b = _N8N

phase('Research')
const research = await agent(
  `Act as a senior market researcher. Business "${b.name}" sells: ${b.offer} (price: ${b.price}) to: ${b.icp}. ` +
  `Target niche: ${b.lead_niche} in ${b.lead_geo}. Produce a tight, realistic market brief: the top 3 pains this ` +
  `offer removes, the 2 alternatives the buyer uses today, the single sharpest wedge to lead with, and the 3 ` +
  `objections to expect. Specific and lean — solo operator.`,
  { label: 'research', phase: 'Research' })

phase('Build kit')
const [pack, outreach, landing, proposal] = await parallel([
  () => agent(
    `Act as a senior solutions architect. Spec the "${b.build_step}" deliverable for: ${b.offer}. ` +
    `List exactly what is in the productized-service pack — components, what the client receives, and what is reused ` +
    `across clients vs. customized per client. Lean and buildable by a solo operator.`,
    { label: 'pack', phase: 'Build kit' }),
  () => agent(
    `Act as a senior B2B cold-outreach copywriter. Write a 3-touch email sequence (day 0/3/7) for ${b.icp}, opening ` +
    `from this hook: "${b.outreach_hook}". Concise, human, one clear CTA (10-min call), subject lines, one-line opt-out each. No hype.`,
    { label: 'outreach', phase: 'Build kit' }),
  () => agent(
    `Act as a senior landing-page copywriter. Write landing copy for "${b.name}" with H1 "${b.landing_headline}". ` +
    `Sections: hero, problem, the offer (${b.offer}), why-trust, pricing (${b.price}), 4-question FAQ, CTA. ` +
    `Tight and conversion-oriented for ${b.icp}.`,
    { label: 'landing', phase: 'Build kit' }),
  () => agent(
    `Act as a senior sales closer. Write a one-page proposal template for ${b.offer} at ${b.price}, tailored to ${b.icp}: ` +
    `outcome, scope, timeline, investment, a risk-reversal/guarantee, next step. Use {{merge_fields}} for personalization.`,
    { label: 'proposal', phase: 'Build kit' }),
])

phase('Assemble')
const kit = await agent(
  `Assemble one clean go-to-market kit (markdown) for "${b.name}". Start with: "PROPOSE MODE — drafts for operator ` +
  `review; nothing sent, published, or deployed." Sections: Market Brief, Service Pack (${b.build_step}), Outreach ` +
  `Sequence, Landing Copy, Proposal Template.\n\n=== MARKET BRIEF ===\n${research}\n\n=== PACK ===\n${pack}\n\n` +
  `=== OUTREACH ===\n${outreach}\n\n=== LANDING ===\n${landing}\n\n=== PROPOSAL ===\n${proposal}`,
  { label: 'assemble', phase: 'Assemble' })

return { business: b.slug, gtm_kit: kit }
