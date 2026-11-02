# Recon map: Baremetrics (web)

Scope: the core metrics dashboard, its data-source connections, customer views, segments and filters, and the scheduled summary reports (email and Slack). Not in scope: Recover (dunning), Cancellation Insights, Trial Insights, Forecast, Benchmarks and data augmentation.
For: the owner's own one-person company (this repo). They sell one-off digital products and some subscriptions across Stripe, Gumroad, Shopify, Kit (email list), Stan Store, Digistore24, BigCommerce, Whop, Payhip and Amazon KDP. They want one morning view of revenue and leads across all of them.
Date: 2026-11-02

How to read this map:

- Numbers in brackets, like [31], point to the Sources table. Files in this repo are cited by path and line.
- Confidence: **high** means several sources agree or an official page says it. **medium** means one credible source. **guess** means inferred.
- Clean room: public sources only. Nobody logged in anywhere. No Baremetrics JavaScript was read or saved, and no private endpoints were used.
- Click counts are estimates. The screen, flow, metric and component IDs are this map's own numbering.
- Read "Limits of this recon" at the end before running /replica-design.

## Sources

Most web pages were seen only as search-result titles, URLs and summaries, because WebFetch was blocked. Rows marked "not opened" were cited from the researcher's prior knowledge. Repo rows were read directly.

