# LedgerHawk demo script

Target a concise recorded walkthrough. The timing below fits **demo mode**; live workflow latency varies, so allow time or edit pauses honestly. Use synthetic sample PDFs only.

## Before recording

1. Open **Audit → Reset demo data**. Repeating an invoice without a reset creates a duplicate result.
2. Show the header mode. Say **demo** for local simulations; say **live** only when the UI shows Live and all three Evolus workflows actually complete. The model chip is a configurable label, not proof of the remote provider.
3. Keep credentials and the Evolus workspace secret values off screen. Record a separate, redacted workspace evidence clip if making an AMD TokenFactory claim.

## Shot list and narration

| Approx. time | Screen action | Suggested narration |
| --- | --- | --- |
| 0:00–0:12 | Open Intake and show the five synthetic invoice tiles. | “LedgerHawk is a working invoice review demo for AP clerks and controllers. Each invoice gets a decision with the checks visible.” |
| 0:12–0:35 | Run **Northwind NW-2291**. Show the document, check marks, and approved stamp. | “The PDF is extracted, matched to the purchase order and vendor master, and approved when every mandatory check passes.” |
| 0:35–1:00 | Run **Orbit OC-3302**. Zoom to the invoice IBAN, vendor-master comparison, and red escalation stamp. | “Orbit's bank account differs from the record on file. The local policy escalates it for controller review, regardless of the assessment workflow's proposed decision.” |
| 1:00–1:20 | Show **Apex AP-5510**, then **Helix HX-7781** and **Brightline BL-0917**. | “A prior invoice number is rejected as a duplicate. A price over the PO tolerance and an invoice without a PO are held for correction.” |
| 1:20–1:42 | Switch to JSON and the run rail; point to extraction, local checks, assessment, and demo routing acknowledgement. | “In live mode three Evolus workflows handle extraction, assessment, and a demo-only route. The final decision is calculated locally. Draft vendor text is displayed but never sent.” |
| 1:42–2:02 | Open Audit and its review queue. Show the reviewer fields and call-back attestation without submitting a fictional verification. | “A person can review an exception. Releasing a high-risk item requires a name, reason, and confirmation of a call-back using the number already on file.” |
| 2:02–2:15 | End on the architecture slide or cover. | “LedgerHawk makes invoice mismatches visible and leaves a reviewable record. It does not move money or post to an ERP.” |

## Accuracy checks for the edit

- Caption the mode visible in the recording. If recorded in demo mode, use “simulated extraction/assessment/routing” in the video. Do not imply the screen demonstrates a live AMD model call.
- Do not cite the seeded Audit totals as losses prevented, hours saved, customer outcomes, or measured ROI. They are illustrative calculations based on synthetic data.
- Never say a vendor email was sent, an ERP was updated, a payment was made, or a callback actually occurred. The UI supports only a display draft, demo acknowledgement, and reviewer attestation.
- If showing AMD TokenFactory, add separate redacted proof of the Evolus workspace model/provider configuration and a live workflow run. Verify the selected challenge's rules before using partner-track wording.
