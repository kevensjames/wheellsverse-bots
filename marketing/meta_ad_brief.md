# Meta Ad Brief — AI Stock Alerts launch

$5/day cold-traffic test. Goal: validate that paid traffic converts on the new store.

---

## Campaign

| Field | Value |
|---|---|
| Objective | **Sales** (optimize for purchases) |
| Daily budget | **$5** |
| Run length | **7 days** ($35 total) |
| Audience | **United States · ages 25-45 · interests: Stock trading, Cryptocurrency, AI, Personal finance, Robinhood, Coinbase, Trading view, Bloomberg** |
| Placement | Manual: Instagram Feed + Facebook Feed only (no Stories — too short for this offer) |
| Pixel | Meta Pixel installed on `shop.wheellsverse.com` (Shopify Admin → Settings → Customer events → add Meta Pixel) |

---

## Primary text (post body — 125 char optimal)

> Daily AI-curated trade signals across stocks + crypto. $19/mo, 7 days free. Cancel anytime. shop.wheellsverse.com

---

## Headlines (40 char each — test 3)

**Variant A:** `AI Stock Alerts — 7 Days Free`
**Variant B:** `Operators don't doomscroll Twitter`
**Variant C:** `Daily AI signals · Stocks + Crypto`

---

## Descriptions (30 char optimal — under "headlines")

- `Built by an operator, for operators`
- `Cancel anytime · No fluff`
- `Same engine I use for my trades`

---

## Creative

**Static image option (1:1, 1080×1080):** Use the Neural-Mesh hero shot — dark navy background, "Built for the operator class." headline in cyan gradient. Add a sticker overlay: `$19/mo · 7 DAYS FREE` in cyan caps.

**Video option (1:1, 1080×1080, 15-30 sec):** Screen recording of the storefront — neural network animating, scroll past hero, scroll to AI Stock Alerts product card, zoom on "$19/mo · 7 DAYS FREE". Cut to a sample alert (text overlay on dark): "TICKER: NVDA · BUY · CONF 0.84". End frame: `shop.wheellsverse.com`. Voiceover optional; works without sound.

The video creative typically outperforms static for SaaS subscriptions by 30-40% — worth the extra 20 minutes of recording.

---

## Tracking

UTM parameters on every link:

```
?utm_source=meta&utm_medium=cpc&utm_campaign=ai_alerts_launch&utm_content={ad_variant}
```

Setup in Shopify Admin → **Settings → Customer events → Add custom pixel** for full conversion tracking back to Meta.

---

## What to watch in week 1

| Metric | Healthy | Warning |
|---|---|---|
| CTR | > 1.5% | < 0.8% (creative is weak) |
| CPM | < $30 | > $60 (audience too cold) |
| Add to Cart rate | > 5% | < 2% (landing page issue) |
| Purchase rate (of ATC) | > 25% | < 10% (checkout friction) |
| Cost per purchase | < $40 | > $80 (kill or pivot) |

If 7 days = no purchases at all, the issue is the *offer* (too cold, wrong audience), not the funnel — move budget to retargeting visitors who opened your other free content (blog, NarAI demo, IG followers).

---

## Stop / scale rules

- **Day 3, no ATCs:** kill the variant, try a new headline
- **Day 5, ATCs but no purchases:** the checkout is fine but the offer isn't compelling enough — try a discount (`FIRSTMONTH50` for 50% off month 1) or longer trial
- **Day 7, hitting cost-per-purchase < $40:** double the daily budget to $10, run for another 7 days
