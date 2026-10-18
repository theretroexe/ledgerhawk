# LedgerHawk

LedgerHawk is an accounts payable invoice audit **demo**. Its existing FastAPI dashboard accepts PDF invoices, compares them with local purchase orders and vendor records, records decisions, and offers a human review queue and audit analytics. It does not make payments, post to an ERP, or send messages.

## How an invoice is processed

1. In **live** mode, an Evolus invoice extraction workflow receives the PDF in multipart field `file`. The app polls its execution and parses `vendor`, `invoice_number`, `invoice_date`, `po_number`, `iban`, `currency`, `total`, and `lines` (including JSON-encoded line arrays). In **demo** mode, the bundled sample PDFs use the local extractor simulation.
2. The backend performs deterministic duplicate, bank-account, vendor, PO, line-item, amount, and total checks. Its decision priority is **duplicate → reject; other high-risk flag → escalate; other failed check → hold; no failed checks → approve**.
3. In live mode, an Evolus AP assessment workflow receives the invoice, matched PO, vendor master entry, flags, and `ap_policy.md` through multipart text field `input`. It returns a decision, rationale, and optional vendor-message **draft for display only**. The backend validates this response and overrides any decision that disagrees with its local rules. Demo mode uses local assessment and draft simulations.
4. The final decision and invoice summary go to a **demo-only Evolus routing workflow** in live mode, also through `input`. The app polls for a completed acknowledgement and checks the invoice number, decision, route, and `recorded` status before adding an audit entry. Demo mode simulates the acknowledgement. Review actions also use the demo route.

Both modes preserve the existing dashboard, review queue, sample invoice generator, and in-memory audit log. A live failure is shown as an error and does **not** silently switch to simulation.

## Run locally

From the `ledgerhawk/` directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python app.py
```

Open `http://localhost:8000`. `LEDGERHAWK_MODE=demo` works without Evolus credentials. For live mode, set `LEDGERHAWK_MODE=live` and fill `EVOLUS_API_KEY`, `EVOLUS_APPLICATION_ID`, `EVOLUS_WORKFLOW_EXTRACT_ID`, `EVOLUS_WORKFLOW_ASSESS_ID`, and `EVOLUS_WORKFLOW_ROUTE_ID` in the local `.env`; restart the app. `EVOLUS_BASE_URL` defaults to `https://api.evolus.ai`. `AMD_MODEL_NAME` only changes the dashboard label. The app loads its own `.env` without overriding already-set process variables. It never prints the key, document body, or extracted output.

The three workflow IDs must refer to the **LedgerHawk** invoice extraction, AP assessment, and demo routing workflows. The routing workflow must generate an acknowledgement only; verify that it has no email, messaging, ERP, or payment steps. TenderLens workflows are separate and should not be reused here.

## Test

```bash
.venv/bin/python test_app.py
.venv/bin/python -m unittest test_workflows.py -v
```

Both commands use offline data and mocks, even when local `.env` selects live mode. The five sample outcomes are Northwind **approve**, Orbit **escalate**, Apex **reject**, Helix **hold**, and Brightline **hold**. Repeated runs of the same invoice become duplicates until you click **Reset demo data** or call `POST /api/reset`.

Docker uses the same configuration:

```bash
docker build -t ledgerhawk .
docker run -p 8000:8000 --env-file .env ledgerhawk
```

## Submission materials

Start with the [submission index](submission/README.md). The revised package in [submission/current/](submission/current/README.md) contains project descriptions, an architecture diagram, an eight-slide deck (HTML and PDF), a cover, a demo-mode Orbit screenshot, and a demo script. Older assets directly under `submission/` are retained for reference but are outdated; do not use their claims about Qwen/vLLM, ERP or email actions, automatic fallback, or measured business results.

Before submission, verify the actual AMD-backed model and routing steps in the Evolus workspace, run all five cases in live mode, test the Docker image, and record the demo video. The dashboard's `AMD_MODEL_NAME` label and the demo-mode screenshot do not establish remote model use. A public repository and reachable app URL also remain to be prepared.

## Security and limits

Keep `.env` out of Git and never paste credentials into issues or chat. The dashboard has no login, and its ledger lives in memory; use it as a demo, not a production payment system. The app accepts PDFs up to 20 MB. Live workflow requests time out, failed execution statuses surface to the user, and no audit entry is added for a failed pipeline. The local reviewer identity is self-reported; production use would require authentication and persistent records.
