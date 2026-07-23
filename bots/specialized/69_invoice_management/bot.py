#!/usr/bin/env python3
"""
Bot #69 — Invoice & Billing Management System Builder
Category: Specialized
Purpose: Generate professional invoice templates, billing workflows, payment tracking
         systems, and late payment follow-up sequences for entrepreneurs.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

INVOICE_TYPES = {
    "service": "Service invoice for consulting, agency, or freelance work",
    "product": "Product or digital goods invoice",
    "recurring": "Recurring subscription or retainer invoice",
    "project": "Milestone-based project invoice with payment schedule",
    "advance": "Deposit or advance payment invoice",
    "final": "Final balance invoice after project completion",
}

PAYMENT_TERMS = {
    "immediate": "Due on receipt",
    "net_7": "Due within 7 days",
    "net_15": "Due within 15 days",
    "net_30": "Due within 30 days",
    "net_45": "Due within 45 days",
    "50_50": "50% upfront, 50% on completion",
    "milestone": "Tied to project milestones",
}


class InvoiceManagementBot(BaseBot):

    def __init__(self):
        super().__init__("69_invoice_management", "specialized")

    def run(self, client_name: str = None, services: str = None,
            amount: str = None, payment_terms: str = None,
            invoice_type: str = None, **kwargs):

        cfg = self.config
        client_name = client_name or cfg.get("client_name", "[Client Company Name]")
        services = services or cfg.get("services",
            "AI automation setup, custom bot development (5 bots), 30-day support")
        amount = amount or cfg.get("amount", "$4,997")
        payment_terms = payment_terms or cfg.get("payment_terms", "net_30")
        invoice_type = invoice_type or cfg.get("invoice_type", "service")

        type_desc = INVOICE_TYPES.get(invoice_type, invoice_type)
        terms_desc = PAYMENT_TERMS.get(payment_terms, payment_terms)

        self.logger.info(f"Generating invoice system for: {client_name} — {amount}")

        system = (
            "You are a business operations consultant and financial systems expert who has "
            "helped 200+ freelancers and entrepreneurs professionalize their billing. "
            "You know that professional invoicing does two things: it gets paid faster, "
            "and it makes your business look legitimate. You design invoicing systems that "
            "eliminate late payments through clear terms, automated reminders, and professional "
            "presentation. You know the psychology of invoice design — a well-structured invoice "
            "signals professionalism and reduces the friction of paying."
        )

        prompt = f"""Generate a complete invoice and billing management package for:

CLIENT: {client_name}
SERVICES: {services}
AMOUNT: {amount}
PAYMENT TERMS: {payment_terms} — {terms_desc}
INVOICE TYPE: {invoice_type} — {type_desc}
BUSINESS: WheellsVerse — AI automation tools
OWNER: Jhon Kevens D Wheeler / J.K. Blaze

---

## PROFESSIONAL INVOICE TEMPLATE

---

**INVOICE**

**WheellsVerse**
AI Automation Solutions
[Business Address] | [City, State, ZIP]
[Email] | [Website] | [Phone]

---

| | |
|---|---|
| **INVOICE #:** | WV-[YYYY]-[NNNN] |
| **DATE:** | [Issue Date] |
| **DUE DATE:** | [Due Date — {terms_desc}] |
| **BILL TO:** | {client_name} |
| | [Client Address] |
| | [Client Email] |

---

**SERVICES RENDERED:**

| # | Description | Qty | Rate | Amount |
|---|-------------|-----|------|--------|
| 1 | [Service line 1 from: {services}] | | | |
| 2 | [Service line 2] | | | |
| 3 | [Service line 3 if applicable] | | | |

| | | |
|---|---|---|
| | **Subtotal:** | $[X] |
| | **Tax ({"{Tax Rate}"}%):** | $[X] |
| | **TOTAL DUE:** | **{amount}** |

---

**PAYMENT METHODS:**
- Bank Transfer: [Account details placeholder]
- PayPal: [Email]
- Stripe: [Payment link]
- Crypto (optional): [Wallet address]

**Payment Terms:** {terms_desc}
**Late Fee:** 1.5% per month on overdue balances

---

**NOTES:**
[Project reference, deliverables summary, or special instructions]

**Thank you for your business!**

---

## INVOICE VARIATIONS

### Progress/Milestone Invoice Template
[If {invoice_type} involves milestones:]
**Milestone 1 (50% deposit):** $[X] — Due: Project Start
**Milestone 2 (25%):** $[X] — Due: [Checkpoint]
**Milestone 3 (25% final):** $[X] — Due: Project Completion

