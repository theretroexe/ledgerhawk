# LedgerHawk project descriptions

Use this copy for a **controlled prototype**. Confirm the chosen challenge and remote AMD model evidence before submission. No performance, cost-saving, or loss-prevention figures have been measured with customers.

## Project title

LedgerHawk — explainable invoice review with Evolus workflows

## Short description (under 255 characters)

LedgerHawk reviews supplier PDF invoices with three Evolus workflows and local AP controls. It flags duplicate invoices, changed bank details, and PO mismatches, then records a demo decision or sends the case to a human review queue.

## Long description

**Problem and user.** Accounts-payable clerks need to compare invoices with purchase orders and vendor records before payment. A duplicate reminder, changed bank account, or price variance can be easy to miss when information is split across a PDF and several records. Financial controllers need to understand why an invoice was held and who reviewed it.

**Working prototype.** LedgerHawk is a FastAPI dashboard where a user selects a synthetic sample invoice or uploads a PDF. In live mode, the first Evolus workflow extracts eight invoice fields and line items from the PDF. Local Python checks compare the normalized invoice with an in-memory vendor master, purchase orders, and prior ledger entries. A second Evolus workflow receives the invoice, matching records, flags, and AP policy, then returns a proposed decision, rationale, and optional vendor-message draft. The app validates the response and applies its own deterministic decision: duplicates are rejected, other high-risk flags escalated, other mandatory failures held, and clean invoices approved. A third Evolus workflow acknowledges a **demo-only** route for that final decision. Live workflow errors are shown; the app does not silently switch to simulation.

**What the user sees.** The Intake view places the extracted invoice beside field-level checks and a step-by-step run record. Audit provides an in-memory review queue, searchable log, CSV export, and illustrative analytics; Records shows the local vendor and PO data used by the checks. A reviewer can approve or reject an exception, with a name and reason recorded. Releasing an escalated invoice also requires a call-back attestation. The five included synthetic cases demonstrate a clean approval, bank-detail escalation, duplicate rejection, price hold, and missing-PO hold.

**Boundaries.** This is a procurement-control demo, not a payment system. It does not send vendor emails or messages, post invoices to an ERP, or transfer funds. Draft text is display only. The ledger is in memory, reviewer identity is self-reported, and the seeded analytics do not establish measured business impact. Demo mode uses local simulations; live mode requires the team's configured Evolus workspace. The dashboard's model label does not verify the remote model/provider.

**Next steps.** Verify and document the actual AMD TokenFactory model used by the remote workflows, test the container build, run the five live scenarios, record a truthful demo video, and provide a controlled hosted prototype. Production use would require authentication, persistent records, real master-data integrations, and operational review controls.

## Tags

**Supported by the repository:** Evolus REST workflows, FastAPI, Python, HTTPX, invoice extraction, rules-based validation, accounts payable, human review.

**Add only after remote verification:** AMD TokenFactory and the exact model/provider used by the Evolus workspace. Do not list AMD Instinct MI300X, ROCm, vLLM, or a specific open model unless separate evidence establishes them.
