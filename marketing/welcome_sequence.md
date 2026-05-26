# Toodle — Welcome Fallback Sequence (Kit / ConvertKit)

**Sequence name in Kit:** match `KIT_SEQUENCE_WELCOME_NAME` in `.env` (default: `Welcome`)
**Trigger:** subscriber captured with NO `product_interest` set (Capture Agent fallback route)
**Purpose:** no lead falls into nothing. Deliver value, then route to the KDP sequence intent.
**Cadence:** Email 1 immediate, Email 2 at Day 2.

> This is a SHORT safety-net sequence, not a full funnel. Its job: don't lose the lead, then warm them toward the KDP arc.
> Fill brackets: `https://wheellsverse-bots.pages.dev/blueprint.pdf?utm_source=email&utm_medium=welcome&utm_campaign=welcome_seq`. UTM every link: `?utm_source=email&utm_medium=welcome&utm_campaign=welcome_seq`
> Compliance: value first, no income promises.

---

## EMAIL 1 — Immediate

**SUBJECT**

You're in — here's where to start

**BODY**

Welcome.

You signed up, so here's something useful right away: the AI Entrepreneur Blueprint → https://wheellsverse-bots.pages.dev/blueprint.pdf?utm_source=email&utm_medium=welcome&utm_campaign=welcome_seq

It's the short, no-filler version of how I turn ideas into real products using AI. Read it first.

I'm J.K. Blaze — I build AI systems for a living, and I share the parts that actually work. Over the next few days I'll send you the steps that don't fit in a PDF.

Start with the blueprint. More soon.

— J.K.

---

## EMAIL 2 — Day 2

**SUBJECT**

One question before I send more

**BODY**

Quick one.

What are you actually trying to build? Most people who grab the blueprint fall into one of two camps:

1. They want to create something — a book, a product, a digital offer — and sell it.
2. They want better signals and tools to make smarter money decisions.

Hit reply and tell me which. One word is fine. It tells me exactly what to send you next so I'm not filling your inbox with stuff that doesn't fit.

And if you haven't opened the blueprint yet, here it is once more → https://wheellsverse-bots.pages.dev/blueprint.pdf?utm_source=email&utm_medium=welcome&utm_campaign=welcome_seq

— J.K.

---

## After you paste into Kit

1. Create a sequence named to match `KIT_SEQUENCE_WELCOME_NAME` (default `Welcome`).
2. Add 2 emails, paste subject + body.
3. Delays: Email 1 immediate, Email 2 +2 days.
4. Fill `https://wheellsverse-bots.pages.dev/blueprint.pdf?utm_source=email&utm_medium=welcome&utm_campaign=welcome_seq`, add UTMs.
5. Optional: when someone replies "build" or "create," tag them `product_interest:kdp` so they enter the KDP arc. This is the manual version of the routing the Capture Agent does automatically.

## Alignment with code

| Where | What |
|---|---|
| `narai/api/routes/toodle.py` | `DEFAULT_SEQUENCE_NAMES["default"]` reads `KIT_SEQUENCE_WELCOME_NAME` from env |
| `.env.example` | `KIT_SEQUENCE_WELCOME_NAME=Welcome` |
| Capture flow | capture with empty/unknown `product_interest` → resolver looks up `"welcome"` (case-insensitive) → `add_subscriber_to_sequence` |

This sequence exists so a capture with no product_interest never dead-ends. It's hygiene, not a growth engine.
