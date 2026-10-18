# LedgerHawk ChatGPT Handoff

For the complete architecture, API map, workflow contracts, and project status, read `context.md`.

## Opening prompt for the next chat

> Continue the existing LedgerHawk project in `ledgerhawk/`. Read `context.md`, this handoff, `README.md`, `app.py`, `evolus_workflows.py`, `ap_policy.md`, and the tests before changing anything. The three Evolus workflows are integrated and the FastAPI dashboard works. First verify the current state, then refresh the stale submission materials to match the real product. Preserve the deterministic AP decisions and live/demo modes. Never print, paste, modify, or commit `.env` or credentials. Make small changes and report tests accurately.

## Current product

LedgerHawk is a FastAPI accounts-payable **demo**. `app.py` serves the existing `index.html` dashboard, sample PDF invoices, a review queue, records, and an in-memory audit ledger. `ap_policy.md` supplies policy text. `evolus_workflows.py` starts and polls the three Evolus workflows and validates their outputs; `test_app.py` and `test_workflows.py` cover offline behavior. The app does not make payments, post to an ERP, or send emails or messages. Vendor-message text is a draft for display only.

In **live** mode, the extraction workflow receives a PDF as multipart `file`; the assessment workflow receives the invoice, matched PO, vendor master entry, deterministic flags, and policy as multipart `input`; the routing workflow receives the locally validated decision and invoice summary as multipart `input` and returns a demo-only acknowledgement. The app uses `X-ApiKey` and `X-Application-Id` against `https://api.evolus.ai`. It surfaces live workflow failures instead of switching to simulation. In **demo** mode, the bundled samples use local simulations.

Local checks are authoritative: duplicate invoice → **reject**; other high-risk flag → **escalate**; other mandatory failure → **hold**; all checks pass → **approve**. The five bundled cases are Northwind (`northwind-clean`) **approve**, Orbit (`orbit-bank`) **escalate**, Apex (`apex-duplicate`) **reject**, Helix (`helix-price`) **hold**, and Brightline (`brightline-nopo`) **hold**. Use **Reset demo data** before a repeat run because later processing of the same invoice becomes a duplicate.

## Run and verify

From `ledgerhawk/`, install `requirements.txt` in a virtual environment, then run `python app.py` and open `http://localhost:8000`. `LEDGERHAWK_MODE=demo` needs no Evolus credentials. For live mode, use the locally ignored `.env` with these **variable names only**: `LEDGERHAWK_MODE`, `EVOLUS_BASE_URL`, `EVOLUS_API_KEY`, `EVOLUS_APPLICATION_ID`, `EVOLUS_WORKFLOW_EXTRACT_ID`, `EVOLUS_WORKFLOW_ASSESS_ID`, `EVOLUS_WORKFLOW_ROUTE_ID`, and `AMD_MODEL_NAME`. The last variable changes only the dashboard label; it does not configure the remote model. See `.env.example` and `README.md` for setup.

Offline verification on 2026-10-18: `.ledgervenv/bin/python test_app.py` printed `ok`; `.ledgervenv/bin/python -m unittest test_workflows.py -q` passed **7 tests**. If using a new environment, substitute its Python path. Docker is not installed in this workspace, so the image build has not been verified here. Rerun the live five-case walkthrough before recording or submitting.

## Handoff status and next tasks

The Evolus integration is **uncommitted** in the nested `ledgerhawk/` Git repository. Review `git status --short` before committing; existing modified files include the app, README, policy, Dockerfile, frontend, and tests, with `evolus_workflows.py` and `test_workflows.py` still untracked at handoff. `.env` is ignored and must stay local.

The tracked `submission/` deck, cover, screenshots, written descriptions, and video script are **stale**. They describe an old Qwen/vLLM, Evolus email/ERP, and automatic fallback design, and include figures that should not be presented as measured outcomes. Refresh these assets from the current UI and actual workflow behavior; keep the old assets untouched until replacements are ready.

For an AMD main-challenge submission, show evidence that a meaningful live workload actually runs through AMD TokenFactory in the Evolus workspace; `AMD_MODEL_NAME` alone is only a label. The workspace configuration cannot be proven from this repository. The Evolus partner track separately requires the team's own AMD-hosted vLLM endpoint, which this integration does not establish. Check the [official event rules](https://lablab.ai/ai-hackathons/amd-developer-hackathon-act-iii) before making eligibility claims. After updating the demo materials, test Docker where available and plan the public repository, app URL, video, and slides required for a submission. The current app has no login and its ledger is in memory, so keep it scoped to a controlled demo.
