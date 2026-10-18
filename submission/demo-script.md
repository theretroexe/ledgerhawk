# LedgerHawk: 2-minute demo video

Target length 1:55–2:00, about 300 words of voiceover at a calm pace. Screen recording at 1920×1080 (or 1440×900), light theme (sun/moon switch top right), browser zoom 100–110%.

## Before you record

- Open **Audit** and click **Reset demo data** (or `POST /api/reset`) before every take. The ledger is in memory: a second run of NW-2291 is caught as a duplicate, and clicking an inbox tile again re-runs that invoice. Never click a tile twice.
- Record against your own server instance if teammates are using the shared one; their runs change the Audit numbers.
- The header shows the model chip (*Qwen2.5-7B-Instruct on AMD Instinct MI300X*) and the mode, **Simulation** or **Live**. Under Simulation, don't say "live" on camera; use the [live] line only if it reads Live.
- Close other tabs, hide bookmarks, turn off notifications. Do one dry run off camera, then reset. Each agent run takes about 3–4 seconds in simulation.
- Expected Audit figures after the five emails: **€39,424 loss prevented**, **€2,550 caught in this session**, €750 held for correction, 70% touchless, 9.8 hours saved, 4 open reviews.

## Shot list and voiceover

Inbox order: Northwind → Orbit → Apex → Helix → Brightline.

| Time | Shot (what is on screen) | Voiceover |
|---|---|---|
| 0:00–0:08 | Deck slide 1, then cut to **Intake**. Hold on the header pitch line "Stops duplicate and fraudulent invoices before payment". | "Accounts-payable teams key supplier invoices by hand, and still pay duplicates and fake bank details. LedgerHawk stops them before payment." |
| 0:08–0:26 | Click **Northwind NW-2291**. The invoice renders as a document ("As read from NW-2291.pdf by the Evolus document extractor"); the Agent run rail ticks through Read the invoice → Check against PO and vendor master → Decide → Write to the vendor → Hand off. Blue ✓ marks fill the margin; blue stamp **Approved for payment**. Point at the model chip in the header. | "An invoice arrives by email. The Evolus document extractor reads it. Eight controls check it against the purchase order and the vendor master, with the evidence in the margin. Then an Evolus agent, running Qwen on an AMD Instinct MI300X through vLLM, makes the call. Clean match: approved for payment." |
| 0:26–0:48 | Click **Orbit OC-3302 "new bank details"**. Hold on the IBAN line: the characters that differ from the vendor master are marked in red in the margin. Red stamp **Stop: verify bank details**. Flip **Document → JSON** for three seconds (extracted fields, controls, the model's decision, the workflow), then back to Document. | "Now the expensive one. A real vendor and a real PO, but the email says the bank account has changed. That's business email compromise. LedgerHawk diffs the IBAN against the vendor master and stops the payment. And every run leaves one record: what was extracted, every control, the model's decision, the workflow it started." |
| 0:48–0:56 | Click **Records**, type **GB33** in the search box: "No vendor matches 'GB33'". Click back to **Intake**. | "Where does that account come from? It isn't in our vendor master at all." |
| 0:56–1:04 | Click **Apex AP-5510 "reminder"**. Red struck-through stamp **Duplicate: do not pay**. | "A second notice for an invoice we paid seventeen days ago. Do not pay." |
| 1:04–1:14 | Click **Helix HX-7781**. Ochre Δ in the margin on the unit price (+10.1% over PO); scroll the rail to the drafted vendor email. Ochre stamp **Hold: query vendor**. | "Helix billed ten percent above the PO. Held, and the Evolus email tool has already written to the vendor." |
| 1:14–1:19 | Click **Brightline BL-0917**. Ochre stamp **Hold: PO required**. | "No purchase order? Held until one is raised." |
| 1:19–1:38 | Click **Audit**. Hold on **€39,424 loss prevented** and the "€2,550 of it caught in this session" chip; pan across held for correction, touchless and time saved. Click the **Bank details changed** bar under "Why invoices were stopped": the audit log filters to those rows. | "The controller sees the result. Loss prevented counts only duplicates and suspected fraud, two and a half thousand euros from this session alone. Variances are held for correction, not counted as loss. Seventy percent of invoices never needed a person, and every decision is in the audit log, one click away." |
| 1:38–1:52 | In **Waiting for a person**, click **Review** on OC-3302. Type a reviewer name and a reason, tick the call-back attestation; **Release for payment** stays disabled until all three are filled. Click it. | "Releasing a stopped payment is a control too: a name, a reason, and a call-back on the number already in the vendor master." |
| 1:52–2:00 | Deck slide 8 (the struck-through stamp re-stamped "Released for payment"), end on slide 1. | "The model can be stricter than our controls, never looser. LedgerHawk: Evolus building blocks, an open model on AMD, fewer bad payments." |

**[live] line for 0:08–0:26:** if the mode reads **Live**, point at the step timings in the Agent run rail while saying "running Qwen on an AMD Instinct MI300X". Under Simulation the rail reads "simulated"; keep the architecture wording and don't say "live".

**After the 1:38 release**, loss prevented drops by €1,410, because a verified release no longer counts as a stopped payment. That's expected; don't re-record because of it.

## Editing notes

- Lower-third captions on each rail step with the Evolus block: *Document extractor*, *Agent + knowledge library*, *AI Tool: email*, *Workflows*.
- Let every stamp land on screen; never cut the stamp animation.
- Zoom in during editing on the IBAN margin diff (~0:32), the JSON `"decision"` block (~0:44) and the call-back checkbox (~1:46).
- On-screen text at 1:19: "Demo data: 30-day synthetic ledger + 5 demo emails. Time saved assumes 12 min of manual handling per invoice."
- No music under the Orbit segment.
- Export 1080p MP4 (H.264), upload to YouTube as unlisted, paste the link into lablab.ai.