| # | source | URL | notes |
| --- | --- | --- | --- |
| 1 | help center | https://help.baremetrics.com/en/collections/3026812-know-your-metrics | "Know Your Metrics" collection: the metric articles |
| 2 | help center | https://help.baremetrics.com/en/collections/3026808-using-baremetrics | "Using Baremetrics" collection: Data Settings, Compare Date Ranges, Investor Links, excluding customers |
| 3 | help center | https://help.baremetrics.com/en/collections/3026820-integration-guides | Integration guides: Stripe, Recurly, Braintree, Shopify Partners, App Store Connect, Google Play, Chargebee (Beta), Xero, Intercom, Zapier, Slack, API |
| 4 | help center | https://help.baremetrics.com/en/articles/5380330-monthly-recurring-revenue | MRR rules |
| 5 | help center | https://help.baremetrics.com/en/articles/5380338-arr-annual-run-rate | ARR article (title only seen) |
| 6 | help center | https://help.baremetrics.com/en/articles/5380334-arpu-average-revenue-per-user | ARPU = MRR / Active Customers |
| 7 | help center | https://help.baremetrics.com/en/articles/5380345-ltv-lifetime-value | LTV = ARPU / User Churn |
| 8 | help center | https://help.baremetrics.com/en/articles/5380347-user-and-revenue-churn | User and revenue churn, rolling 30 days |
| 9 | help center | https://help.baremetrics.com/en/articles/5380355-net-revenue | Net Revenue |
| 10 | help center | https://help.baremetrics.com/en/articles/5554856-fees-metric | Fees metric |
| 11 | help center | https://help.baremetrics.com/en/articles/12542396-usage-revenue | Usage Revenue (Stripe metered) |
| 12 | help center | https://help.baremetrics.com/en/articles/9096541-usage-based-billing | Non-Stripe usage reported as Other Revenue |
| 13 | help center | https://help.baremetrics.com/en/articles/8594409-asp-average-sales-price | ASP |
| 14 | help center | https://help.baremetrics.com/en/articles/8594448-nrr-net-revenue-retention | NRR |
| 15 | help center | https://help.baremetrics.com/en/articles/9893951-net-revenue-retention-nrr-vs-gross-revenue-retention-grr | NRR vs GRR |
| 16 | help center | https://help.baremetrics.com/en/articles/5380342-new-customers-and-upgrades | New Customers and Upgrades; customer list; Compare Plans |
| 17 | help center | https://help.baremetrics.com/en/articles/5380343-cancellations-and-downgrades | Cancellations and Downgrades; interval tip |
| 18 | help center | https://help.baremetrics.com/en/articles/5380323-reactivations | Reactivations; Revenue Breakout |
| 19 | help center | https://help.baremetrics.com/en/articles/5380315-failed-charges | Failed Charges metric and page |
| 20 | help center | https://help.baremetrics.com/en/articles/5427087-plan-breakdowns-active-subscriptions | Plan Breakdowns and Active Subscriptions |
| 21 | help center | https://help.baremetrics.com/en/articles/11740744-filtering-customers-in-baremetrics | Customer filters |
| 22 | help center | https://help.baremetrics.com/en/articles/5379934-segment-your-metrics | Segments; compare up to 5 |
| 23 | help center | https://help.baremetrics.com/en/articles/5539022-creating-custom-dashboards | Custom dashboards |
| 24 | help center | https://help.baremetrics.com/en/articles/5380058-goals | Goals |
| 25 | help center | https://help.baremetrics.com/en/articles/5380063-compare-date-ranges | Compare Dates |
| 26 | help center | https://help.baremetrics.com/en/articles/5380055-annotations | Annotations (not read in detail) |
| 27 | help center | https://help.baremetrics.com/en/articles/12543014-data-exports | Data Exports |
| 28 | help center | https://help.baremetrics.com/en/articles/5380550-slack-integration | Slack integration |
| 29 | help center | https://help.baremetrics.com/en/articles/5380101-email-notifications | Email notifications |
| 30 | help center | https://help.baremetrics.com/en/articles/5373959-invite-team-members | Settings from the profile picture; Team; roles |
| 31 | help center | https://help.baremetrics.com/en/articles/5380115-data-settings | Data Settings |
| 32 | help center | https://help.baremetrics.com/en/articles/5380456-stripe | Stripe connection and import time |
| 33 | help center | https://help.baremetrics.com/en/articles/5380452-shopify-partners-apps | Shopify Partners (app billing, not stores) |
| 34 | help center | https://help.baremetrics.com/en/articles/5380475-connecting-multiple-data-sources | Several sources are combined |
| 35 | help center | https://help.baremetrics.com/en/articles/5380439-chargebee-beta | Chargebee (Beta) |
| 36 | help center | https://help.baremetrics.com/en/articles/9709051-xero-integration | Xero (out of slice) |
| 37 | help center | https://help.baremetrics.com/en/articles/8174445-getting-started | Forecast+ with QuickBooks and Xero (out of slice) |
| 38 | help center | https://help.baremetrics.com/en/articles/5380088-manual-subscription-import-guide | CSV import run by support |
| 39 | help center | https://help.baremetrics.com/en/articles/10628509-using-the-baremetrics-api | API for payments not captured automatically |
| 40 | help center | https://help.baremetrics.com/en/articles/13604718-baremetrics-for-hubspot-setup-guide | HubSpot (out of slice) |
| 41 | help center | https://help.baremetrics.com/en/articles/5380395-intercom-integration | Intercom (out of slice) |
| 42 | help center | https://help.baremetrics.com/en/articles/5380613-zapier-integration | Zapier actions |
| 43 | help center | https://help.baremetrics.com/en/articles/15518999-customer-insights-non-paying-renewing-cancelling-geo | Customer Insights lists |
| 44 | help center | https://help.baremetrics.com/en/articles/5497515-manually-excluding-customers | Exclude and GDPR delete |
| 45 | help center | https://help.baremetrics.com/en/articles/5380112-hide-and-favorite-plans | Hide and favorite plans |
| 46 | help center | https://help.baremetrics.com/en/articles/5702219-change-your-plan-names-with-stripe | Plan names come from Stripe |
| 47 | help center | https://help.baremetrics.com/en/articles/5379838-customer-augmentation | Customer augmentation (out of slice) |
| 48 | help center | https://help.baremetrics.com/en/articles/5379918-benchmarks | Benchmarks (out of slice) |
| 49 | help center | https://help.baremetrics.com/en/articles/15427470-connecting-baremetrics-to-ai-tools-via-mcp-claude-cursor-codex | MCP connection to AI tools |
| 50 | help center | https://help.baremetrics.com/en/articles/16056371-claude-connector | Claude connector |
| 51 | help center | https://help.baremetrics.com/en/articles/8264286-from-start-to-success-baremetrics-onboarding-guide | Onboarding guide (intro only); native integrations |
| 52 | changelog | https://changelog.baremetrics.com/segmentation-4m1cB2 | Compare Segments button |
| 53 | changelog | https://changelog.baremetrics.com/2026-03-18-new-segmented-breakouts | P&L-style breakouts (2026-03-18) |
| 54 | changelog | https://changelog.baremetrics.com/2026-03-09-new-export-breakdown-details-report | Breakdown Details export (2026-03-09) |
| 55 | changelog | https://changelog.baremetrics.com/your-data-your-way--now-exportable-on-demand-1OIXqE | Data exports launch |
| 56 | changelog | https://changelog.baremetrics.com/goals-+-tabular-data-in-custom-dashboards-3NXkZi | Goal and table widgets |
| 57 | changelog | https://changelog.baremetrics.com/new-attributes-for-charges-4oFn7W | One-time and recurring charge attributes |
| 58 | changelog | https://changelog.baremetrics.com/new-track-your-usage-based-revenue-4qcN68 | Metrics > Usage Revenue |
| 59 | changelog | https://changelog.baremetrics.com/new-more-clarity-for-charges-without-invoices-2QzSy4 | Invoice-less Stripe charges in Other Revenue |
| 60 | changelog | https://changelog.baremetrics.com/new-metric-average-sale-price-asp-17S4OQ | ASP launch |
| 61 | changelog | https://changelog.baremetrics.com/retention-cohort-tables-have-a-new-home-1pWUak | Cohort tables get their own section |
| 62 | changelog | https://changelog.baremetrics.com/new-stripe-metadata-customer-properties---synced-searchable-segmentable-3obq7u | Stripe metadata as attributes |
| 63 | changelog | https://changelog.baremetrics.com/new-last-known-attributes-2mVCBq | Last Known attributes |
| 64 | changelog | https://changelog.baremetrics.com/2026-06-16-new-customer-insights-renewing-cancelling-non-paying-and-geo-data | Customer Insights launch (June 2026) |
| 65 | changelog | https://changelog.baremetrics.com/trials-refunds-and-fees-now-in-api-4bNDUI | Trials, refunds and fees in the API |
| 66 | changelog | https://changelog.baremetrics.com/manual-subscriptions---edit-plan-names-4nKrW8 | Rename manual plans |
| 67 | changelog | https://changelog.baremetrics.com/apple-app-store-connect-43QSgU | App Store Connect; connect many sources |
| 68 | changelog | https://changelog.baremetrics.com/intercom-app-metrics-+-in-app-data-3G0zlu | Intercom sidebar (out of slice) |
| 69 | changelog | https://changelog.baremetrics.com/2026-04-29-new-cancellation-insights-with-plan-filters-and-breakdowns | Cancellation Insights (out of slice) |
| 70 | blog | https://baremetrics.com/blog/what-metrics-does-baremetrics-monitor | "28 metrics" post |
| 71 | blog | https://baremetrics.com/blog/what-customer-events-are-tracked-in-baremetrics | Customer events; feed filter |
| 72 | blog | https://baremetrics.com/blog/new-feature-live-stream | Live Stream launch |
| 73 | blog | https://baremetrics.com/blog/setting-up-your-baremetrics-account | Setup steps; Control Center; Live Stream |
| 74 | blog | https://baremetrics.com/blog/the-quick-guide-to-getting-started-with-baremetrics | Getting-started order |
| 75 | blog | https://baremetrics.com/blog/new-feature-customer-profiles | Customer profiles and directory sort (older post) |
| 76 | blog | https://baremetrics.com/blog/get-baremetrics-insights-inside-stripe-with-our-new-app | Stripe App; customer view (Jul 2022, updated Feb 2026) |
| 77 | blog | https://baremetrics.com/blog/new-metric-refunds | Refunds metric |
| 78 | blog | https://baremetrics.com/blog/different-mrr-data | Why its MRR differs from Stripe's |
| 79 | blog | https://baremetrics.com/blog/new-feature-notifications | Email notifications launch |
| 80 | blog | https://baremetrics.com/blog/multi-currency | Currency conversion per transaction date |
| 81 | blog | https://baremetrics.com/blog/baremetrics-integration-platforms | Native integrations; several sources in one view |
| 82 | blog | https://baremetrics.com/blog/baremetrics-stripe-platform-integrations | Unified MRR; segment by source |
| 83 | blog | https://baremetrics.com/blog/revenue-churn | Revenue churn (conflicting rule) |
| 84 | blog | https://baremetrics.com/blog/reactivating-subscriptions-reactivating-and-resuming-metrics-for-your-subscriptions | Reactivation MRR |
| 85 | blog | https://baremetrics.com/blog/what-is-contraction-monthly-recurring-revenue | Contraction MRR |
| 86 | blog | https://baremetrics.com/blog/how-to-import-augment-and-segment-customers-in-baremetrics | Add Filter; saved segment numbers |
| 87 | blog | https://baremetrics.com/blog/saas-pricing-models | Only paying subscribers are active customers |
| 88 | marketing site | https://baremetrics.com/metrics | Metric formulas |
| 89 | academy | https://baremetrics.com/academy/annual-run-rate | ARR = MRR x 12 |
| 90 | academy | https://baremetrics.com/academy/average-revenue-per-user-arpu | ARPU worked example |
| 91 | academy | https://baremetrics.com/academy/lifetime-value-ltv | LTV |
| 92 | academy | https://baremetrics.com/academy/saas-calculate-mrr | MRR normalisation example |
| 93 | marketing site | https://baremetrics.com/arr-calculator | ARR calculator; 100%-off customers excluded |
| 94 | marketing site | https://baremetrics.com/features/smart-dashboards | Smart dashboards: trendlines, goals, widgets |
| 95 | marketing site | https://baremetrics.com/features/metrics | Native connections list |
| 96 | pricing page | https://baremetrics.com/pricing | "Over 28 subscription metrics"; older cache with Metrics-plan features |
| 97 | pricing page | https://baremetrics.com/pricing?via=super | Cached snippet, date unknown: Launch, Growth, Scale |
| 98 | video | https://baremetrics.com/videos/baremetrics-make-custom-dashboards | Personalised home dashboard (Feb 2025) |
| 99 | video | https://baremetrics.com/videos/baremetrics-connect-your-payment-provider | Connect a payment provider (Feb 2025) |
| 100 | video | https://baremetrics.com/videos/why-we-built-the-baremetrics-mcp-saas-metrics-in-one-chat | Baremetrics MCP (Aug 2026) |
| 101 | video | https://baremetrics.com/videos/how-to-connect-baremetrics-to-hubspot-step-by-step | HubSpot setup (out of slice) |
| 102 | video | https://baremetrics.com/videos/baremetrics-add-custom-fields-customer-attributes | UTM sources as custom attributes |
| 103 | public demo | https://demo.baremetrics.com/stats/active-customers | Demo metric page route |
| 104 | founder post | https://x.com/Shpigford/status/714856134675398656?lang=en | /baremetrics slash command examples (2016) |
| 105 | connector listing | https://claude.com/connectors/baremetrics | Read-only connector tools |
| 106 | add-on listing | https://workspace.google.com/marketplace/app/baremetrics_for_sheets/815522020118 | Google Sheets add-on: one function per metric |
| 107 | API docs | https://developers.baremetrics.com/ | Developer portal; API keys in Settings |
| 108 | API docs | https://developers.baremetrics.com/reference | Reference navigation (resource groups) |
| 109 | API docs | https://developers.baremetrics.com/reference/introduction.md | Points to the llms.txt index |
| 110 | API docs | https://developers.baremetrics.com/reference/authentication | Bearer: API key or OAuth token |
| 111 | API docs | https://developers.baremetrics.com/reference/pagination.md | 30 per page by default, 200 max |
| 112 | API docs | https://developers.baremetrics.com/reference/quick-start | Plan, customer and subscription bodies |
| 113 | API docs | https://developers.baremetrics.com/reference/sources | Sources; only API-fed data is writable |
| 114 | API docs | https://developers.baremetrics.com/reference/create-plan | Create Plan; trial rule |
| 115 | API docs | https://developers.baremetrics.com/reference/list-customers | List Customers search fields |
| 116 | API docs | https://developers.baremetrics.com/reference/delete-customer.md | Delete Customer rule |
| 117 | API docs | https://developers.baremetrics.com/reference/list-customer-events.md | Customer events schema |
| 118 | API docs | https://developers.baremetrics.com/reference/set-attributes | POST /v1/attributes |
| 119 | API docs | https://developers.baremetrics.com/reference/create-subscription | Create Subscription; addons |
| 120 | API docs | https://developers.baremetrics.com/reference/update-subscription | Update Subscription |
| 121 | API docs | https://developers.baremetrics.com/reference/cancel-subscription | Cancel Subscription rule |
| 122 | API docs | https://developers.baremetrics.com/reference/delete-refund | Delete one-off refunds only |
| 123 | API docs | https://developers.baremetrics.com/reference/create-annotation | Annotation fields |
| 124 | API docs | https://developers.baremetrics.com/reference/list-goals | GET /v1/goals |
| 125 | API docs | https://developers.baremetrics.com/reference/show-goal.md | /v1/goals/{id} |
| 126 | API docs | https://developers.baremetrics.com/reference/show-summary | Show Summary: one row per day |
| 127 | API docs | https://developers.baremetrics.com/reference/show-metric | Show Metric |
| 128 | API docs | https://developers.baremetrics.com/reference/show-customers | Customers behind a metric |
| 129 | API docs | https://developers.baremetrics.com/reference/customer | Metric ids for Show Customers (updated 2026-04-15) |
| 130 | API docs | https://developers.baremetrics.com/reference/create-segment | Segment query shape |
| 131 | API docs | https://developers.baremetrics.com/reference/list-fields | GET /v1/segments/fields |
| 132 | third party | https://www.rubydoc.info/gems/baremetrics_api/BaremetricsAPI/Endpoint/Metrics | Ruby gem: metrics methods |
| 133 | third party | https://www.rubydoc.info/gems/baremetrics_api/BaremetricsAPI/Endpoint/Events | Ruby gem: list_events, show_event |
| 134 | third party | https://www.rubydoc.info/gems/baremetrics_api/BaremetricsAPI/Endpoint/Subscriptions | Ruby gem: subscription methods |
| 135 | third party | https://www.rubydoc.info/gems/baremetrics_api/BaremetricsAPI/Endpoint/Goals | Ruby gem: goal methods |
| 136 | third party | https://www.rubydoc.info/gems/baremetrics_api/BaremetricsAPI/Endpoint/Users | Ruby gem: list_users, show_user |
| 137 | third party | https://www.rubydoc.info/gems/baremetrics_api/BaremetricsAPI/Endpoint/Charges | Ruby gem: charge methods incl. create |
| 138 | third party | https://www.rubydoc.info/gems/baremetrics_api/BaremetricsAPI/Endpoint/Plans | Ruby gem: plan methods |
| 139 | third party | https://raw.githubusercontent.com/api-evangelist/baremetrics/refs/heads/main/openapi/baremetrics-charges-api-openapi.yml | Charge schema |
| 140 | third party | https://raw.githubusercontent.com/api-evangelist/baremetrics/refs/heads/main/openapi/baremetrics-annotations-api-openapi.yml | Annotations spec |
| 141 | third party | https://raw.githubusercontent.com/api-evangelist/baremetrics/refs/heads/main/rate-limits/baremetrics-rate-limits.yml | Rate-limit claim |
| 142 | third party | https://raw.githubusercontent.com/api-evangelist/baremetrics/refs/heads/main/finops/baremetrics-finops.yml | Claim: API access on Scale only |
| 143 | third party | https://apis.io/apis/baremetrics/baremetrics-metrics-api/ | Metric keys (OpenAPI copy) |
| 144 | third party | https://apis.io/apis/baremetrics/baremetrics-plans-api/ | Plan schema mirror |
| 145 | third party | https://apis.io/apis/baremetrics/baremetrics-subscriptions-api/ | Subscriptions list filter |
| 146 | third party | https://hub.windmill.dev/scripts/baremetrics/8963 | Update-subscription body |
| 147 | third party | https://hub.windmill.dev/scripts/baremetrics/8958 | Create-subscription body |
| 148 | third party | https://hub.windmill.dev/scripts/baremetrics/8954 | Create-plan script (trial units) |
| 149 | third party | https://docs.composio.dev/toolkits/baremetrics.md | Daily summary rows; cents; list params |
| 150 | third party | https://glama.ai/mcp/servers/jonnilundy/mcp-baremetrics/tree | Community MCP metric list |
| 151 | third party | https://www.stitchflow.com/user-management/baremetrics/api | Sources sample; cents; write limits |
| 152 | third party | https://jentic.com/apis/baremetrics | Generated spec; POST /sources claim |
| 153 | third party | https://www.truto.one/integrations/detail/baremetrics | Webhook names (unverified) |
| 154 | third party | https://rapidapi.com/stefan.skliarov/api/Baremetrics/details | "created" as a datetime (conflict) |
| 155 | third party | https://www.rapidevelopers.com/md/flutterflow-integrations/baremetrics | API organised around sources |
| 156 | third party | https://www.yodeck.com/docs/user-manual/baremetric-widget-code | /stats/<metric> links with dates in the URL hash |
| 157 | third party | https://www.pabbly.com/baremetrics-review/ | Older walkthrough |
| 158 | third party | https://www.putler.com/blog/baremetrics-review/ | Competitor review: about 20 metrics plus live stream |
| 159 | third party | https://g2.com/products/baremetrics/reviews | G2 reviews: Control Center as daily go-to |
| 160 | third party | https://www.g2.com/products/baremetrics/pricing | G2 pricing; free trial |
| 161 | third party | https://flexprice.io/glossary/contraction-mrr | Contraction MRR (conflicting) |
| 162 | third party | https://hackceleration.com/resources/integrations/zapier/baremetrics | Zapier: 0 triggers, 4 actions |
| 163 | third party | https://hackceleration.com/resources/integrations/claude/baremetrics | 17 tools; 3,600 requests/hour claim |
| 164 | third party | https://cdnjs.com/libraries/baremetrics-calendar/1.0.8 | Baremetrics' open-source date picker listing. Not opened (clean room) |
| 165 | third party | https://xexeq.jp/blogs/media/topics16136 | Investor Links news summary (Japanese) |
| 166 | pricing tracker | https://pricingsaas.com/companies/baremetrics | 2026 plans and add-ons |
| 167 | pricing tracker | https://pricingsaas.com/companies/baremetrics/diffs/2025Q3 | Move to ARR-based tiers |
| 168 | pricing tracker | https://pricingsaas.com/companies/baremetrics/diffs/2026W33 | Monthly prices removed from the FAQ |
| 169 | pricing tracker | https://pricingsaas.com/companies/baremetrics/diffs/2026W40 | ARR slider, free tier, $69 and $409 |
| 170 | pricing tracker | https://pricingsaas.com/companies/baremetrics/diffs/2026W41 | Back to $189 and $749 |
| 171 | pricing tracker | https://findstack.com/products/baremetrics/reviews?page=3 | July 2026 capture; tier feature lists |
| 172 | pricing tracker | https://findstack.com/products/baremetrics/pricing | Old pricing (Feb 2024) |
| 173 | pricing tracker | https://costbench.com/software/product-analytics/baremetrics/ | Prices as of June 2026 |
| 174 | pricing tracker | https://costbench.com/changelog/baremetrics-price-decrease-2026-09/ | Sep 2026: top tier at $749 |
| 175 | pricing tracker | https://costbench.com/software/product-analytics/baremetrics/free-plan/ | No free plan (Aug 2026) |
| 176 | pricing tracker | https://frontdeskreview.com/software/subscription-analytics/baremetrics/ | Verified Sep 3, 2026; 14-day trial |
| 177 | pricing tracker | https://getpulsesignal.com/compare/baremetrics-vs-memberful | Verified Oct 11, 2026 (internally inconsistent) |
| 178 | pricing tracker | https://toolradar.com/compare/baremetrics-vs-morevy | Oct 13, 2026: Launch $75, no free plan |
| 179 | pricing tracker | https://visualping.io/pages/baremetrics-pricing-alerts-4895240 | Mid-2026 redesign; custom plan |
| 180 | pricing tracker | https://us.fitgap.com/products/006445/baremetrics | No permanent free tier found |
| 181 | vendor docs | https://docs.stripe.com/webhooks | Not opened; prior knowledge |
| 182 | vendor docs | https://docs.stripe.com/keys | Restricted keys. Not opened |
| 183 | vendor docs | https://docs.stripe.com/api/balance_transactions/list | Not opened |
| 184 | vendor docs | https://docs.stripe.com/rate-limits | Not opened |
| 185 | vendor docs | https://docs.stripe.com/api/events/list | 30-day event window. Not opened |
| 186 | vendor docs | https://docs.stripe.com/api/charges/object | Charge "application" field. Not opened |
| 187 | vendor docs | https://app.gumroad.com/api | Gumroad API v2. Not opened |
| 188 | vendor docs | https://shopify.dev/docs/api/webhooks | Not opened |
| 189 | vendor docs | https://shopify.dev/docs/api/usage/access-scopes | read_orders vs read_all_orders. Not opened |
| 190 | vendor docs | https://shopify.dev/docs/api/usage/rate-limits | Not opened |
| 191 | vendor docs | https://shopify.dev/docs/api/usage/bulk-operations/queries | Not opened |
| 192 | vendor docs | https://shopify.dev/docs/api/admin-graphql/latest/queries/orders | Not opened |
| 193 | vendor docs | https://www.shopify.com/legal/api-terms | Shopify API terms. Not opened |
| 194 | vendor docs | https://developers.kit.com/v4 | Kit API v4. Not opened; current URL to confirm |
| 195 | vendor docs | https://developer.bigcommerce.com/docs/rest-management/orders | Not opened |
| 196 | vendor docs | https://developer.bigcommerce.com/docs/integrations/webhooks | Not opened |
| 197 | vendor docs | https://developer.bigcommerce.com/docs/start/authentication/api-accounts | Not opened |
| 198 | vendor docs | https://docs.whop.com | Not opened |
| 199 | vendor docs | https://developers.facebook.com/docs/marketing-api/insights | Meta Insights. Not opened |
| 200 | vendor docs | https://developers.facebook.com/docs/graph-api/overview/rate-limiting | Not opened |
| 201 | vendor docs | https://developers.facebook.com/docs/graph-api/changelog/versions | Not opened |
| 202 | vendor docs | https://developers.facebook.com/terms/ | Meta Platform Terms. Not opened |
| 203 | vendor docs | https://www.amazon.com/gp/help/customer/display.html?nodeId=508088 | Amazon Conditions of Use. Not opened |
| 204 | repo | .claude/skills/replica-recon/SKILL.md | Clean-room rules for this run |
| 205 | repo | core/scoreboard.py | Scoreboard: metric contract, sources, surfaces map |
| 206 | repo | frontend/admin/scoreboard.html | Scoreboard page |
| 207 | repo | core/api.py | Main app: routes, webhooks, middleware, schedulers (read in parts) |
| 208 | repo | core/revenue.py | RevenueEngine and daily report |
| 209 | repo | core/revenue_gate.py, core/base_bot.py | Revenue gate for the bots |
| 210 | repo | supabase_schema.sql | NarAI chat schema |
| 211 | repo | supabase_shopify_multitenant.sql | Multi-tenant Shopify app schema |
| 212 | repo | money_center/ | Registry of income estimates (README, registry, dashboard, cli, assets, tests) |
| 213 | repo | core/stripe_client.py, core/stripe_engine.py, core/stripe_router.py, core/chat_db.py | Other Stripe code |
| 214 | repo | core/gumroad_client.py | Gumroad v2 client |
| 215 | repo | core/whop_client.py | Whop v5 client |
| 216 | repo | core/kit.py | Kit v4 client |
| 217 | repo | core/convertkit.py | Legacy ConvertKit v3 client |
| 218 | repo | core/lead_capture.py | Second lead store; older v3 calls |
| 219 | repo | core/email_capture.py | Lead store |
| 220 | repo | narai/api/routes/toodle.py, narai/core/db.py | Kit capture and webhook tables |
| 221 | repo | core/shopify_client.py | Shopify Admin REST client |
| 222 | repo | narai/core/shopify_mt/webhooks.py, narai/core/shopify_mt/crypto.py | HMAC verifier; token encryption |
| 223 | repo | shopify.app.toml | Shopify app scopes |
| 224 | repo | core/click_tracker.py | /go clicks, UTMs, conversions |
| 225 | repo | core/siteboost_state.py | SiteBoost outreach state |
| 226 | repo | core/kdp_registry.py, narai/core/kdp/royalties.py, narai/godmode/adapters/amazon_kdp.py | KDP registry, royalty calculator, browser adapter |
| 227 | repo | core/publish_pipeline.py, core/twitter.py | Stan Store UTM links |
| 228 | repo | core/conversion_analytics.py | Funnel events |
| 229 | repo | core/impact.py | Impact.com affiliate client |
| 230 | repo | narai/integrations/scheduler.py, narai/integrations/briefing.py, narai/api/routes/briefing.py | Morning briefing |
| 231 | repo | core/output_automation.py | Email, Slack and Discord senders |
| 232 | repo | narai/marketing/ | Marketing autopilot (marketing_autopilot.py, schedule.yaml, autopilot.db) |
| 233 | repo | dashboard/index.html | Old Money Command Center panel |
| 234 | repo | core/meta_ads.py, core/budget_manager.py, core/performance.py | Meta Marketing API calls |
| 235 | repo | marketing/GLOBAL_PLAN.md, marketing/META_APP_REVIEW_SUBMISSION.md | The silo problem; Meta app review draft |
| 236 | repo | suprema/autorepair/scanners/committed_runtime_state.py | Note on a committed Stan Store session file |
| 237 | repo | railway.json, main.py, setup_cron.sh, scripts/daily_run.sh | How the app and jobs run |
| 238 | repo | .env.example | Variable names only; no values read |
| 239 | repo | .gitignore | data/*.json and data/*.db are ignored |
| 240 | repo | tests/test_scoreboard.py, tests/test_scoreboard_mount.py | Scoreboard tests |
| 241 | repo | backend/app/services/briefing/daily_brief.py | Trade-app daily brief |

## Core loop

**Baremetrics:** connect a billing tool once, then check the Control Center each day, or read the daily email or Slack summary, to see how subscription revenue moved [73, 159, 29, 28]. (high)

**The clone:** every morning, see what made money yesterday, from which store and which channel.

How well Baremetrics fits this owner:

- Of the ten stores, only Stripe is a native Baremetrics source. Its Shopify connector reads Shopify Partner app billing, not store orders [33, 81]. No native connector for the other eight stores appeared in any list found [3, 51, 95]. This absence was not checked directly. (medium) Payments Baremetrics does not capture (ACH, wire, PayPal, manual invoicing) go in through its API, or through a CSV import that its support team runs [39, 38]. (medium)
- Baremetrics is built around subscriptions. One-off sales show up only in Other Revenue and Net Revenue, and in the one-time-charge filters [9, 12, 57, 158]. (medium) Recommendation (inference): lead the home view with yesterday's net revenue by store and product. Keep MRR as a secondary card.
- Baremetrics merges sources and cannot split every graph by source. Per-source views go through a source segment [34, 21, 82]. (high) So the clone needs store as a first-class dimension on every card, chart and email line (inference).
- No metric for leads, email subscribers or marketing channel was found [1]. A channel only arrives as a customer attribute, such as a UTM source [102, 62, 47]. The clone needs Kit subscriber metrics and a channel field. (guess)
- The nearest Baremetrics pieces to "what made money yesterday" are the daily email, the daily Slack report, the Live Stream and the Breakdown Details export [29, 28, 72, 54]. None shows one-off revenue per store per day in one place. (guess)

## Screens

| ID | screen | route / how to reach | purpose | key components | states seen | evidence | confidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S00 | App shell and navigation | every page | move between sections | left sidebar: Control Center, Metrics (one page per metric, e.g. Metrics > Usage Revenue), Customers (directory, segments, Insights), Settings; the profile picture at the bottom left opens Settings | filled only | [30, 43, 58, 73] | high (sidebar, Settings); medium (section list) |
| S01 | Control Center (home) | the app's home | overview of business health; "the heart of your account" | metric cards (about 20 metrics per a competitor review; exact set and order not documented); live feed of events (S02); dashboard switcher dropdown ("Create New Dashboard"; gear > "Remove View"); a header "Customize" dropdown of key metrics in an older walkthrough [157] | filled only | [73, 23, 98, 158, 159] | high (exists); medium (default content) |
| S02 | Live Stream | beside the metric cards on S01 [158] | running feed of business events | event rows (signups, charges, upgrades, downgrades, cancellations, failed charges); some rows add an insight, such as a new subscriber's LTV; event-type filter | filled only | [72, 71, 73] | high (content); medium (placement) |
| S03 | Metric detail page (one template for every metric, M01-M25) | click a card on S01, or Metrics > a metric; third-party code links app.baremetrics.com/stats/<metric> with start_date and end_date in the URL hash [156]; the public demo uses /stats/<metric-slug> [103] | one metric over time, and who is behind it | time-series graph; toolbar with date range and "Compare Dates"; "Compare Segments" button at the top; "Goals" button at the graph's top right; day/week/month interval (implied); breakout rows (S04); "Compare Plans" section; customer list at the bottom (click a name for S08) | filled; limit: no segment comparison for Net Revenue [22] | [16, 17, 24, 25, 52, 156, 103] | high (page parts); medium (URL pattern); guess (interval) |
| S04 | Revenue Breakout | on metric pages for MRR, upgrades, downgrades, churn, refunds and customers [53]; exact placement not documented | MRR movement split into new, expansion, reactivation, downgrade and churn | P&L-style table with segment rows nested under each category (since 2026-03-18) | filled only | [53, 18] | high |
| S05 | Plan Breakdowns and Active Subscriptions | route not documented | every plan with its billing interval, active customers and active subscriptions | plan table; favorited plans at the top | filled only | [20, 45] | high |
| S06 | Retention cohort tables | own section; also on the User Churn and Revenue Churn pages | retention by signup cohort | cohort matrix; breakdown by segment; Retention Tables export (S19) | filled only | [61, 22, 27] | high |
| S07 | Customers directory | Customers tab | find and filter customers | "Add Filter" panel on the left (25+ attributes, search or scroll; each custom attribute gets its own filter); segment dropdown defaulting to "All Customers"; sort by LTV, plan, signup date and name, and search by almost any field (older post [75]) | filled only; current column list not found | [21, 86, 75] | high (filters); medium (sort, search) |
| S08 | Customer profile | click any customer name in the app | one customer's value and history | LTV (total charges), MRR, plans or products, social and location details, recent events, full history from signup through charges and failed charges to cancellation; actions: exclude, GDPR delete | filled only; current layout not documented | [75, 76, 44] | medium |
| S09 | Segments: save, manage, compare | save filters from S07; "All Customers" dropdown > "Manage Segments"; "Compare Segments" at the top of any metric | reuse a filter set as a lens on metrics | segment name; MRR, ARPU and Active Customers shown at once; Update or "Save as new"; compare up to 5 segments | filled; limit: Net Revenue cannot be compared | [22, 52, 86] | high |
| S10 | Customer Insights | Customers > Insights in the left sidebar | four lists: Non-Paying, Renewing, Cancelling, Geo | lists of up to 250 customers; Geo donut chart, full country list, count/MRR toggle, location-source switch (Card Country and others); CSV export by email | filled; partial (Renewing stays empty for integrations without billing-period dates; Cancelling is Stripe only; Non-Paying leaves out delinquent customers); stale up to a day (daily refresh) | [43, 64] | high |
| S11 | Custom dashboard builder | S01 > hover the dashboard dropdown > "Create New Dashboard" | save a named set of metrics, optionally for one segment | name; metric picker; "Share with team" checkbox; "Save"; gear > "Remove View"; widgets: metric, goal, table (lists of plans or customers tied to 12+ metrics) | filled only | [23, 56, 94, 98] | high |
| S12 | Goal editor ("Add a Goal") | "Goals" button at a graph's top right | a target line on a metric | name; start date and value; end date and value; the goal is drawn as a separate line | filled only | [24, 56] | high |
| S13 | Compare Dates | "Compare Dates" in the toolbar | compare a range with a past range | two date ranges | none seen; presets and how the difference shows are not documented | [25] | high (exists) |
| S14 | Settings > Data Connections | profile picture > Settings > Data Connections | connect and disconnect billing sources | list of sources; Connect and Disconnect; "Connect with Stripe" (OAuth); Chargebee: read-only API key and site subdomain; Shopify Partners: access token and organization ID | connected; importing (minutes to hours; no UI documented) | [33, 32, 35, 34, 99] | high |
| S15 | Settings > Team | profile picture > Settings > Team | invite people and set roles | "Invite User" form (name, email, "admin" checkbox); roles Admin, User (optional Forecast+ toggle), Billing User; unlimited members on every plan | filled only | [30] | high |
| S16 | Settings > Data Settings | Settings | rules that change the numbers | delinquency window (30 days by default, 2 months, or never); reporting currency (defaults to the Stripe default; others converted at each transaction date's rate; change once a day) | filled; reprocessing after a currency change (no UI documented) | [31, 80] | high |
| S17 | Settings > Notifications | Notifications page in account settings | email summaries and alerts | "Metric Summary" of all metrics, daily, weekly or monthly; instant notifications (e.g. downgrades, cancellations; failed charges at launch); separate on/off toggles | filled only; email layout, metric list and send time not found | [29, 79] | high |
| S18 | Settings > Slack Integration | Settings > Slack Integration | Slack alerts and reports | Connect (Slack sign-in, accept); channel picker; instant event notifications; daily, weekly and monthly reports with metrics chosen per report; "/baremetrics <metric> <interval>" from any channel ("/baremetrics" alone lists the commands) | filled only; whether posts include charts is not confirmed | [28, 104] | high |
| S19 | Settings > Data Exports | Settings > Data Exports | CSV exports by email | reports: MRR Per Customer; Retention Tables (segment, year); Active Subscriptions (as of a date); Customers Segmentation Data (segment); Breakdown Details (one date; one row per subscription event with event type, customer ID and name, previous and current plan, customer MRR, MRR change, ARR impact, previous and current coupon); "Export"; CSV zip by email | limit: 6 exports per day per report type; no per-graph CSV button found | [27, 55, 54] | high |
| S20 | Settings > Plan Management | Plan Management Settings page; manual plans in the Plans tab | tidy plan lists | "Hide" and favorite per plan; rename manual plans (edit icon > name > Save); provider plan names come from the provider | filled only; whether hiding a plan removes it from metrics is not documented | [45, 46, 66] | high |
| S21 | Exclude or GDPR-delete a customer | Customers tab: search, then exclude | keep a customer out of metrics, or erase them | exclude action; GDPR delete (excludes the customer and deletes the profile and its data); bulk exclusion by emailing support a list of IDs | filled only; single events cannot be excluded, because they would be re-imported from Stripe | [44] | high |

Navigation notes: sources also name sections outside the slice (Recover, Cancellation Insights, Trial Insights, Forecast or Forecast+, Benchmarks) [30, 157, 48]. The order and grouping of the Metrics menu were not found. An older third-party walkthrough puts settings under an avatar at the top right [157]; the newer official help says bottom left [30]. Trust the help. API keys live in Settings [107]. Do not copy the third-party /stats/ slugs; that code maps some metrics to the wrong slugs [156].

Other in-slice extras, with no screen seen: Investor Links, a time-limited read-only share with customer details anonymised [2, 165] (medium); a Google Sheets add-on with one function per metric [106] (high); an MCP server and a read-only Claude connector [49, 50, 100, 105] (high); Zapier actions that create customers, subscriptions and plans, with no triggers [42, 162] (high).

### Metric catalogue (each metric uses S03)

Baremetrics claims over 28 subscription metrics [96].

| ID | metric | rule | evidence | confidence |
| --- | --- | --- | --- | --- |
| M01 | MRR | Value of all active subscriptions, normalised to a month: $120 a year adds $10 MRR for 12 months. Coupons are deducted. Customers on 100%-off coupons are free users; putting a 100% coupon on a payer counts as user and revenue churn. Free or trial to paid is a new customer; paid to free is a cancellation. Payments are checked (delinquent or paused accounts are not counted) and prorations handled, so it differs from Stripe's figure. | [4, 78, 92] | high |
| M02 | ARR (Annual Run Rate) | Current MRR x 12, with the same exclusions as MRR. Assumes nothing changes for a year. The help article's body was not seen. | [89, 93, 5] | high |
| M03 | ARPU | MRR / Active Customers. Example: $3,459 / 146 = $23.69. | [6, 90] | high |
| M04 | ASP | Average amount paid at the first subscription. New sales only. Rolling 30 days, refreshed daily. | [13, 60] | high |
| M05 | LTV | ARPU / User Churn rate as a decimal ($60 / 0.05 = $1,200). Some content adds a margin factor; the help uses the revenue-only version. On profiles, "LTV" means total charges to date. | [7, 88, 91] | high |
| M06 | Active Customers | Paying customers with an active subscription. Free, trial, 100%-off and delinquent customers are left out, and so are one-time buyers with no subscription. The delinquency setting affects it. No standalone help article found. | [87, 4, 70] | medium |
| M07 | Active Subscriptions | Count of active subscriptions, per plan with billing interval. Also an export as of a chosen date. | [20, 27] | high |
| M08 | New Customers | Free plan, trial or no plan straight to a paid plan. | [16] | high |
| M09 | Upgrades / Expansion | One paid plan to a pricier paid plan. The blog adds automatic increases when a coupon ends. Feeds NRR, net revenue churn and Quick Ratio. | [16, 70] | high |
| M10 | Downgrades / Contraction | Still paying, but less per month. Moving to an annual plan with free months is a downgrade. Paid to free is a cancellation. Sources conflict on contraction MRR (downgrades plus cancellations, or downgrades only); pick one rule and write it down. | [17, 85, 161, 4] | high (downgrades); guess (contraction: sources conflict) |
| M11 | Cancellations | Paid plan to non-paid plan. Delinquent customers count once the Data Settings window passes (30 days by default). | [17, 31] | high |
| M12 | Reactivations | A former customer comes back. Reactivation MRR is revenue from customers who had cancelled and started a new subscription in the period. | [18, 70, 84] | high |
| M13 | User Churn | Rolling 30 days: customers who cancelled in the last 30 days / active customers 30 days ago. | [8, 88] | high |
| M14 | Revenue Churn | Rolling 30 days: MRR lost (cancellations plus downgrades) / MRR 30 days ago x 100. Some blog posts also count failed charges (conflict). | [8, 88, 83] | high |
| M15 | Net Revenue Churn | (Churned MRR - Expansion MRR) / MRR 30 days ago x 100. Goes negative when expansion wins. | [70, 88] | high |
| M16 | NRR | 100% - net revenue churn. Rolling 30 days. Also called Net Dollar Retention. | [14] | high |
| M17 | GRR | Like NRR without expansion, so never above 100%. Churned MRR includes downgrades and cancellations. Rolling 30 days. | [15, 88] | high |
| M18 | Quick Ratio | (New + Expansion + Reactivation MRR) / (Contraction + Churned MRR). 1 to 4 is healthy; above 4 is rapid growth. | [70] | medium |
| M19 | Net Revenue | Recurring plus non-recurring charges, minus refunds. Fees are not deducted. A month's total stays fixed after the month ends. Cannot be compared by segment. | [9, 11, 22] | high |
| M20 | Fees | Payment-provider fees (e.g. Shopify, Stripe, the App Store) as their own metric. Not removed from any other metric. Also in the API. | [10, 65] | high |
| M21 | Other Revenue | One-time (non-recurring) charges, including usage from non-Stripe sources and Stripe charges with no invoice (shown with descriptions). No article defines it directly. One-off product sales land here. | [12, 59, 129] | medium |
| M22 | Usage Revenue | Stripe only: gross revenue from metered prices. At Metrics > Usage Revenue. Segmentable by plan. | [11, 58] | high |
| M23 | Refunds | Money returned to customers. Dated by when the refund was issued. Does not change MRR. The page lists who was refunded. | [77, 70, 71] | high |
| M24 | Coupons | Money "lost" to coupons on active subscribers. | [70] | medium |
| M25 | Failed Charges | A provider charge attempt that fails, usually a card problem. The page shows failed charges per day, delinquent customers and customers with soon-to-expire cards. Recovering the money (Recover) is out of the slice. | [19, 70] | high |

Also named, with no definition found: Churned Customers, MRR Growth Rate and New Subscriptions (Sheets add-on [106]; API metric ids [129]). Trial metrics are out of the slice. The metric-key lists in the API, the Sheets add-on and a community MCP server differ from each other [143, 150, 149].

### States not seen (design them fresh)

- **No source connected.** The setup order is documented (sign up, connect billing data, then team, segments, dashboards) [73, 74, 51], but no screen was seen. Suggestion: a full-page "connect your first store" prompt, maybe with sample data. (guess)
- **Importing.** The first import takes minutes to hours, depending on data volume and the queue [32]. Add the next source only after it finishes [34]. No UI documented.
- **Reprocessing** after a currency change [31]. No UI documented.
- **Errors.** Failed sync, disconnected source, API or token errors: not documented.
- **Permission denied and upgrade prompts.** Roles exist (Admin, User, Billing User) [30], and tiers gate features such as Custom Dashboards [97], but no denied or upgrade screen was seen. A one-person clone can start without roles. (guess)
- **No data for the range, loading states, chart tooltips, date presets:** not documented.
- **Mobile and responsive layouts:** not documented.
- **Freshness.** Insights lists refresh once a day [43]. The clone should label how fresh each number is.

## Flows

```
F01 Connect a data source
    S00 profile picture -> Settings -> S14 Data Connections -> pick a provider
    -> "Connect with Stripe" -> authorise in Stripe -> import runs -> S01 fills
    happy path clicks: about 5, plus the import wait (estimate)
    edge: a long history means a slow import (minutes to hours; support can check progress);
          add the next source only after the import and calculations finish;
          Chargebee needs a read-only API key and the site subdomain;
          Shopify Partners sends no customer emails (add them through the API);
          the reporting currency is taken from Stripe
    evidence: [32, 34, 35, 33, 99]   confidence: high (steps), guess (clicks)

F02 Read the morning numbers
    a) open the app -> S01 Control Center (cards and the S02 Live Stream)
    b) the daily Metric Summary email (set up in F05)
    c) the daily Slack report (set up in F06), or "/baremetrics daily" in any channel
    audit one day: S19 Data Exports -> Breakdown Details for that date -> CSV by email
    happy path clicks: 0 for b) and c); a) is just opening the app (estimate)
    edge: no time-zone setting was found, so "yesterday" may not match the owner's day;
          one-off sales show only in Other Revenue and Net Revenue;
          Customer Insights lists can lag by up to a day
    evidence: [73, 29, 28, 54, 43]   confidence: high

F03 Drill into a metric
    S01 -> click a metric -> S03 (graph, date range, interval, S13 Compare Dates)
    -> S04 breakout rows and Compare Plans -> customer list -> click a name -> S08
    happy path clicks: about 3 to 4 (estimate)
    edge: daily data is spiky (the help suggests weekly or monthly intervals over a long range);
          the delinquency setting (S16) changes cancellations, MRR and churn
    evidence: [17, 16, 31, 25]   confidence: high (steps), guess (clicks)

F04 Filter by segment
    S07 Customers -> Add Filter -> pick an attribute (search or scroll) -> set a value
    -> add more filters -> save as a named segment (shows MRR, ARPU, Active Customers)
    -> S03 -> Compare Segments (up to 5), or pick it in the "All Customers" dropdown
    -> edit later in S09 via Manage Segments
    happy path clicks: about 6 to 8 (estimate)
    edge: Net Revenue cannot be compared by segment; attribute names must be unique;
          AND/OR and the filter operators are not confirmed
    evidence: [22, 21]   confidence: high (steps), guess (clicks)

F05 Set up the daily email report
    S00 profile picture -> Settings -> S17 Notifications -> turn on Metric Summary
    -> choose daily (or weekly, monthly) -> optionally turn on instant notifications
    happy path clicks: about 4 (estimate)
    edge: the email's content, metric list and send time are not documented
    evidence: [29]   confidence: high (steps), guess (clicks)

F06 Set up the daily Slack report
    S00 profile picture -> Settings -> S18 Slack Integration -> Connect -> sign in to Slack and accept
    -> choose a channel -> pick metrics for the daily report (and weekly, monthly) -> save
    happy path clicks: about 7 (estimate)
    edge: recurring reports go to one channel only; "/baremetrics" works in any channel;
          charts in posts are not confirmed; may need the Growth tier [171] (medium)
    evidence: [28]   confidence: high (steps), guess (clicks)

F07 Export CSV
    S00 profile picture -> Settings -> S19 Data Exports -> choose a report -> set its date, segment or year
    -> Export -> a CSV zip arrives by email
    happy path clicks: about 5, plus the email (estimate)
    edge: 6 exports per day per report type; no instant download;
          S10 Insights lists also export by email
    evidence: [27, 43]   confidence: high (steps), guess (clicks)

F08 Build a custom dashboard
    S09 save a segment -> S01 -> hover the dashboard dropdown -> Create New Dashboard (S11)
    -> name it -> add metrics -> tick Share with team -> Save
    happy path clicks: about 6 to 7 (estimate)
    edge: delete with the gear > Remove View; Custom Dashboards are a Growth-tier feature [97]
    evidence: [23, 97]   confidence: high (steps), guess (clicks)

F09 Set a goal
    S03 graph -> Goals (top right) -> S12 Add a Goal -> name, start and end dates and values
    -> save -> the goal line shows on the graph
    happy path clicks: about 4 (estimate)
    edge: Goal Tracking may need the Growth tier [171] (medium)
    evidence: [24]   confidence: high (steps), guess (clicks)

F10 Exclude or GDPR-delete a customer
    S07 Customers -> search for the customer -> S21 exclude, or GDPR delete
    (both actions are also listed on the S08 profile)
    happy path clicks: about 3 (estimate)
    edge: GDPR delete also deletes the profile and its data;
          single events cannot be excluded, because they would be re-imported from Stripe;
          bulk exclusion means emailing support a list of customer IDs;
          a confirmation step is not documented
    evidence: [44, 75]   confidence: high (steps), guess (clicks)
```

No flow covers S05, S06, S15 or S20. Each is a single page with no documented multi-step goal, and S05's route is not documented.

## Components

| component | variants | states | used on | evidence | confidence |
| --- | --- | --- | --- | --- | --- |
| Sidebar navigation (C00) | Control Center, Metrics (one item per metric), Customers (with Insights), Settings via the profile picture | not documented | all (S00) | [30, 43, 58] | high |
| Metric card (C09) | one per metric | anatomy is a guess: name, current value, change vs the previous period, small trend line, click-through to S03 | S01, S11 | [158] | guess |
| Dashboard widget (C01) | metric, goal (standalone tracker), table (plans or customers tied to 12+ metrics); segmentable by country, plan type or CRM data (marketing claim) | not documented | S01, S11 | [56, 94, 23] | high |
| Dashboard switcher (C02) | dropdown of saved dashboards; "Create New Dashboard"; gear > "Remove View" | opens on hover | S01, S11 | [23] | high |
| Time-series chart (C03) | overlays: goal line, selectable trendlines, up to 5 segment series; line or bar per metric not documented | tooltips not documented | S03, S06, S12 | [24, 94, 52] | high |
| Date range picker, Compare Dates and interval (C04) | one range; two ranges (Compare Dates); day/week/month interval (implied) | range kept in the URL hash (third party) [156] | S03, S13 | [25, 156, 17] | high (picker, compare); medium (URL); guess (interval) |
| Segment switcher and filter builder (C05) | "All Customers" dropdown with "Manage Segments"; "Add Filter" panel with a searchable attribute list; Save, Update, "Save as new"; "Compare Segments" multi-select capped at 5 | filters stack (AND implied; OR not confirmed) | S03, S07, S09 | [22, 21] | high |
| Table (C06) | customer list on metric pages (rows open S08); Customers directory (sortable); Compare Plans; plan breakdown; P&L-style breakout with nested segment rows; cohort matrix; Geo country list; dashboard table widget | not documented | S03 to S07, S10, S11 | [16, 53, 43, 61] | high |
| Donut chart (C10) | Geo by count or by MRR | count/MRR toggle | S10 | [43] | high |
| Live event row (C07) | new customer or signup, charge, upgrade, downgrade, cancellation, failed charge, refund, reactivation | optional insight line (e.g. LTV); event-type filter above the feed; row layout not documented | S01, S02 | [72, 71] | medium |
| Goal form (C11) | name, start date and value, end date and value | not documented | S12 | [24] | high |
| Settings controls (C08) | Invite User form (name, email, admin checkbox); notification toggles and frequency; Slack Connect, channel picker, per-report metric pickers; export list with filters and Export button; Data Settings selectors (delinquency, currency); plan Hide and Favorite buttons; Connect and Disconnect | not documented | S14 to S20 | [30, 29, 28, 27, 31, 45, 33] | high |
| Button (C12) | labels seen: "Add Filter", "Compare Segments", "Goals", "Save", "Update", "Save as new", "Export", "Connect", "Disconnect", "Invite User", "Hide" | not documented | S03, S07, S09, S11, S14, S15, S18, S19, S20 | [21, 22, 23, 24, 27, 28, 30, 33, 45, 52] | high (labels); guess (styles and states) |

Component IDs are stable and are not in table order. Inputs, modals, toasts, and empty, loading and error components were not documented in any source found; design them fresh in /replica-design.

Clean-room note for C04: Baremetrics published an open-source date range picker [164]. Do not open or reuse it. Build your own.

## Inferred data model

Baremetrics' public API gives most of the model. The clone will not call Baremetrics; these shapes only inform its own schema.

```
Account         id, name, reporting_currency, delinquency_window (30 days / 2 months / never)
                evidence: S16 [31, 80]; Account section of the API reference [108]; get-account tools [105, 149]
                confidence: high (the two settings, from help); guess (other fields; no schema found)

Source          id (the source_id in API paths), provider (e.g. stripe, or the Baremetrics API),
                provider_id (the upstream account id, e.g. acct_...)
                evidence: List Sources [113]; example response [151]; API organised around sources [155]; S14
                confidence: medium (every object belonging to a source is official; the field list is third-party);
                a POST /sources to register a custom source is claimed only by a third party [152] (unverified)

Plan            oid, source_id, name, currency, amount (integer cents: $10 = 1000), interval (e.g. month),
                interval_count, trial_duration, trial_duration_unit (day / month / year), hidden, favorite
                rule: only the first plan on a subscription triggers a trial
                evidence: Quick Start [112]; Create Plan [114]; [138, 144, 148]; S05 [20]; S20 [45]
                confidence: high (core fields); medium (trial units); guess (how hidden and favorite are stored)

Customer        oid (your id), source_id, name, email, notes (shown on the profile),
                created (Unix time; RapidAPI says a datetime: conflict),
                read-only: ltv (cents), is_active, is_canceled, current_mrr (cents), current_plans[],
                excluded and gdpr_deleted (app actions; names are guesses)
                rule: remove all subscriptions before deleting; list search matches oid, email, notes, name;
                      list sorts by ltv or created
                evidence: Quick Start [112]; List Customers [115]; Delete Customer [116]; [149, 151, 154]; S07, S08, S21 [44]
                confidence: high

CustomerAttribute  customer_oid or customer_email, field_id, value (arrays as comma-separated strings)
                rule: matched by oid across all sources; Stripe address, shipping and metadata sync in
                      automatically, and removing them in Stripe removes them here
                evidence: POST /v1/attributes [118]; [62]; Last Known attributes such as Last Known MRR [63]
                confidence: high

Subscription    oid, source_id, customer_oid, plan_oid, started_at (Unix seconds), canceled_at (empty while active),
                quantity, discount, addons[] {oid, amount, quantity}; updates may carry occurred_at
                rule: the customer and plan must exist first; canceled_at cannot be moved later
                evidence: Create, Update and Cancel Subscription [119, 120, 121]; [134, 145]; scripts [146, 147]
                confidence: high (core fields); medium (quantity, discount, addons body)

Charge          oid, source_id, amount (cents), currency, status (paid / failed / refunded), created (Unix),
                customer, subscription (empty for one-off charges: inferred), description (Stripe charges without invoices)
                evidence: third-party Charge schema [139]; gem methods incl. create [137]; Quick Start [112]; [59]
                confidence: medium

Refund          fields not found
                rule: one-off refunds (no subscription) can be deleted through the API, subscription refunds cannot;
                      dated by when issued; never changes MRR
                evidence: Delete Refund [122]; [65]; [77]
                confidence: high (rules); fields unknown

Fee             fields not found; provider fees on charges (the API takes fees on one-off charges)
                rule: its own metric; never removed from other metrics
                evidence: [10, 65]
                confidence: medium

Event           id, type, source, source_id, timestamp, customer oid
                types named: new customer, upgrade, downgrade, cancellation, reactivation, payment, failed charge, refund
                (exact type values not found); an account-wide event list (with a live-stream flag) also exists
                evidence: List Customer Events [117]; gem list_events and show_event [133]; [71]; S02
                confidence: medium

Annotation      id (integer), metric, annotation (text, required), date (YYYY-MM-DD, required),
                show-on-all-graphs flag, added-by (required); belongs to the account, not to a source
                evidence: Create Annotation [123]; [140]; help article [26] not read
                confidence: high (fields exist); JSON keys for the flag and the author not found

Goal            id, name, metric, start_date, start_value, end_date, end_value; belongs to the account
                evidence: Goals help [24]; GET and POST /v1/goals, GET and DELETE /v1/goals/{id} [124, 125, 135]
                confidence: high (goals exist with these inputs in the app); guess (API field names)

Segment         id, name, query[] {category (baremetrics / clearbit / customer_properties), field, method, value}
                evidence: Create Segment [130]; GET /v1/segments/fields grouped by category, e.g.
                          subscriptions.is_active [131]; S09 [22]
                confidence: high; allowed method values not found

Dashboard       id, name, segment, shared_with_team, widgets[] {type: metric / goal / table, metric}
                evidence: S11 [23]; widget types [56]
                confidence: medium (from help; not in the public API)

TeamMember      user, name, email, role (Admin / User / Billing User), forecast_plus_access
                evidence: S15 [30]; gem list_users and show_user [136]
                confidence: high (roles); guess (field names)

ReportSetting   channel (email / slack), frequency (daily / weekly / monthly),
                metrics[] (Slack: chosen per report; email summary: all metrics),
                slack_channel (one for all recurring reports), instant_event_types[]
                evidence: S17 [29]; S18 [28]
                confidence: guess (inferred from help; not in the public API)

ExportRequest   report_type (MRR Per Customer / Retention Tables / Active Subscriptions /
                Customers Segmentation Data / Breakdown Details), filters (date, segment, year),
                requested_at, emailed_at
                evidence: S19 [27, 54, 55]
                confidence: guess (entity); high (the limit of 6 per day per report type)

MetricSnapshot  account, date, one value per metric (mrr, arr, arpu, ltv, customers, net revenue, ...),
                money in integer cents of the account currency
                evidence: Show Summary returns one row per day for an inclusive range [126, 149];
                          Show Metric [127]; metric keys [143]
                confidence: medium
```

Relationships (sourced, high): Source 1-n Plan, Customer, Subscription and Charge [113]. Subscription n-1 Customer (customer_oid) and n-1 Plan (plan_oid), with 0-n addons [119]. Customer 1-n Event [117]. Customer n-m attribute fields, matched by oid across sources [118]. Annotation n-1 Metric, or shown on all graphs [123]. Every object is keyed by its oid within a source_id. Money is integer cents plus a currency [112].

Relationships (inferred, guess): Account 1-n Source, TeamMember, Annotation, Goal, Segment and Dashboard. Charge 0..1 Subscription, since charges can be one-off. Refund n-1 Charge, or standalone when one-off. Fee n-1 Charge. Goal n-1 Metric. MetricSnapshot is one row per account per day, summed across sources, with per-customer and per-plan breakouts.

Public API notes (shapes only):

- REST at https://api.baremetrics.com/v1. Bearer token: the API key from Settings, or an OAuth access token [110]. (high)
- Lists return 30 items by default and up to 200 with per_page; responses carry meta.pagination with has_more, page and per_page [111]. (high)
- Data paths sit under a source: /v1/{source_id}/customers and so on. Provider data is read-only; only data added through the API can be changed [113]. (high)
- Metrics paths have no source: Show Summary (start_date and end_date, inclusive), Show Metric (/v1/metrics/{metric} with start_date, end_date, compare_to default 30), Show Customers, Show Plan Breakout, Show Cohorts [126, 127, 128, 132, 149]. So filtering metrics by source through the API is unknown. (high for the endpoints; gap for the source filter)
- Rate limit: third parties claim 3,600 requests per hour per key, with HTTP 429 and Retry-After [141, 163]. No official page found. (medium)

Clone additions the owner needs (shapes from this repo, not from Baremetrics):

```
Sale            store (a Source), external_id (the store's order or event id; unique per store),
                occurred_at (event time, not receipt time), amount_cents, currency, fee_cents,
                refunded_cents, product, customer_email, channel
                evidence: owner rows in features.csv (one sales ledger; morning view by store and product;
                          channel for every sale); dedupe pattern merchant_billing (stripe_event_id UNIQUE,
                          amount_cents, currency) in supabase_shopify_multitenant.sql:11-100;
                          Baremetrics Charge (cents, currency, status) [139, 112]
                confidence: guess (new for the clone; no store API was read for these fields)

Lead            email, name, source, channel, product_interest, tags, status, captured_at
                evidence: core/email_capture.py:96-101 (email, name, source, topic, captured_at, metadata);
                          narai/api/routes/toodle.py:66-130 (kit_captures: email, source, product_interest,
                          tags, subscriber_id, sequence_id, status, error, created_at)
                confidence: high (repo shapes); guess (the merged table and its channel field)

Click           partner, ts, referrer, dest (the repo also stores the visitor ip)
                evidence: core/click_tracker.py:101-246
                confidence: high

Conversion      ts, partner, amount_usd, customer_email, source, external_id (dedupe key),
                attributed_click_ts, attributed_click_referrer
                evidence: core/click_tracker.py:101-246 (last click within 72 hours)
                confidence: high (repo shape); extending it to every store is new

AdSpend         date, ad account, campaign, spend, impressions, clicks
                evidence: Meta Insights [199] (not opened); core/budget_manager.py:373
                confidence: guess
```

Relationships (owner additions, guess): Source (store) 1-n Sale. A Sale matches at most one Conversion on external_id; the Stripe webhook already passes the Stripe event id as external_id (core/api.py:10225-10231). Leads and Sales match on email.

Mapping the core loop onto the model (guess): "which store" is Baremetrics' Source, which sits on every plan, customer, subscription and charge [113]. "Which channel" is a customer attribute such as a UTM source in Baremetrics [102]; in the clone it should be a field on each sale. "What made money yesterday" is the daily row of Show Summary [126]; in the clone it is a daily rollup per store, in integer cents, on the owner's calendar day. For the clone's sales ledger, reuse the repo's dedupe pattern: a unique external event id with amount_cents and currency (supabase_shopify_multitenant.sql:11-100).

## Feature matrix

See `features.csv`. Must: 22, should: 36, could: 57, skip: 8.

- Baremetrics features in the slice (original = yes, clone = no): 90 rows. Must 12, should 24, could 54.
- Left out on purpose (clone = skip): 8 rows. They are outside the slice, or cannot be cloned (Benchmarks).
- The owner's own needs that Baremetrics lacks (original = no): 25 rows. Must 10, should 12, could 3. replica-diff lists these as extras and does not score them.
- The 25 owner rows carry no screen or flow IDs, because the original has no such screens. /replica-architect should give the morning view, the store connectors and the CSV uploads their own IDs. Because replica-diff also leaves these rows out of its must-have gate (.claude/skills/replica-diff/SKILL.md:43-46), check the ten owner must rows, which hold the core loop, by hand or in /replica-test.
- Priorities follow the owner's core loop: one-off revenue by store first, subscriptions second, team and sharing last. This is judgement, not research.

What the original's pricing gates (read for which features it treats as upgrade reasons):

- Since Q3 2025, tiers are priced by the customer's ARR: Launch ($0 to $360K ARR), Growth ($360K to $3.6M), Scale ($3.6M+), with a 35% annual discount [167, 97, 176]. (high)
- Mid-2026 list prices: Launch $75/mo, or $49/mo billed annually; Growth $255/mo or $189/mo; Scale $1,152/mo or $749/mo [97, 171, 173, 166]. (high) Real annual savings: 34.7% Launch, 25.9% Growth, 35.0% Scale [171]. (medium)
- Launch: one integration and core subscription analytics. No Custom Dashboards, Unlimited Segmentation or Benchmarks. Its segmentation limit is not stated [97]. (high)
- Growth: two integrations, plus Custom Dashboards, Unlimited Segmentation and Benchmarks [97]. (high) Third-party copies also put Advanced Exports, Goal Tracking, and Slack and Intercom integrations here [171]. (medium)
- Scale: unlimited integrations [97]. (high) Third parties add Scenario Planning, Budget and Expense Tracking, the Analytics API and a dedicated support rep [171, 142]. (medium)
- Add-ons: Payment Recovery (Recover) and Cancellation Insights, +$129/mo each, both outside the slice [166]. (high) A build-your-own plan option was also seen [173, 179]. (medium)
- Before Q3 2025: a modular Metrics plan of about $250/mo plus add-ons [167]. A Feb 2024 listing showed four plans from $129 to $1,000 [172], and G2 lists the Metrics plan from $49/mo [160]. (medium)
- No permanent free plan as of Aug 2026 [175, 180]; a free trial [160], of 14 days according to one tracker [176]. (medium) Prices moved several times from Aug to Oct 2026: a free tier up to $180K ARR with Growth at $69 and Scale at $409 appeared in late September, then Growth and Scale went back to $189 and $749 in early October [168, 169, 170, 174, 177, 178]. Best reading for early Nov 2026: Launch $75/mo ($49 annual), Growth from $189/mo, Scale from $749/mo, free tier unconfirmed. Check the live page before quoting. (medium)
- You can connect as many data sources as you like [67, 81]; the tier caps probably count these connections (inference). Unclear whether the 1, 2 or unlimited "integrations" count covers only billing sources or also Slack, HubSpot and Intercom. (gap)

## Out of scope (cannot or should not be cloned)

- Recover: dunning, failed-charge recovery, and the at-risk-cards part of the Failed Charges page [19, 30].
- Cancellation Insights [69].
- Trial Insights and the trial metrics [106, 129].
- Forecast and Forecast+: scenario planning, budgets, and the QuickBooks and Xero data that feed them [37, 36].
- Benchmarks: built from other Baremetrics customers' data. Cannot be cloned [48].
- Customer augmentation: CSV upload, HubSpot sync, API attributes and the Clearbit enrichment category [47, 40, 101, 118, 130].
- Intercom two-way sync and inbox widget [41, 68]. The Stripe App, which runs inside Stripe's own dashboard [76].
- Anything Baremetrics owns: its name, logo, copy, screenshots, its customers' data, and its open-source date picker code [164].
- Native connectors for billing tools the owner does not use (Braintree, Recurly, Chargebee, App Store Connect, Google Play, Shopify Partners) stay in the matrix as could, not skip. They are in the slice; they just do not serve this owner.

## Size

Screens 22 (S00 to S21), flows 10 (F01 to F10), entities 23 (18 inferred from Baremetrics, 5 added for the owner).

Hard parts:

1. **Ten store connectors with uneven access.** Stripe, Gumroad, Shopify and Kit have official APIs with history, and BigCommerce likely does too (guess: vendor docs not opened; see Owner's stores). Whop, Payhip and Digistore24 are provisional. Stan Store and KDP are manual uploads. Each needs auth, backfill, webhooks or polling, and rate-limit handling.
2. **One correct ledger.** Webhooks can arrive more than once, and today's Stripe receiver sums retries again (core/api.py:10110-10281). Some store sales may also settle in the owner's Stripe (guess). Refunds, fees, currency conversion at each transaction date, and calendar days in the owner's time zone all have to be right.
3. **Attribution and metric rules.** A channel per sale across stores (tracked links, UTMs, referrers), plus Baremetrics' subscription rules (MRR normalisation, coupons, 100%-off, delinquency, rolling 30-day churn) over subscriptions from several stores.

Also: scheduled email, Slack and Telegram reports at the owner's morning, and the segment engine (stacked filters, compare up to 5). No offline or realtime need: a daily refresh fits the core loop (Baremetrics' own Insights lists refresh daily [43]), and webhooks keep sales near-live anyway (guess).

Size: **L (a quarter)** for the whole slice. The must rows alone (morning view, four connectors, ledger, daily email) look like **M (a few weeks)**. (guess) This is no promise of a perfect clone.

## Owner's stores

Today the scoreboard connects only Stripe (core/scoreboard.py:89-95). The owner's plan says sales from Kit, KDP, BigCommerce, Stan, DS24 and Shopify sit in silos, so they cannot tell what their Meta spend generated (marketing/GLOBAL_PLAN.md:160). (high)

The vendor docs below were **not opened** this session. Vendor facts come from the researcher's prior knowledge or from this repo. Only repo facts are rated high.

| store | API | auth | difficulty | in Baremetrics? | evidence |
| --- | --- | --- | --- | --- | --- |
| Stripe | REST API and webhooks. List endpoints filter on created and reach full history. /v1/balance_transactions gives amount, fee and net per money movement, refunds included. Do not backfill from /v1/events (30 days only). | secret key as Bearer; use a restricted read-only key | easy | yes, native ("Connect with Stripe") [32] | repo pulls charges and active subscriptions with the official SDK (core/revenue.py:117, 133) (high); docs [181 to 186] not opened (guess) |
| Gumroad | REST API v2: /v2/sales with after and before dates, products, subscribers; resource-subscription webhooks for sale, refund, dispute, cancellation and subscription changes | personal access token from an OAuth app; view_sales scope | easy | no native connector found (guess) | client exists, unused (core/gumroad_client.py:7-11, 119-137) (high); docs [187] not opened (guess) |
| Shopify (store) | Admin GraphQL API (REST is legacy); order and refund webhooks; bulk export for history | app installed on the one store; Admin API token in X-Shopify-Access-Token | easy, once read_all_orders is added (without it, only the last 60 days of orders) | no: its Shopify connector reads Partner app billing, not store orders [33] | the app lacks read_all_orders (shopify.app.toml:29) (high); docs [188 to 193] not opened (guess) |
| Kit (leads) | REST API v4: subscribers by creation date, form subscribers, growth stats, purchases, webhooks | API key in X-Kit-Api-Key | easy | no native connector found (guess) | v4 client (core/kit.py:48, 76) (high); docs [194] not opened (guess) |
| Stan Store | no sales API or webhook known | web login only, per the repo | manual upload only (provisional) | no (guess) | core/scoreboard.py:94; a Playwright login session was committed before (suprema/autorepair/scanners/committed_runtime_state.py:6) (medium) |
| Digistore24 | believed: a vendor API with read-only keys to list purchases and transactions, plus IPN notifications for payments, refunds, chargebacks and rebills | API key (unverified) | medium (provisional) | no (guess) | no code in the repo (core/scoreboard.py:93) (high); no doc URL verified (guess) |
| BigCommerce | REST: Orders v2 with date filters, v3 refunds, order webhooks; orders carry channel_id and order_source | store-level API account token in X-Auth-Token, with the store hash | easy (guess) | no (guess) | env names only, no client (.env.example:99-117; core/scoreboard.py:95) (high); docs [195 to 197] not opened (guess) |
| Whop | REST; the repo uses v5; payments, receipts and memberships; payment and membership webhooks (unverified) | company API key as Bearer; OAuth for apps | medium (provisional) | no (guess) | core/whop_client.py (high); docs [198] not opened (guess) |
| Payhip | sale webhooks; a small REST API (license keys, coupons); no known endpoint lists past sales | Bearer API key for REST; webhook authenticity check unknown | medium (provisional) | no (guess) | receiver and REST base (core/api.py:12205-12326) (high); the rest is a guess |
| Amazon KDP | no public sales or royalties API known; report downloads in KDP Reports (.xlsx assumed) | none: the owner downloads the files | manual upload only | no (guess) | browser adapter (narai/godmode/adapters/amazon_kdp.py:10-15) (medium); Amazon Conditions of Use [203] not opened (guess) |
| Meta Ads (spend, not a store) | Marketing API Insights: spend, impressions, clicks, actions; one row per day | OAuth token with ads_read; a system-user token for unattended jobs | medium | no | repo calls insights (core/budget_manager.py:373) and pins v19.0 (core/meta_ads.py:47); docs [199 to 202] not opened (guess) |
| Impact.com (affiliate, extra) | Publisher API: actions (earnings), campaigns, ads, invoices | account SID and API password | already wired | no | core/impact.py:156-215 (high) |
| SiteBoost (outreach, internal) | local state file: places scanned, emails sent | none | already wired | no | core/siteboost_state.py; core/scoreboard.py:44-59 (high) |

Notes per store:

- **Stripe.** Rate limits are believed to be about 100 reads per second in live mode, far above a morning sync [184]. (guess) Whether Payment Links and Checkout record UTM parameters is not confirmed. Risk: stores that pay out through the owner's own Stripe account create charges there too. This is believed for Payhip, possible for Stan Store, and true for BigCommerce if Stripe is its gateway. Count each sale once. The charge's "application" field may name the platform [186]. (guess)
- **Gumroad.** Sales are believed to carry refund and chargeback flags and a referrer usable for channel. The repo pages with page=N; current docs may use page_key instead. No rate limit is published, so throttle and handle HTTP 429. (guess)
- **Shopify.** Orders are believed to record the sales channel and a customer journey summary with referrer and UTM parameters; check the field names [192]. GraphQL limits are cost-based, and bulk operations avoid them for exports [190, 191]. Unverified: in 2026, new single-store apps may be made in the Dev Dashboard, not the store admin. (guess)
- **Kit.** Leads per day from /v4/subscribers (created_after, created_before), per form from /v4/forms/{id}/subscribers, and new, cancelled and net subscribers from /v4/account/growth_stats [194]. (guess) The API-key limit is believed to be about 120 requests per 60 seconds. The repo self-limits to 4 per second, which is 240 per minute and would exceed it in a sustained loop (core/kit.py:49). (guess) The comment on that same line says Kit's documented ceiling is higher, so the two disagree; check [194] before relying on either.
- **Stan Store.** Plan a CSV upload by the owner until an export, a Zapier trigger, a webhook or a Stripe-settlement route is confirmed. Do not carry the stored-cookie browser login into the clone. Stan's terms on automated access were not reviewed.
- **Digistore24.** Everything here is unverified. Read the official docs first.
- **BigCommerce.** Rate limits are a quota per 30-second window, reported in X-Rate-Limit headers; numbers per plan need checking [195]. (guess)
- **Whop.** Whop has changed API versions more than once. Confirm v5 still works before building on the repo client [198]. (guess)
- **Payhip.** New sales arrive by webhook, forward only; history would come from a dashboard CSV export. (guess) The repo handler guesses field names (event or type, price or amount, buyer_email or email, purchase_key or id) (core/api.py:12303-12326). (high)
- **Amazon KDP.** Believed reports: Dashboard, Orders, KENP Read, Royalties, Payments, Promotions, Pre-orders and Prior Months' Royalties. (guess) Yesterday's figures are estimates, and royalties are finalised later. Show KDP numbers as estimated, with the time of the last upload. Amazon's Conditions of Use exclude robots and data-extraction tools [203]; together with the clean-room rule of never logging in, the clone imports the files the owner downloads.
- **Meta Ads.** Use Meta for spend. Use store-side UTMs and referrers for "which channel", because Meta's own attributed conversions will not match store sales. Insights reach back about 37 months, and v19.0 is probably past end of life [199, 201]. (guess)

## Reuse from this repo

A static read. Nothing was run against live accounts, and no secret values were read (only variable names in .env.example). Production runs `uvicorn core.api:app` on Railway (railway.json:7).

Reuse, with fixes:

1. **Metric contract and status UI.** `{value, connected, source, note}`, with value set to None when a source is not connected, so "not measured" never shows as a fake 0 (core/scoreboard.py:18-20). A card grid with a "live" or "not connected" pill on each card (frontend/admin/scoreboard.html:59-107). (high)
2. **Webhook receivers as ingestion.** Stripe (core/api.py:10110-10281), Payhip (core/api.py:12204-12466), Shopify (core/api.py:14050-14170) and Kit (narai/api/routes/toodle.py:372-412). Make them write to one ledger, dedupe on the store's event id, verify signatures, and store the event time, not the receipt time. (high)
3. **Pull clients for backfill.** Gumroad (core/gumroad_client.py, unused today), Shopify (core/shopify_client.py, Admin REST 2026-04), Kit v4 (core/kit.py) and Whop (core/whop_client.py, unused today). Add date filters, pagination, a Kit subscriber list and Whop payments. (high)
4. **Channel attribution.** /go/{partner} logs a click and redirects with utm_source, utm_medium, utm_campaign and utm_content. record_conversion() credits the last click within 72 hours and dedupes on external_id (core/click_tracker.py:44-56, 101-246). Today only the Stripe webhook calls it. (high)
5. **Morning report plumbing.** APScheduler cron with a time zone (NARAI_BRIEFING_CRON defaults to weekdays at 07:00; NARAI_BRIEFING_TZ defaults to America/New_York) (narai/integrations/scheduler.py:46-87). A yesterday-vs-day-before KPI line (narai/integrations/briefing.py). Senders for Telegram, Slack (incoming webhook, Block Kit) and SMTP email with sections (core/output_automation.py:68-243). Fix: the KPI buckets by UTC date, it runs on weekdays only by default, and it skips itself when TELEGRAM_BOT_TOKEN is unset. (high)
6. **Schema patterns.** merchants (Fernet-encrypted tokens, scopes, last_synced_at), merchant_events, and merchant_billing (stripe_event_id UNIQUE for dedupe, amount_cents, currency, status) (supabase_shopify_multitenant.sql:11-100; narai/core/shopify_mt/crypto.py). Conventions from supabase_schema.sql: uuid keys, timestamptz, owner RLS, service-role writes from the backend. (high)
7. **A ready consumer.** revenue_gate.set_metrics_provider() can take the clone's daily totals (Kit subscribers, 7-day clicks, 7-day revenue). Today it is never called, so the gate runs on env-var zeros (core/revenue_gate.py:107-169). (high)
8. **A brief-builder pattern.** A read-only daily brief with a composed headline (backend/app/services/briefing/daily_brief.py:1-87). (high)
9. **Tests worth keeping.** tests/test_scoreboard.py (a real zero vs "not connected"), tests/test_scoreboard_mount.py (page served, API auth enforced), money_center/tests/test_registry.py. (high)

Fix before trusting the numbers:

- RevenueEngine sums gross charges (it ignores amount_refunded), ignores currency, computes MRR from unit_amount only, and uses rolling 24-hour and 7-day windows instead of calendar days (core/revenue.py:117-141, 198-206, 239-259). (high)
- Scoreboard trials and churn never fill: RevenueEngine never returns those keys, and the test mocks them in (core/revenue.py:151-159; tests/test_scoreboard.py). (high) "users" probably reads 0 (core/revenue.py:133, 158). (guess)
- Scoreboard "leads" are SiteBoost places scanned, and "conversion" is Stripe subscriptions divided by places scanned (core/scoreboard.py:44-59). (high)
- /api/money/summary adds an estimated KDP "revenue" (published genres x $2.99 x 70% / 30) into today's total. Its leads read the wrong keys, and its affiliate clicks import a missing function, so both always show 0 (core/api.py:10301-10309, 10329-10334). (high)
- The Stripe webhook appends to a JSON file capped at 500 entries with no event_id dedupe, so retries are summed again (core/api.py:10110-10281). (high)
- Shopify get_orders_summary(days=30) ignores days and sums the last 250 orders of any status, which /api/sa/store then labels "total_revenue_today" (core/shopify_client.py:515-541). The orders/paid webhook records no amount (core/api.py:14050-14170). (high)
- Two manual revenue ledgers never reconcile (core/api.py:10373-10388, 11178-11182). Payhip sales are in no total at all (core/api.py:12204-12466). (high)
- The 07:00 Telegram summary counts clicks with the wrong key, so "Affiliate Clicks Today" is always 0 (core/api.py:7553-7590). The 08:00 revenue report only runs from main.py's launch(), never under Railway (core/api.py:13800-13819; main.py:179). (high)
- conversion_analytics gives each event a fixed default value (purchase 10.0, subscription 5.0), so its rankings are not real revenue (core/conversion_analytics.py:29-79). (high)
- Data files under data/ are gitignored, and only Payhip uses RAILWAY_VOLUME_PATH, so the others may reset on each deploy (.gitignore:42-45). (medium)
- Meta Graph v19.0 is pinned in several places (core/meta_ads.py:47; core/budget_manager.py:315, 373, 394; core/performance.py:226, 251). It has probably expired. (guess) When launched locally, several loops call run_pending() on the same scheduler, so a job could run twice (core/api.py:13678-13840). (guess)

Security: the recon found security issues in the current admin pages, API auth, webhook receivers and the
Money Center server. Because this repository is public, they were reported to the owner privately and are not
listed here. Do not reuse the existing admin page or Money Center server patterns; reuse the money_center/
registry idea only.

Build new:

- One sales ledger and one leads table, with daily rollups in the owner's time zone. (inference from the fixes above)
- Connectors for the stores with no sales code at all: Digistore24, BigCommerce, Stan Store, KDP, and Whop payments (core/scoreboard.py:93-95; core/whop_client.py; KDP has only a browser adapter, narai/godmode/adapters/amazon_kdp.py:10-15). (high)
- Do not treat money_center/ as revenue data: it holds estimates, total_revenue_usd is 0 everywhere, and nothing updates it (money_center/registry.py). (high)

## Limits of this recon

- **WebFetch was blocked** in this environment; baremetrics.com and most sites did not resolve. Screens, states and flows come from indexed help, changelog, blog and API-doc pages, seen as search-result titles, URLs and summaries. No help article was read in full.
- **No screenshots were captured.** replica/screens/ is empty (the folder does not exist yet). Layouts, the default dashboard and the visual design are unknown.
- **Before /replica-design**, the owner should allow baremetrics.com and help.baremetrics.com in this environment's network settings, or capture screenshots from public pages (the marketing site, help articles, the public demo [103]) into replica/screens/.
- **The search budget ran out** (200 WebSearch calls per turn, shared by all research agents). The connectors research could not search at all, so every vendor fact about the owner's stores comes from prior knowledge or this repo. A critic pass on 2026-11-02 re-checked about 40 repo citations (two line references corrected, the rest held) but could not re-check any web claim, for the same reason.
- **Not checked:** native support for Gumroad, Paddle, Lemon Squeezy, Kit, Stan Store, Digistore24, BigCommerce, Whop, Payhip or KDP (absence is inferred); the baremetrics.com/paypal page; full API response schemas; segment operators; official rate limits; outbound webhooks (only Truto lists names [153]); currency handling for tiered plans (https://changelog.baremetrics.com/?label=9931); the indexes https://developers.baremetrics.com/llms.txt [109] and help.baremetrics.com/llms.txt.
- **Not documented anywhere found:** empty, loading and error states, the default Control Center layout, the Metrics menu order, date presets, interval options, tooltips, directory columns, the current profile layout, the summary email's content, send time and time zone, and mobile behaviour.
- **Pricing is unsettled.** Prices changed several times from Aug to Oct 2026 and the trackers disagree. Check the live page.
- **Terms were not read.** Neither Baremetrics' terms (on building a competing product) nor the API terms of the eleven vendors above. This run used public sources only and never logged in.
- **The repo read was static.** Production env vars, whether Railway has a volume, and which Stripe event types the webhook receives are unknown. core/api.py (about 15k lines) and dashboard/index.html (about 19k lines) were read in parts.
