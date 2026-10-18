# lablab.ai submission text

## Project title

LedgerHawk: accounts-payable control agent on Evolus × AMD

## Short description (≤255 characters)

LedgerHawk is an accounts-payable agent on Evolus and an open model on AMD Instinct. It reads emailed invoices, checks them against the PO and vendor master, and stops duplicate payments and bank-detail fraud before any money leaves.

## Long description

**The problem.** Accounts-payable teams still key supplier invoices by hand, roughly 10–15 minutes each, and the costly mistakes get through anyway: a "second notice" for an invoice that was already paid, a price quietly raised above the purchase order, or an email saying "our bank details have changed" that is really business email compromise.

**What LedgerHawk does.** It runs supplier-invoice intake end to end for the AP clerk and the financial controller. An invoice arrives by email with a PDF attached, and the Evolus document extractor turns it into fields and lines. Eight deterministic controls check it against the purchase order and the vendor master (a two-way match): approved vendor, bank details, duplicate, valid PO, items on the PO, prices within 2%, quantities and totals. An Evolus agent, backed by an open model (Qwen2.5-7B-Instruct) served with vLLM on an AMD Instinct MI300X in AMD Developer Cloud and grounded in an AP policy held in an Evolus knowledge library, makes the call and writes the rationale. For fixable variances, the Evolus email AI Tool writes to the vendor. Evolus workflows then post the invoice to the ERP or start a human review.

**An audit instrument, not a chatbot.** The invoice is shown as the extractor read it, and each control's evidence sits in the margin beside the exact field or line, including a character-by-character diff of the IBAN against the vendor master. Each run ends with an AP control stamp: Approved for payment, Hold: query vendor, Hold: PO required, Stop: verify bank details, or Duplicate: do not pay. A Document | JSON switch shows the full run record (extracted fields, the eight controls with the PO and vendor master, the model's decision, the vendor email, the workflow and the ledger entry), ready to copy or download. A Records tab exposes the vendor master and purchase orders the controls check against.

**Built to be trusted.** The model can be stricter than the controls, never looser: if it tries to approve an invoice that failed a check, the policy decision overrides it and the override is logged. Releasing a stopped invoice needs the reviewer's name, a reason and an attestation that the vendor was called back on the number in the vendor master; the old stamp is struck through and re-stamped "Released for payment" with the reviewer's name. Every decision and override lands in a searchable audit log with CSV export.

**Measurable value.** The Audit view leads with loss prevented, counting only duplicates and suspected fraud, and shows variances separately as held for correction. On the app's 30-day demo ledger (synthetic data plus five demo emails): €39,424 loss prevented, €2,550 of it caught in the demo session (a €1,410 suspected fraud and a €1,140 duplicate), €750 held for correction, 70% of invoices touchless, and 9.8 hours saved at an assumed 12 minutes of manual handling per invoice.

**How it is built.** A single-file FastAPI app with a no-build HTML UI, packaged with Docker. Each Evolus building block (document extractor, agent via its OpenAI-compatible endpoint, knowledge library, AI Tool, workflows) is called through the Evolus API when its credentials are set and simulated otherwise, and the app labels every step live, simulated or fallback, so the demo runs anywhere and never fails silently.

**Next.** Measure latency and extraction accuracy on the MI300X endpoint with real invoices, read the vendor master and POs from the ERP through Evolus workflows, add goods receipts for a full three-way match, and turn reviewer releases into policy updates.

## Technology tags

Evolus, AMD Developer Cloud, AMD Instinct MI300X, ROCm, vLLM, Qwen2.5-7B-Instruct, Open-source LLM, AI Agents, Document AI, OpenAI-compatible API, FastAPI, Python, Docker

## Category tags

Finance, Accounts Payable, Fraud Prevention, Business Automation, Enterprise AI

## Files to upload

- Cover image: `cover.png` (1280×720)
- Slide presentation: `deck.pdf` (9 slides; source `deck.html`)
- Posters: `poster.pdf` (A3 print, also `poster.png` at 2246×3174) and `poster-social.png` (1080×1350 for social posts); sources `poster.html`, `poster-social.html`
- Video: record from `demo-script.md`, upload to YouTube, paste the link
- Extra screenshots if the form allows: `full-orbit-bank.png` (stop on bank details), `full-orbit-json.png` (run record), `full-released.png` (released by a reviewer), `shot-audit.png` (loss prevented), `full-records-gb33.png` (fraudster's IBAN not in the vendor master), `full-orbit-dark.png` (dark theme)
