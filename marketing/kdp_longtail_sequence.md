# Toodle — KDP Long-Tail Sequence (Non-Buyers)

**Sequence name in Kit:** match `KIT_SEQUENCE_KDP_LONGTAIL_NAME` in `.env` (default: `KDP Long-Tail`)
**Trigger:** subscriber finished the main KDP arc (`kdp_nurture_sequence.md`) and did NOT buy. Tag them `kdp:nonbuyer` at the end of Day 7 in Kit's automation rules, then trigger this sequence.
**Purpose:** acquisition cost was paid. Don't let a non-buyer drift. Three more touches over 23 days with different angles.
**Cadence:** Day 14 (case study), Day 21 (objection / FAQ), Day 30 (last call — last touch from this funnel).

> Fill brackets: `[BOOK TITLE]`, `[AMAZON LINK]`. Add UTM to every link: `?utm_source=email&utm_medium=longtail&utm_campaign=kdp_seq`
> Compliance: no income promises. The whole arc respects that they didn't buy on Day 7 — these emails earn the next look, they don't beg for one.

---

## EMAIL 6 — Day 14 (case study / proof through specifics)

**SUBJECT**

What happened when one reader actually ran it

**BODY**

A week after the blueprint went out, one reader emailed me with three lines:

"Picked one thing. Built it in an afternoon. Sold three on the first day."

That's it. That's the whole message.

I'm not going to tell you what they sold or who they are — the specifics don't transfer. But the pattern does: they picked ONE thing, they built it FAST, they put it in front of real humans the same day.

Most people who get the blueprint never do step one. They keep "thinking about it." The few who do step one usually do steps two and three within 48 hours, because the momentum carries.

If you're still in "thinking about it," that's normal. But it's the trap. Name your one thing today. Out loud. To a friend, in a notebook, in a reply to this email. Just name it. That single act unlocks the next 72 hours.

— J.K.

P.S. [BOOK TITLE] has the full step-by-step if the blueprint felt too compressed → [AMAZON LINK]

---

## EMAIL 7 — Day 21 (objection / "but my situation is different")

**SUBJECT**

"But I don't have an idea yet"

**BODY**

This is the email I get most often.

"I love the blueprint but I don't have an idea yet."

Here's the reframe: you don't need a NEW idea. You need to look at the thing you already do — at work, as a hobby, in your group chats — and ask one question: *what do people keep asking me about?*

That's your offer. The thing other humans already pay attention to when you talk. Not a "passion." Not a "calling." A pattern that's already happening, where you're already the answer.

Most great first products are someone packaging the answer they were already giving for free.

Don't wait for an idea to strike. Audit what's already happening. The signal is there.

— J.K.

P.S. The full method for finding and packaging that signal is Chapter 1 of [BOOK TITLE] → [AMAZON LINK]

---

## EMAIL 8 — Day 30 (last call — direct, kind, clean exit)

**SUBJECT**

Last one — then I'll stop

**BODY**

This is the last email in this sequence.

After today, you stay on the list — you'll get the broadcasts, the new blueprints, the bigger releases. But this specific arc closes here, and I want to close it cleanly.

Here's what I want you to know:

If the blueprint sat with you for a month and nothing clicked, that's information. Maybe this isn't your moment. Maybe you're building something different in a different way. Both are fine. The worst outcome is pretending the blueprint changed something when it didn't.

If it DID sit with you — if "pick the one thing" is still rattling around — then the book is the longer, fuller version of that one idea. Same voice. More depth. → [AMAZON LINK]

Either way: thank you for being here, for opening these. Most people don't.

— J.K.

P.S. Reply to this email any time. It goes straight to me, not a queue.

---

## After you paste into Kit

1. Create a sequence named to match `KIT_SEQUENCE_KDP_LONGTAIL_NAME` (default `KDP Long-Tail`).
2. Add 3 emails (the file numbers them 6/7/8 to preserve continuity with the main KDP arc; in Kit they're emails 1/2/3 of this sequence).
3. Delays: Email 1 immediate (relative to sequence entry, not relative to opt-in), then +7 days, then +9 days.
4. Fill `[BOOK TITLE]` and `[AMAZON LINK]`, add UTMs to every link.
5. In Kit's automation rules: at the end of Day 7 of the main KDP sequence, if the subscriber's `purchased:[BOOK TITLE]` tag is NOT present, add tag `kdp:nonbuyer` and trigger entry into this sequence.

## Alignment with code

| Where | What |
|---|---|
| `narai/api/routes/toodle.py` | `DEFAULT_SEQUENCE_NAMES` does NOT include long-tail — long-tail entry is driven by Kit automation rules on tag, not by the Capture Agent. |
| `.env.example` | `KIT_SEQUENCE_KDP_LONGTAIL_NAME=KDP Long-Tail` (add when wiring this sequence — purely documentary, no Capture-Agent code path uses it) |
| `core/lead_capture.py:re_engage_cold_leads()` | Existing plumbing for re-engaging cold leads. Can be repurposed if Kit-side automation is undesirable, but Kit-side is cleaner. |

## Why this exists

Acquisition cost was paid for every name on this list. Letting a non-buyer go silent after Day 7 forfeits that cost. Three additional touches over 23 days at low cadence respect the no-sale signal while keeping the door open. Day 30 closes the loop cleanly — better to lose them with dignity than annoy them into unsubscribing from the broader list.

This is hygiene, not aggression. If a non-buyer never opens an email from this arc, they exit naturally; if they do open, the offer is right there.