### Recurring Retainer Template
**Monthly Service Agreement:**
Amount: $[X]/month
Billing Cycle: [1st of each month / Net 15]
Auto-renewal: [Yes — 30-day cancellation notice required]

---

## PAYMENT FOLLOW-UP SEQUENCE

### For {amount} invoice with {payment_terms} terms:

**Email 1 — Invoice Sent (Day 0)**
Subject: Invoice #WV-[YYYY]-[NNNN] for {services[:30]}...
```
Hi [Name],

Please find attached Invoice #WV-[YYYY]-[NNNN] for the work completed on [project].

Total: {amount}
Due: [Date] ({terms_desc})

You can pay via [payment method]. Please reach out if you have any questions.

Thanks for working with us!

J.K. Blaze | WheellsVerse
```

**Email 2 — Friendly Reminder (3 days before due)**
Subject: Friendly reminder: Invoice #{amount} due [Date]
```
[Polite 3-line reminder — just making sure it hasn't slipped through the cracks]
```

**Email 3 — Day of Due Date**
Subject: Invoice due today — {amount}
```
[Professional reminder — payment is due today, payment link included]
```

**Email 4 — 7 Days Overdue**
Subject: Overdue: Invoice #{amount} — action required
```
[Firm but professional — reference late fee policy, request payment or update]
```

**Email 5 — 14 Days Overdue**
Subject: Second notice: Overdue invoice — {amount}
```
[More formal tone — propose a payment plan or escalation path]
```

**Email 6 — 30 Days Overdue**
Subject: Final notice before escalation — Invoice {amount}
```
[Final notice — next step is collections or legal, offer one last resolution path]
```

---

## BILLING MANAGEMENT SYSTEM

### Invoice Tracking Spreadsheet Structure
| Invoice # | Client | Date | Amount | Due Date | Status | Paid Date | Notes |
| WV-[YYYY]-0001 | [Client] | | {amount} | | Outstanding | | |

**Status options:** Draft / Sent / Viewed / Partial / Paid / Overdue / Written Off

### Monthly Billing Dashboard Metrics
- **Total invoiced:** $[X]
- **Collected:** $[X] ([X]%)
- **Outstanding:** $[X]
- **Overdue:** $[X]
- **Average days to payment:** [X days]
- **AR aging:** [0-30 / 31-60 / 61-90 / 90+ days buckets]

---

## INVOICING TOOLS COMPARISON

| Tool | Best For | Price | Key Feature |
| QuickBooks | Full accounting | $30-$100/mo | Tax prep integration |
| Wave | Freelancers/solo | Free | Invoice + accounting free |
| FreshBooks | Service businesses | $17-$55/mo | Time tracking + invoicing |
| Stripe Invoicing | Online payments | 0.4% fee | Auto payment collection |
| PayPal Invoice | Quick invoices | 2.9% + $0.30 | Widely accepted |

**Recommended for WheellsVerse ({amount} invoices):** [Best tool with reason]

## LEGAL PROTECTION CLAUSES

Add these to contracts/invoices to protect against non-payment:
1. [Clause 1 — intellectual property retention until payment]
2. [Clause 2 — late fee language]
3. [Clause 3 — dispute resolution]
4. [Clause 4 — governing law/jurisdiction]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_client = self.slugify(client_name, 20)

        output = f"""# Invoice Package: {client_name}
**Amount:** {amount}
**Terms:** {payment_terms}
**Type:** {invoice_type}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Invoice Management Bot*
"""
        path = self.save_output(output, f"invoice_{safe_client}_{ts}.md", ext="md")
        self.logger.info(f"Invoice package saved → {path}")
        return {"file": str(path), "client": client_name, "amount": amount}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Invoice & Billing Management System Builder")
    parser.add_argument("--client", type=str, default=None)
    parser.add_argument("--services", type=str, default=None)
    parser.add_argument("--amount", type=str, default=None)
    parser.add_argument("--terms", type=str, default="net_30",
                        choices=list(PAYMENT_TERMS.keys()))
    parser.add_argument("--type", type=str, default="service",
                        choices=list(INVOICE_TYPES.keys()))
    args = parser.parse_args()
    bot = InvoiceManagementBot()
    result = bot.execute(client_name=args.client, services=args.services,
                         amount=args.amount, payment_terms=args.terms,
                         invoice_type=args.type)
    print(f"\n✅ Invoice Package: {result['file']}")
