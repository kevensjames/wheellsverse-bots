# WheellsVerse Store — Deliverables

Content ready to sell. Each folder maps to a `store_key` in [core/store_setup.py](../../core/store_setup.py) and [core/store_delivery.py](../../core/store_delivery.py).

## What's in here

### ✅ prompt_bible/prompt_bible.md — Prompt Bible v1
- 200 copy-paste ChatGPT prompts across 20 categories (10 per category)
- Plain Markdown, easy to convert to PDF
- Labeled as v1 — future versions grow each category to 500 prompts (10,000 total)

### ✅ social_templates/social_templates.csv — Social Template Pack v1
- 60 ready-to-post social media posts
- Themes: AI Tips, Income, Crypto, Motivation, Productivity
- Platforms mixed: Instagram, LinkedIn, Twitter
- CSV format — import directly into Buffer, Hootsuite, or Later

## To ship these as paid products

1. **Export to delivery format.** Convert the Markdown/CSV into a polished PDF/ZIP. Options:
   - Markdown → PDF: `pandoc prompt_bible.md -o prompt_bible.pdf` or open in Typora/Obsidian and "Export as PDF"
   - CSV → stays as CSV, plus a companion PDF with a "how to use" guide
2. **Host the file somewhere stable.** Google Drive (shareable link), S3 with signed URL, or Gumroad asset host.
3. **Set the delivery URL as a Railway env var:**
   ```
   DELIVERY_URL_PROMPT_BIBLE=https://drive.google.com/file/d/.../view?usp=sharing
   DELIVERY_URL_SOCIAL_TEMPLATES=https://drive.google.com/file/d/.../view?usp=sharing
   ```
   Use `railway variables --set 'DELIVERY_URL_PROMPT_BIBLE=...'`
4. **Run Stripe setup** (only if/when you've decided to go live on these two products):
   ```bash
   python -m core.store_setup
   ```
   This creates the Stripe products + payment links and writes them to `data/store_payment_links.json`. The `/store` handler then injects them into the Buy buttons.
5. **Redeploy** to pick up the new `store_payment_links.json`.
6. Test: buy one product yourself with a real card to confirm end-to-end. Refund via Stripe dashboard after.

## Not yet built

These products have placeholder entries in `store_setup.py` and `store_delivery.py` but no deliverable content. Buyers would get a "preparing your order" holding email until the content exists + its `DELIVERY_URL_<KEY>` env var is set.

- AI Income Blueprint (course videos + workbook)
- Crypto Starter Toolkit
- AI Automation Guide
- WheellsVerse Bot Pack (access package)
- Bundle (assembly of the above)
- Crypto Newsletter (ongoing publication)
- WhatsApp Inner Circle (group setup)
- NEXORA Creator Platform Beta (external)

Build these in future sessions, one at a time.
