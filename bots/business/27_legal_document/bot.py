#!/usr/bin/env python3
"""
Bot #27 — Legal Document Generator
Category: Business
Purpose: Generate business legal document templates including contracts, agreements,
         terms of service, privacy policies, and NDAs.

DISCLAIMER: Output is a template for reference only — always review with a qualified attorney.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot


class LegalDocumentBot(BaseBot):

    def __init__(self):
        super().__init__("27_legal_document", "business")

    def run(self, doc_type: str = None, party_a: str = None,
            party_b: str = None, key_terms: str = None,
            jurisdiction: str = None, **kwargs):

        cfg = self.config
        doc_type     = doc_type or cfg.get("doc_type", "freelance_service_agreement")
        party_a      = party_a or cfg.get("party_a", "WheellsVerse (Service Provider)")
        party_b      = party_b or cfg.get("party_b", "Client (Business Owner)")
        key_terms    = key_terms or cfg.get("key_terms", "monthly retainer, content creation, AI automation services")
        jurisdiction = jurisdiction or cfg.get("jurisdiction", "State of [Your State], USA")

        self.logger.info(f"Generating {doc_type}: {party_a} ↔ {party_b}")

        system = (
            "You are a business attorney and legal document specialist who creates "
            "clear, professional legal templates for small businesses and freelancers. "
            "You write in plain English where possible while maintaining legal validity. "
            "You always include a disclaimer that the template should be reviewed by "
            "a licensed attorney before use. You focus on common scenarios and "
            "practical protections that matter most to small businesses."
        )

        doc_types = {
            "freelance_service_agreement": "Freelance / Independent Contractor Service Agreement",
            "nda":                         "Non-Disclosure Agreement (NDA)",
            "partnership_agreement":       "Business Partnership Agreement",
            "client_contract":             "Client Service Contract",
            "affiliate_agreement":         "Affiliate Marketing Agreement",
            "terms_of_service":            "Website Terms of Service",
            "privacy_policy":              "Privacy Policy",
            "content_license":             "Content License Agreement",
            "ip_assignment":               "Intellectual Property Assignment Agreement",
        }

        doc_label = doc_types.get(doc_type, doc_type.replace("_", " ").title())

        prompt = f"""Generate a professional {doc_label} template:

DOCUMENT TYPE: {doc_label}
PARTY A: {party_a}
PARTY B: {party_b}
KEY TERMS/SERVICES: {key_terms}
JURISDICTION: {jurisdiction}

⚠️ DISCLAIMER: Include at the top: "This document is a template for informational purposes only. It is not legal advice. Please consult a licensed attorney in your jurisdiction before using this document."

---

## {doc_label.upper()}

**Effective Date:** ____________, 20___
**Between:** {party_a} ("Party A")
**And:** {party_b} ("Party B")

[Generate a complete, professional {doc_label} with all standard sections relevant to this document type, including:]

For a {doc_label}, the key sections should include:

1. **RECITALS / PURPOSE** — Background and intent of the agreement
2. **DEFINITIONS** — Key terms defined clearly
3. **SCOPE OF SERVICES/AGREEMENT** — Specific to {key_terms}
4. **PAYMENT TERMS** — (if applicable) compensation, invoicing, late payment
5. **TERM AND TERMINATION** — Duration, renewal, termination clauses
6. **INTELLECTUAL PROPERTY** — Who owns what is created
7. **CONFIDENTIALITY** — What information stays private
8. **WARRANTIES AND REPRESENTATIONS** — What each party guarantees
9. **LIMITATION OF LIABILITY** — Liability caps and exclusions
10. **INDEMNIFICATION** — Who protects whom from claims
11. **DISPUTE RESOLUTION** — Mediation/arbitration/jurisdiction: {jurisdiction}
12. **GENERAL PROVISIONS** — Entire agreement, amendments, severability, waiver
13. **SIGNATURE BLOCK** — Both parties' signature lines with date

Write the full document text — not just section headers. Include specific, appropriate language for each section based on the document type and key terms provided.

After the document, include:
## NEGOTIATION NOTES
5 clauses that are commonly negotiated and how to adjust them

## RED FLAGS TO WATCH FOR
5 terms that favor the other party too heavily — know when to push back"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3500)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_type = doc_type.replace(" ", "_")[:25]

        output = f"""# {doc_label}
**Parties:** {party_a} ↔ {party_b}
**Jurisdiction:** {jurisdiction}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

⚠️ **LEGAL DISCLAIMER:** This is a template for reference only. Not legal advice. Review with a licensed attorney before use.

---

{result}

---
*Generated by WheellsVerse Legal Document Bot*
"""
        path = self.save_output(output, f"legal_{safe_type}_{ts}.md", ext="md")
        self.logger.info(f"Legal document saved → {path}")
        return {"file": str(path), "doc_type": doc_type}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Legal Document Generator")
    parser.add_argument("--type",         type=str, default="freelance_service_agreement",
                        choices=["freelance_service_agreement", "nda", "partnership_agreement",
                                 "client_contract", "affiliate_agreement", "terms_of_service",
                                 "privacy_policy", "content_license", "ip_assignment"])
    parser.add_argument("--party-a",      type=str, default=None)
    parser.add_argument("--party-b",      type=str, default=None)
    parser.add_argument("--terms",        type=str, default=None)
    parser.add_argument("--jurisdiction", type=str, default="USA")
    args = parser.parse_args()
    bot = LegalDocumentBot()
    result = bot.execute(doc_type=args.type, party_a=args.party_a, party_b=args.party_b,
                         key_terms=args.terms, jurisdiction=args.jurisdiction)
    print(f"\n✅ Legal Document: {result['file']}")
