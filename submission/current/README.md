# LedgerHawk submission package

This `current/` package describes the implemented FastAPI demo. The older files directly under `submission/` are preserved for reference and contain obsolete claims; use the files here for any new presentation. See the repository `README.md` and `context.md` for setup and architecture details.

## What is ready

| Asset | Status |
| --- | --- |
| `lablab-descriptions.md` | Draft copy aligned with the code; review final challenge selection and AMD evidence before pasting. |
| `architecture.svg` | Diagram of the implemented three-workflow pipeline and local controls. |
| `deck.html`, `deck.pdf` | Pitch deck source and export. |
| `cover.html`, `cover.png` | Cover source and export. |
| `dashboard-orbit.png` | Fresh screenshot of the current **demo-mode** dashboard with a synthetic invoice. |
| `demo-script.md` | Shot list and voiceover; the video itself still needs recording. |

## Product claims supported by the repository

- Live mode calls three Evolus REST workflows for PDF extraction, AP assessment, and demo routing. Demo mode uses local simulations. Live errors surface without a simulation fallback.
- Local deterministic checks decide **reject** for duplicates, **escalate** for other high-risk flags, **hold** for other mandatory failures, and **approve** only when checks pass. The assessment decision is overridden when it conflicts.
- The dashboard presents five synthetic invoice scenarios, field-level flags, an in-memory audit ledger, review queue, and vendor/PO records. Vendor-message text is a **draft only**.
- Routing records a demo acknowledgement. LedgerHawk does **not** pay invoices, post to an ERP, or send messages. Its analytics use seeded synthetic records and assumptions; they are not measured business improvements.

The app's `AMD_MODEL_NAME` and visible dashboard chip are **display text**, not proof of model hosting. Before claiming AMD infrastructure use, capture redacted evidence from the Evolus workspace that a meaningful live workflow uses AMD TokenFactory. The main AMD challenge and partner tracks have different criteria; verify the [current event rules](https://lablab.ai/ai-hackathons/amd-developer-hackathon-act-iii) and selected challenge before submitting. No own AMD-hosted vLLM endpoint has been demonstrated for this project.

## Rehearse and verify

From the repository root, use the commands in the main `README.md`. In demo mode, reset the ledger with **Audit → Reset demo data** before each take. Expected results are Northwind **approve**, Orbit **escalate**, Apex **reject**, Helix **hold**, and Brightline **hold**. The screenshot is a demo capture; do not present it as evidence of a live model call.

Offline checks at the time this package was prepared: `.ledgervenv/bin/python test_app.py` printed `ok`; `.ledgervenv/bin/python -m unittest test_workflows.py -q` passed **7 tests**. The repository was clean before these submission files were added. `.env` is ignored and no credential file was staged. Docker was not available in this environment, so the image build is still unverified.

## Manual submission checklist

1. Verify the three remote workflows and their model/provider setting in Evolus; confirm the routing workflow has no email, ERP, payment, or message side effects. Capture **redacted** proof of AMD TokenFactory use if claiming the main AMD technology requirement.
2. Run all five cases in live mode, record the actual responses and latency, and ensure no invoice or credential data appears in public evidence. Do not put real invoices into a public demo.
3. Build and run Docker on a machine with Docker, then deploy a controlled public demo if required by the submission form. The app has no login and its ledger is in memory.
4. Record and review the video using `demo-script.md`; confirm the mode shown on screen, submit the cover and deck, and provide a public repository and working app URL if required.
