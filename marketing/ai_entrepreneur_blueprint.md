---
title: The AI Entrepreneur Blueprint
subtitle: The Stack & The Method
version: 1.0
author: J.K. Blaze
brand: WheellsVerse
intended_pdf_path: data/store/digital/ai_entrepreneur_blueprint.pdf
hosted_at: https://wheellsverse-bots.pages.dev/blueprint   # set CTA_URL to match
length_target: 1 page (≈350 words body)
status: SOURCE — convert to PDF before flipping KIT_DRY_RUN=false
---

# The AI Entrepreneur Blueprint

**The Stack & The Method**

---

## THE STACK

The four tools I actually use. That's it. Not 50 "must-have" tools. Four.

1. **The Brain** — Claude or GPT-4o. Writing, ideas, code, analysis. Pick one, learn it deeply. Both work. Switching constantly is a tax most beginners pay without realizing.
2. **The Visuals** — Higgsfield. Covers, ads, social images, short video. One subscription replaces a freelancer for everything you'll need in your first six months.
3. **The Audience** — Kit (formerly ConvertKit). The only place your audience lives that you actually own. Email list, sequences, tagging — all in one. → https://convertkit.com?lmref=your_ref
4. **The Checkout** — Gumroad or Stripe. Take payment in 15 minutes. You don't need a store. You need a way to be paid.

That's the entire stack. If a tool isn't in this list, you don't need it yet.

---

## THE METHOD

**Step 1 — Pick the one thing to sell.**

Not "what could I build." Pick ONE thing. A short book. A checklist. A Notion template. A 30-minute consult. Specific enough to name in one sentence. If you can't say it in one sentence, you don't have an offer yet — you have an idea.

**Step 2 — Use the stack to build it. Today.**

The Brain writes it. The Visuals dress it. Kit holds the audience. Gumroad takes the money. The whole thing should take an afternoon, not a quarter. Polish is what you do *after* someone pays.

**Step 3 — Put it in front of 10 humans.**

Not a thousand. Ten. Friends, your email list, one community you actually belong to. Watch what happens. Track who buys, who doesn't, who asks questions. Real signal beats imagined demand every single time.

---

## THAT'S IT.

The trap most people fall into: they think they need to learn more before they start. Wrong. You need a system that *moves* while you learn. The stack moves you. The method directs you. Everything else is decoration you add after the thing works.

Run it.

— **J.K. Blaze**
*WheellsVerse*

**P.S.** Tomorrow's email is about the place 90% of people get stuck. It's not where you'd expect.

---

<!-- ============================================================
     PRODUCTION NOTES — strip these before the PDF goes public
     ============================================================ -->

## Cover brief (Higgsfield)

- **Aesthetic:** dark futuristic tech, single bold cyan accent. Match the wheellsverse-bots.pages.dev landing page palette ("One system. One founder.")
- **Typography-first:** the title carries the design. No stock photos of "a person holding a laptop." No handshake imagery. No graphs going up-and-to-the-right.
- **Optional visual element:** four small geometric icons in a row (brain / image / envelope / dollar) representing the stack.
- **Spec:** 8.5×11 portrait, 300dpi, RGB. Single front cover only — body is the inside page.

## Real URLs to fill before publishing

| Token in body | What to paste |
|---|---|
| `[JOIN-KIT-LINK]` | Your ConvertKit affiliate URL — already in `.env` as `AFFILIATE_CONVERTKIT_URL`. Default in `.env.example`: `https://convertkit.com?lmref=your_ref` |
| The four tool names | Add affiliate links ONLY where you actually have one. Don't fake any. For Claude / GPT-4o / Stripe / Gumroad: leave as plain text unless you have a real referral set up. Honesty > a few extra clicks. |

## Where this goes once the PDF exists

1. Convert this `.md` to `data/store/digital/ai_entrepreneur_blueprint.pdf` (whatever toolchain produced `top_5_ai_tools_2026.pdf` — pandoc + weasyprint or your existing build script).
2. Upload PDF to: Cloudflare R2 / GitHub Releases / Gumroad (gated download) — pick one based on whether you want gating or open.
3. Set `CTA_URL=<final PDF URL>` in `.env`.
4. **Also fix:** [core/lead_capture.py:36](../core/lead_capture.py#L36) currently defaults to a dead Railway URL — change the hardcoded fallback or make it raise if `CTA_URL` env is missing.
5. Add a `/blueprint` route on the Cloudflare Pages site that either redirects to the PDF or serves a gated form.
6. Update both `[BLUEPRINT LINK]` brackets in:
   - [marketing/kdp_nurture_sequence.md](kdp_nurture_sequence.md) — all 5 emails
   - [marketing/welcome_sequence.md](welcome_sequence.md) — both emails

Once those steps are done, run the smoke test:

```bash
/Users/jhonwheeler/wheellsverse_venv/bin/python -m narai.api.main &
curl -s http://127.0.0.1:5051/toodle/status | jq .   # auth-protected; expects token
# confirm the resolver sees `"kdp launch"` and `"welcome"` in resolver.sequences
# then flip KIT_DRY_RUN=false and POST a real capture from your own email
```

If `/toodle/status` resolves the sequence IDs AND the blueprint URL serves a real PDF, the pipe is live and the $5/day Meta ad has somewhere to land.
