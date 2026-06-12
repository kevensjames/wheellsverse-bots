# 28-Day Email Warmup Tracker — hello.wheellsverse.com

Tick off each day as Instantly handles the warmup automatically.
Your only job: confirm warmup is running, check Postmaster Tools daily.

> **Rule of thumb**: NEVER send cold mail manually during this 28 days. The
> warmup-pool emails count; your real cold sends do not. Send your first cold
> mail on **Day 29** at the earliest.

---

## Pre-flight (Day 0 — same day Instantly is set up)

- [ ] `hello.wheellsverse.com` DNS shows 5/5 ✓ on `python3 scripts/verify_dns.py`
- [ ] Google Workspace mailbox `jay@hello.wheellsverse.com` works (send/receive test)
- [ ] Instantly mailbox connected — green "Connected" status
- [ ] Warmup toggle is ON in Instantly → Email Accounts → Settings
- [ ] Warmup volume set to **30/day at start, +5/day automatic ramp** (default)
- [ ] Reply rate target: **20-30%** (Instantly handles automatically)
- [ ] Postmaster Tools enrollment started at [postmaster.google.com](https://postmaster.google.com) (data takes 7-14 days to appear)

---

## Week 1: Reputation Foundation (Days 1-7)

> Volume: 5-15 warmup emails/day. NO real cold mail.

| Day | Date | Instantly warmup running? | Postmaster Tools spam rate | Notes |
|---|---|---|---|---|
| 1 | ___ | [ ] | (no data yet) |   |
| 2 | ___ | [ ] | (no data yet) |   |
| 3 | ___ | [ ] | (no data yet) |   |
| 4 | ___ | [ ] | (no data yet) |   |
| 5 | ___ | [ ] | (no data yet) |   |
| 6 | ___ | [ ] | (no data yet) |   |
| 7 | ___ | [ ] | first data should appear |   |

**Week 1 stop conditions** — if any of these, pause warmup, fix, restart:
- Mailbox can't send at all (DNS/SMTP misconfig)
- Bounced emails > 5% (DKIM/SPF issue)
- Instantly shows "Domain reputation low" warning

---

## Week 2: Volume Ramp (Days 8-14)

> Volume: 15-30 warmup emails/day. STILL no real cold mail.

| Day | Date | Warmup ok? | Spam rate | Domain reputation |
|---|---|---|---|---|
| 8  | ___ | [ ] | ___ % | ___ |
| 9  | ___ | [ ] | ___ % | ___ |
| 10 | ___ | [ ] | ___ % | ___ |
| 11 | ___ | [ ] | ___ % | ___ |
| 12 | ___ | [ ] | ___ % | ___ |
| 13 | ___ | [ ] | ___ % | ___ |
| 14 | ___ | [ ] | ___ % | ___ |

**Week 2 stop conditions**:
- Spam rate > 0.1% on any day
- Domain reputation drops below "Medium"
- Mailbox put on Instantly's "warning" list

If any trigger: pause warmup 3 days, then restart at 50% volume.

---

## Week 3: Live-Send Preparation (Days 15-21)

> Volume: 30-50 warmup emails/day. STILL no real cold mail.

| Day | Date | Warmup ok? | Spam rate | Domain reputation |
|---|---|---|---|---|
| 15 | ___ | [ ] | ___ % | ___ |
| 16 | ___ | [ ] | ___ % | ___ |
| 17 | ___ | [ ] | ___ % | ___ |
| 18 | ___ | [ ] | ___ % | ___ |
| 19 | ___ | [ ] | ___ % | ___ |
| 20 | ___ | [ ] | ___ % | ___ |
| 21 | ___ | [ ] | ___ % | ___ |

**Tasks during Week 3 (use the calm time)**:
- [ ] Run `python3 scripts/local_prospect_run.py --scan --location "Boston, MA" --limit 50 --live` (real Google Places call)
- [ ] Inspect 5-10 sample previews in `data/launches/siteboost/runs/<date>/03-previews/` — do they look like real sites?
- [ ] Read [SALES-PLAYBOOK.md](SALES-PLAYBOOK.md) cover to cover (3rd time — internalize it)
- [ ] Test Stripe payment flow with a $1 test product (Stripe test mode)
- [ ] Verify intake form posts data correctly

---

## Week 4: Final Ramp + First Live Send (Days 22-28)

> Volume: 50-75 warmup emails/day. Days 22-27 still warmup-only. **Day 28: first real send (small).**

| Day | Date | Warmup ok? | Spam rate | Domain reputation | Real cold sends |
|---|---|---|---|---|---|
| 22 | ___ | [ ] | ___ % | ___ | 0 |
| 23 | ___ | [ ] | ___ % | ___ | 0 |
| 24 | ___ | [ ] | ___ % | ___ | 0 |
| 25 | ___ | [ ] | ___ % | ___ | 0 |
| 26 | ___ | [ ] | ___ % | ___ | 0 |
| 27 | ___ | [ ] | ___ % | ___ | 0 |
| 28 | ___ | [ ] | ___ % | ___ | **10** ← first real cold sends |

### Day 28 — First Real Send (10 emails)

- [ ] All Week 4 metrics green (spam rate < 0.1%, reputation Medium+)
- [ ] Pick 10 best prospects from your last `scripts/local_prospect_run.py --all` dry-run
- [ ] Manually review each of the 10 emails before send (subject lines, preview links, business names spelled right)
- [ ] Send via Instantly (NOT directly via Gmail — keep all sends through Instantly's deliverability pipeline)
- [ ] Track replies for 48 hours
- [ ] Expected: 0-1 replies. If 0, that's normal at this volume.

---

## Day 29+: Scaling Cadence

| Week | Daily real cold sends | Daily warmup (keep running) |
|---|---|---|
| Week 5 | 25/day | 30/day |
| Week 6 | 50/day | 30/day |
| Week 7 | 75/day | 25/day |
| Week 8+ | 100/day per inbox MAX | 20/day per inbox forever |

**Hard cap: 100 cold/day per inbox** for the first 90 days. Use multiple inboxes
(`jay@`, `hello@`, `team@`) to spread volume if you want to scale faster.

---

## Red Flags — pause immediately and investigate

| Signal | Action |
|---|---|
| Postmaster Tools spam rate > 0.3% | Pause sending 7 days. Check copy + list quality. |
| "Domain reputation: Low" in Postmaster Tools | Pause 14 days. Restart warmup at 50% volume. |
| Bounce rate > 3% on real sends | Pause. Run `siteboost_state.block_email()` on bouncing addresses. |
| Multiple replies marking as spam | Pause. Review copy — likely tone-deaf or too pushy. |
| Receiving "abuse@" complaints | Stop sending. Audit copy + consider new domain. |

---

## Quick reference

**Daily 60-second check** (post-coffee routine):
1. Open [Instantly dashboard](https://app.instantly.ai)
2. Check warmup status → should say "Healthy"
3. Open [Postmaster Tools](https://postmaster.google.com/u/0/managedomains)
4. Confirm spam rate < 0.1%
5. Tick today's row above

**Weekly 5-minute check** (every Monday):
1. Pull last week's reply stats from Instantly
2. Update README-MORNING.md current status section
3. Run `python3 scripts/siteboost_status.py` for full system snapshot
