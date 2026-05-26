# Toodle — KDP Nurture Sequence (Kit / ConvertKit)

**Sequence name in Kit:** match this exactly to `KIT_SEQUENCE_KDP_NAME` in `.env` (default: `KDP Launch`)
**Trigger:** subscriber tagged `product_interest:kdp` (Capture Agent applies this automatically — see `narai/api/routes/toodle.py`)
**Lead magnet:** Free AI Entrepreneur Blueprint
**Goal of sequence:** deliver value → build trust → route to KDP book purchase
**Cadence:** Email 1 immediate, then Day 1, Day 3, Day 5, Day 7

> Fill the brackets before pasting: `[BOOK TITLE]`, `[AMAZON LINK]`, `https://wheellsverse-bots.pages.dev/blueprint.pdf?utm_source=email&utm_medium=nurture&utm_campaign=kdp_seq`.
> Every CTA link should carry a UTM: `?utm_source=email&utm_medium=nurture&utm_campaign=kdp_seq`
> Compliance: never promise guaranteed income. Sell the system and the skill, not a number.

---

## EMAIL 1 — Immediate (deliver the magnet)

**SUBJECT**

Here's your AI Entrepreneur Blueprint

**BODY**

You're in.

Here's the blueprint I promised → https://wheellsverse-bots.pages.dev/blueprint.pdf?utm_source=email&utm_medium=nurture&utm_campaign=kdp_seq

Open it now while it's fresh. It's short on purpose — most "guides" are 90 pages of filler. This one is the actual steps, in order.

Quick context on who's sending this: I'm J.K. Blaze. I build AI systems that turn ideas into real products — fast. The blueprint is the same process I use myself.

Over the next few days I'll send you the parts that don't fit in a PDF — the mistakes that stall most people, and how to skip them.

Read the blueprint first. Then watch your inbox.

— J.K.

---

## EMAIL 2 — Day 1 (the why / the shift)

**SUBJECT**

The reason most people never start

**BODY**

Did you open the blueprint yet? If not, here it is again → https://wheellsverse-bots.pages.dev/blueprint.pdf?utm_source=email&utm_medium=nurture&utm_campaign=kdp_seq

Here's the thing nobody tells you.

Most people don't fail at building something because they're not smart enough. They fail because they wait. They wait to feel ready. They wait for the perfect idea. They wait until they "know enough."

You don't need more knowledge. You need a system that moves while you learn.

That's the whole shift. Stop collecting information. Start running a process.

The blueprint gives you the process. Tomorrow I'll show you the first place people get stuck — and it's not where you'd expect.

— J.K.

---

## EMAIL 3 — Day 3 (teach something real)

**SUBJECT**

The mistake that kills 90% of first attempts

**BODY**

Most beginners build the wrong thing first.

They spend weeks on the logo. The name. The perfect landing page. The "brand." All the stuff that feels like progress but moves nothing.

Here's the fix: build the smallest version that someone can actually pay for. Nothing else. Not the polish — the offer.

One product. One page. One way to buy. Then you put it in front of real people and watch what happens.

That's it. That's the unlock. Everything else is decoration you add after the thing works.

I go deep on this — the exact step-by-step — in [BOOK TITLE]. If the blueprint got you thinking, the book is the full map.

→ [AMAZON LINK]

Either way, do this today: pick the one thing you could sell. Just name it. That's the start.

— J.K.

---

## EMAIL 4 — Day 5 (proof + soft pitch)

**SUBJECT**

You don't need a big audience to start

**BODY**

A myth worth killing: "I need followers first."

You don't. Your first customers don't care how big you are. They care whether you solve their problem.

Small and focused beats big and vague every time. A tiny audience that trusts you is worth more than thousands who scroll past.

The blueprint shows you the structure. [BOOK TITLE] shows you how to fill it in — how to find the people, write the offer, and get the first yes without a following.

It's a few dollars and a couple hours of reading. The cheapest mistake-insurance you'll ever buy.

→ [AMAZON LINK]

Tomorrow: the last email, and the one decision that separates the people who do this from the people who keep reading about it.

— J.K.

---

## EMAIL 5 — Day 7 (direct offer + close)

**SUBJECT**

The difference between knowing and doing

**BODY**

You've had the blueprint for a week now.

Here's the honest truth: a blueprint only works if you run it. The people who win aren't the ones who read the most. They're the ones who picked one step and actually moved.

So here's your move. If you're serious about building something with AI instead of just reading about it, get the full system:

→ [BOOK TITLE] — [AMAZON LINK]

It's the complete process. Every step the blueprint summarized, fully laid out, with nothing skipped.

And if now's not the time — no pressure. Keep the blueprint. Run it when you're ready. I'll still be here.

But if you've been waiting for a sign to start: this is it.

— J.K.

P.S. Got a question before you buy? Just reply to this email. It comes straight to me.

---

## After you paste into Kit

1. Create a sequence named to match `KIT_SEQUENCE_KDP_NAME` (default `KDP Launch`).
2. Add 5 emails, paste subject + body for each.
3. Set delays: Email 1 = immediate, then +1 day, +2 days, +2 days, +2 days.
4. Fill all `[BRACKETS]` and add UTMs to every link.
5. Boot the app with `KIT_DRY_RUN=true` → POST a test capture → confirm the resolver prints this sequence's real ID via `GET /toodle/status`.
6. Only then set `KIT_DRY_RUN=false`.

## Alignment with code

| Where | What |
|---|---|
| `narai/api/routes/toodle.py` | `DEFAULT_SEQUENCE_NAMES["kdp"]` reads `KIT_SEQUENCE_KDP_NAME` from env |
| `.env.example` | `KIT_SEQUENCE_KDP_NAME=KDP Launch` |
| Capture flow | `product_interest:"kdp"` in the POST body → resolver looks up the live sequence ID by name → `add_subscriber_to_sequence` |
| Sanity check | `GET /toodle/status` (auth-protected) returns the resolved tag/sequence maps |

If `GET /toodle/status` shows `sequences` map missing a `"kdp launch"` key (lowercased for matching), the sequence either doesn't exist in Kit yet or its name doesn't match `KIT_SEQUENCE_KDP_NAME`. Fix one or the other — that's the only failure mode.

## Productization note

This file is also the deliverable artifact for the future Toodle SaaS template: a paying customer who buys the "KDP Launch" playbook receives this exact sequence as their starting point and edits the brackets. The product_interest → sequence_name mapping in `DEFAULT_SEQUENCE_NAMES` is the extension point — adding a new product is "drop a new playbook file here + add one env var + one dict entry."
