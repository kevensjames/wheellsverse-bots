---
name: truth_verification
description: Use whenever a function reports success, completion, or any positive terminal status from an external action — including web automation (Playwright clicks, form fills, navigation), file writes, API calls, queue or registry updates, database writes, or subprocess results. Also use when reviewing diffs that touch upload_book, daily_kdp_publish, or any function whose return value influences whether a row is marked published/live/uploaded/sent in a registry, queue, log, or notification. Enforces strict assertion-based verification instead of trusting return codes, URL transitions, status strings, or absence of exceptions.
---

# Truth Verification Protocol

## The lie pattern we are eliminating

Functions in this codebase have historically reported success in
three deceptive ways:

1. URL-substring trust — "we navigated to /pricing so we are on the
   pricing tab" (false: /pricing also appears in /ap/signin redirect
   URLs and in error pages)
2. Return-code trust — "click_and_wait returned without exception so
   the click worked" (false: it has a try/except that swallows
   selector-not-found)
3. Optimistic logging — "we reached the publish step so log 'Published!'"
   (false: reaching a step is not the same as completing it)

## Why this skill exists

This skill was created after a specific failure on 2026-05-19. The KDP
publish automation reported `status: published` and sent a Telegram
"✅ Kindle: published" notification for The Night Parliament. The
KDP dashboard showed the book was still in Draft state — the Content
tab had no cover, no AI disclosure, no accuracy checkbox; the Pricing
tab was entirely empty; the yellow Publish button was never clicked.

The lie was produced by code that did:

    if "title-setup" in page.url and "/pricing" in page.url:
        result["status"] = "published"
        logger.info(f"Published! URL: {page.url}")

The URL had `/pricing` in it because the script navigated TO the pricing
tab, not because it completed publishing. Two iterations of debugging
were wasted on downstream symptoms before the lie was traced to its
source.

If this skill prevents one repeat of that pattern, it has paid for itself.
If you find yourself writing code that looks like the snippet above —
stop and apply the verification rule below.

## The verification rule

Every function that writes "success", "published", "complete", "ok",
"done", "uploaded", or any positive terminal status MUST satisfy
ALL THREE conditions before doing so:

1. **Pre-condition asserted before action.** Before clicking publish,
   verify the pre-state (on pricing tab, all required fields filled).
   Before uploading a file, verify the file exists on disk and is
   readable.

2. **Action performed with explicit wait for response.** No fire-and-
   forget clicks. Every action awaits a specific signal — DOM marker
   visible, API response 200, file appears at target path.

3. **Post-condition asserted against external state.** Not against the
   return value of the action itself. The check must be answerable by
   observing the world, not by trusting the caller. For KDP publish
   this means: poll the bookshelf or product page for "In Review" or
   "Live" status, do not trust a URL transition. For a file upload
   this means: read the target back and compare hash. For a queue
   update this means: re-read the queue file and verify the row exists.

If any of the three conditions cannot be satisfied, the function MUST
return a non-success status with a named error code and a screenshot
or evidence artifact.

## Forbidden patterns

- `if "expected_substring" in page.url: success = True`
- `try: do_thing(); status = "ok"; except: status = "fail"`
  (without verifying do_thing actually changed external state)
- `result["status"] = "published"` without an immediately preceding
  verification check that called an `is_*_confirmed` helper
- Reading a downstream value as proof of an upstream action — e.g.
  "the registry was updated to 'published', therefore the book is
  published." The registry was updated by the same code that produced
  the lie. Proof must come from an authority that did not write the
  claim. For KDP that means the bookshelf DOM or the public
  amazon.com/dp/[ASIN] page, not data/kdp_registry.json.
- `logger.info("Success!")` before the verification assertion has passed
- String matching on user-visible text without also checking a
  structural DOM marker (KDP changes labels frequently — text alone
  is not a stable proof)

## Required patterns

- Every verification gets its own named helper: `is_authenticated`,
  `is_on_pricing_tab`, `is_publish_confirmed`, `is_cover_uploaded`,
  `is_queue_entry_written`. The name describes the external state,
  not the action.
- Every helper returns a strict bool, never raises, has a short timeout
  (1-3 seconds), checks at least two independent signals where possible.
- Every action function returns a structured result dict with at
  minimum: `ok: bool`, `verified_by: str (helper name)`, `evidence:
  str (path to screenshot or hash or url)`, `state: str (terminal
  state name from the taxonomy)`.
- Every screenshot saved on failure follows the naming convention
  `kdp_<state>_<genre>_<timestamp>.png` so failure mode is grep-able.

## Audit checklist

When you edit any function that touches external state, before saving
the diff, verify:

- [ ] Does this function call any `is_*_confirmed` helper before
      reporting success?
- [ ] If a helper does not exist for what this function asserts,
      did you create one in core/kdp_session.py or wherever helpers
      live?
- [ ] Is every `status = "..."` assignment in a branch immediately
      preceded by a verification check, or in an explicit error
      branch?
- [ ] If this function returns ok=True, can a downstream caller
      prove the external world actually changed, by reading evidence?
- [ ] If KDP's DOM changes tomorrow, would this function fail loud
      (raise a named error with screenshot) or silently lie?

If any checkbox is no, the diff is not ready to save.
