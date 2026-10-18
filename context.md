# LedgerHawk Project Context

**Snapshot: 2026-10-18.** This is the full starting context for a new contributor or ChatGPT conversation. Work from the LedgerHawk repository root. The revised presentation assets are indexed in `submission/README.md`.

## Purpose and change of direction

LedgerHawk is an accounts-payable invoice review **demo**. A clerk selects one of five sample invoice PDFs or uploads a PDF; the app extracts invoice data, checks it against local purchase orders and vendor records, proposes an AP assessment, and records a final decision for review and audit. TenderLens AI was set aside. Do not reuse its workflow IDs or rebuild LedgerHawk around its Streamlit frontend.

The project moved from an older proposed extractor/agent/email/ERP architecture to **three configured LedgerHawk Evolus workflows**: invoice extraction, AP assessment, and demo-only routing. The existing FastAPI dashboard remains the product UI. The user reports that the Evolus workspace uses AMD TokenFactory, but the repository cannot prove which remote model is attached to those workflows. `AMD_MODEL_NAME` is a display label only.

## Repository map

| Path | Role |
| --- | --- |
| `app.py` | FastAPI routes, sample PDF generation, local master data, deterministic controls, live/demo pipeline, review queue, and in-memory ledger. |
| `evolus_workflows.py` | Evolus HTTP execute/poll client and extraction, assessment, and routing response validators. |
| `index.html` | Existing no-build dashboard: Intake, Audit, Records, document/JSON views, review actions, CSV export, and reset. |
| `ap_policy.md` | AP rules sent to the assessment workflow; local code enforces the final decision. |
| `test_app.py`, `test_workflows.py` | Offline regression checks and mocked live-workflow contract tests. |
| `README.md`, `.env.example`, `Dockerfile` | Setup and container instructions; `.gitignore` and `.dockerignore` protect local configuration from Git and Docker build contexts. |
| `submission/README.md`, `submission/current/` | Submission index and revised descriptions, architecture diagram, cover, eight-slide deck (HTML/PDF), demo screenshot, and script. Older assets directly under `submission/` remain **stale**. |

Dependencies are pinned in `requirements.txt`: FastAPI, Uvicorn, HTTPX, and python-multipart. There is no database, frontend build step, or production authentication.

## How one invoice is processed

1. `POST /api/process` accepts a multipart PDF (`file`) and optional email context (`email`), rejects files over 20 MB or without a PDF header, and streams newline-delimited JSON progress events. The email field provides context; the app does not monitor an inbox.
2. In **live** mode, the extraction workflow receives the PDF in multipart field `file`. The client starts an execution at `POST /api/v1/workflows/{id}/execute`, polls `GET /api/v1/workflows/{id}/executions/{executionId}`, and requires a completed output with `vendor`, `invoice_number`, `invoice_date`, `po_number`, `iban`, `currency`, `total`, and `lines`. A JSON-encoded `lines` string is parsed into an array. The app normalizes names, PO placeholders, IBAN, and finite amounts. In **demo** mode, a local simulator reads text from the app's generated sample PDFs; arbitrary PDFs may extract poorly in demo mode.
3. `run_checks()` compares the invoice with in-memory `VENDORS`, `PURCHASE_ORDERS`, and prior ledger entries. It checks duplicates, vendor and IBAN, PO ownership, line items, quantity, price tolerance (2%), and total. Missing or unreadable numbers and amounts fail closed. `rule_decision()` has fixed precedence: **duplicate → reject; other high-risk flag → escalate; other failed mandatory check → hold; no flags → approve**.
4. In live mode, the AP assessment workflow receives JSON via multipart text field `input`: extracted invoice, matched PO, vendor master entry, deterministic flags, and the text of `ap_policy.md`. It must return a valid `decision`, non-empty `rationale`, and optional `draft`. `guard()` replaces any decision that disagrees with the deterministic result and records the override. Drafts are displayed only; no email is sent.
5. The demo routing workflow receives the **final locally validated** decision and invoice summary via multipart text field `input`. Its acknowledgement must repeat the invoice number and decision, report `status: recorded`, and use the matching demo route. Only then does the app append an audit entry. In demo mode this acknowledgement is simulated. A live workflow failure or timeout produces an error event, with no silent simulation fallback and no new audit entry.

Evolus requests use `https://api.evolus.ai` by default with `X-ApiKey` and `X-Application-Id` headers. The client polls every 3 seconds for up to 300 seconds. Routing names are `demo_approved_queue`, `manual_review_queue`, `high_risk_review_queue`, and `rejected_invoice_log` for approve, hold, escalate, and reject. These are **demo acknowledgements**, not payment, ERP, or messaging actions. Check the remote routing workflow itself for unwanted side effects before a live run.

## Sample cases and dashboard

| Sample ID | Invoice | Expected result | Reason |
| --- | --- | --- | --- |
| `northwind-clean` | NW-2291 | Approve | PO, vendor, bank, lines, and total match. |
| `orbit-bank` | OC-3302 | Escalate | Invoice IBAN differs from vendor master. |
| `apex-duplicate` | AP-5510 | Reject | A prior AP-5510 entry is seeded in the ledger. |
| `helix-price` | HX-7781 | Hold | Unit price exceeds the PO tolerance. |
| `brightline-nopo` | BL-0917 | Hold | No purchase order is referenced. |

The dashboard exposes a review queue, audit log, filters, analytics, vendor/PO records, and generated sample PDFs. `POST /api/reset` restores seeded demo data; do this before repeating the walkthrough, or a processed invoice becomes a duplicate. A reviewer can approve or reject a held or escalated item. Releasing an escalated item requires a reviewer name, reason, and confirmed call-back. Review routing errors leave the ledger unchanged. Reviewer identity is self-reported.

The analytics ledger is seeded with synthetic history. Its exposure, loss-prevented, touchless, and time-saved numbers are **demo calculations**, not independently measured customer outcomes. The time-saved calculation assumes 12 manual minutes per touchless invoice.

## HTTP endpoints

| Method and path | Purpose |
| --- | --- |
| `GET /`, `GET /favicon.svg` | Dashboard and icon. |
| `GET /api/status` | Current mode, configuration presence, and display model label; no credentials. |
| `GET /api/samples`, `GET /api/samples/{sid}.pdf` | Sample inbox and generated PDF. |
| `POST /api/process` | Process a PDF and stream NDJSON progress/result events. |
| `GET /api/ledger`, `GET /api/records`, `GET /api/analytics` | Audit entries, local master data, and demo metrics. |
| `POST /api/ledger/{iid}/review`, `POST /api/reset` | Human review and seeded-data reset. |

## Local setup and configuration

From `ledgerhawk/` in a fresh checkout:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
LEDGERHAWK_MODE=demo .venv/bin/python app.py
```

Open `http://localhost:8000`. For live mode, create a **local** `.env` from `.env.example` only if one does not already exist, configure it privately, then restart the app. The app reads its own `.env` without overriding process variables. Configuration names are `LEDGERHAWK_MODE`, `EVOLUS_BASE_URL`, `EVOLUS_API_KEY`, `EVOLUS_APPLICATION_ID`, `EVOLUS_WORKFLOW_EXTRACT_ID`, `EVOLUS_WORKFLOW_ASSESS_ID`, `EVOLUS_WORKFLOW_ROUTE_ID`, and `AMD_MODEL_NAME`. Never paste values into chat, docs, logs, tests, or commits. The three IDs must belong to LedgerHawk workflows, not TenderLens.

The Dockerfile runs the same app on port 8000; `.dockerignore` excludes local `.env`, virtual environments, and Git metadata from the build context. Docker was unavailable in this workspace, so its build and run remain unverified.

## Verification and current repository state

On 2026-10-18, `.ledgervenv/bin/python test_app.py` printed `ok`, and `.ledgervenv/bin/python -m unittest test_workflows.py -q` passed **7 tests**. The tests use simulations or mocks even if local `.env` selects live mode. They cover the five decisions, parsing of JSON `lines`, validation failures, polling failure/timeout, authoritative local overrides, and failure behavior. They do **not** prove the remote Evolus workspace's model configuration or its lack of side effects. Run a live five-case walkthrough separately before recording a demo.

The app and Evolus integration were committed before the submission refresh. At this snapshot, the revised files under `submission/` are untracked. `CHATGPT_HANDOFF.md` also appears as a tracked deletion; that unrelated change has been left untouched. Check `git status --short` before committing. `.env` is ignored and must remain local.

## Boundaries and next work

- Review the revised materials in `submission/current/` before submission. They replace the stale descriptions, diagram, deck, cover, and script directly under `submission/`; the Orbit screenshot is from demo mode. Keep unsupported Qwen/vLLM, Evolus email/ERP, automatic fallback, and measured outcome claims out of the final submission.
- Verify the actual AMD TokenFactory provider/model in the Evolus workspace and capture safe evidence of a meaningful AMD-backed live workflow. The [official event page](https://lablab.ai/ai-hackathons/amd-developer-hackathon-act-iii) requires meaningful AMD work for the main challenge and points participants to TokenFactory. Eligibility is for the organizers to decide. The Evolus partner track additionally specifies a team-owned AMD-hosted vLLM endpoint; the current repository does not establish that requirement.
- Test the Docker image where Docker is available. A full submission also needs a public repository, reachable app URL, demo video, and slides. Do not expose a live app with real invoice data or credentials before adding appropriate access control.
- For product use beyond a controlled demo, add authentication, persistent records, secure reviewer identity, and proper operational controls. The present app has in-memory data and no real payment or ERP integration.

## Copyable request for a new ChatGPT chat

> I am continuing LedgerHawk, an existing FastAPI AP invoice demo. Read `context.md`, `README.md`, `submission/README.md`, and `submission/current/README.md`, then inspect the current code and `git status` before changing anything. Keep the three Evolus workflows, deterministic AP decisions, and existing dashboard. The revised submission materials are in `submission/current/`; verify live AMD TokenFactory evidence and routing behavior, run the five live cases, test Docker, and prepare the video and public demo. Do not read out, change, or commit `.env` or any credential values. Work incrementally, test each change, and distinguish verified behavior from assumptions.
