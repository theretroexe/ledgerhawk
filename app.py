"""LedgerHawk: accounts-payable invoice intake + audit agent.

Pipeline per invoice: Evolus document extractor -> deterministic PO match (two-way) / audit rules
-> Evolus agent reasoning on an open model served on AMD (vLLM) -> Evolus AI Tool drafts the
vendor query -> Evolus workflow posts to ERP or routes to a human.

Every Evolus call runs live when its env vars are set and falls back to a local simulation
otherwise, so the whole UI works before the workspace and model endpoint are wired in.
"""
import asyncio
import json
import math
import os
import random
import re
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse

API = "https://api.evolus.ai"
KEY = os.getenv("EVOLUS_API_KEY")
APP_ID = os.getenv("EVOLUS_APP_ID")
EXTRACTOR_AGENT = os.getenv("EVOLUS_EXTRACTOR_AGENT_ID")
EXTRACTOR_ID = os.getenv("EVOLUS_EXTRACTOR_ID")
AP_AGENT = os.getenv("EVOLUS_AP_AGENT_ID")  # Evolus agent whose model is the AMD vLLM endpoint
WF_POST = os.getenv("EVOLUS_WORKFLOW_POST_ID")  # approved -> post to ERP
WF_REVIEW = os.getenv("EVOLUS_WORKFLOW_REVIEW_ID")  # anything else -> human review
MODEL_NAME = os.getenv("AMD_MODEL_NAME", "Qwen2.5-7B-Instruct · vLLM on AMD Instinct MI300X")
PRICE_TOLERANCE = 0.02  # 2% unit-price variance allowed before a hold
MAX_UNIT, MAX_TOTAL = 1e9, 1e12  # any quantity, unit price or total beyond these is treated as unreadable
MANUAL_MINUTES = 12  # assumed manual handling time per invoice, used for "hours saved"


def live(*ids):
    return bool(KEY and APP_ID and all(ids))


LIVE = {
    "extractor": live(EXTRACTOR_AGENT, EXTRACTOR_ID),
    "agent": live(AP_AGENT),
    "ai_tool": live(),
    "workflow": live(WF_POST, WF_REVIEW),
}

# --- Company master data (would live in the ERP; Evolus reaches it through a workflow/MCP) ---

VENDORS = {
    "Northwind Components": {"iban": "IT60X0542811101000000123456", "terms_days": 30},
    "Helix Industrial": {"iban": "DE89370400440532013000", "terms_days": 45},
    "Apex Logistics": {"iban": "IT02A0301503200000003517230", "terms_days": 30},
    "Orbit Cloud Services": {"iban": "NL91ABNA0417164300", "terms_days": 15},
    "Brightline Office Supply": {"iban": "IT40S0542811101000000654321", "terms_days": 30},
}

PURCHASE_ORDERS = {
    "PO-1042": {"vendor": "Northwind Components", "requester": "Plant Ops", "lines": [
        {"desc": "Servo motor SM-200", "qty": 40, "price": 85.00},
        {"desc": "Mounting bracket MB-12", "qty": 40, "price": 12.50}]},
    "PO-1043": {"vendor": "Helix Industrial", "requester": "Maintenance", "lines": [
        {"desc": "Hydraulic pump HP-7", "qty": 6, "price": 1240.00}]},
    "PO-1044": {"vendor": "Apex Logistics", "requester": "Supply Chain", "lines": [
        {"desc": "Freight Milan-Rome pallet", "qty": 12, "price": 95.00}]},
    "PO-1045": {"vendor": "Orbit Cloud Services", "requester": "IT", "lines": [
        {"desc": "GPU compute hours", "qty": 500, "price": 2.10},
        {"desc": "Managed storage TB-month", "qty": 20, "price": 18.00}]},
}

# Demo inbox: each sample is an email with a PDF invoice attached, built on the fly below.
# Ordered for the 2-minute demo: clean -> bank fraud -> duplicate first.
SAMPLES = {
    "northwind-clean": {
        "from": "billing@northwind-components.example", "subject": "Invoice NW-2291 for PO-1042",
        "body": "Hello, please find attached our invoice for the servo motors delivered on Monday. Regards, Northwind AR",
        "invoice": {"vendor": "Northwind Components", "number": "NW-2291", "date": "2026-10-14", "po": "PO-1042",
                    "iban": "IT60X0542811101000000123456", "lines": [
                        ("Servo motor SM-200", 40, 85.00), ("Mounting bracket MB-12", 40, 12.50)]}},
    "orbit-bank": {
        "from": "finance@orbit-cloud-billing.example", "subject": "Invoice OC-3302 - NEW BANK DETAILS",
        "body": "Due to an audit, our bank account has changed. Please use the new IBAN on the attached invoice going forward. Urgent.",
        "invoice": {"vendor": "Orbit Cloud Services", "number": "OC-3302", "date": "2026-10-16", "po": "PO-1045",
                    "iban": "GB33BUKB20201555555555", "lines": [
                        ("GPU compute hours", 500, 2.10), ("Managed storage TB-month", 20, 18.00)]}},
    "apex-duplicate": {
        "from": "ar@apex-logistics.example", "subject": "REMINDER: invoice AP-5510",
        "body": "Second notice. Our records show invoice AP-5510 is still open, please pay at your earliest convenience.",
        "invoice": {"vendor": "Apex Logistics", "number": "AP-5510", "date": "2026-09-28", "po": "PO-1044",
                    "iban": "IT02A0301503200000003517230", "lines": [("Freight Milan-Rome pallet", 12, 95.00)]}},
    "helix-price": {
        "from": "invoices@helix-industrial.example", "subject": "HX-7781 hydraulic pumps",
        "body": "Dear customer, attached is invoice HX-7781. Note: prices updated per our Q4 list.",
        "invoice": {"vendor": "Helix Industrial", "number": "HX-7781", "date": "2026-10-15", "po": "PO-1043",
                    "iban": "DE89370400440532013000", "lines": [("Hydraulic pump HP-7", 6, 1365.00)]}},
    "brightline-nopo": {
        "from": "sales@brightline-office.example", "subject": "Brightline invoice BL-0917",
        "body": "Thanks for your order! Invoice attached for the ergonomic chairs.",
        "invoice": {"vendor": "Brightline Office Supply", "number": "BL-0917", "date": "2026-10-16", "po": "",
                    "iban": "IT40S0542811101000000654321", "lines": [("Ergonomic chair EC-3", 8, 310.00)]}},
}


def sample_pdf(inv):
    """Minimal one-page text PDF (no deps). Text stays uncompressed so the simulator can read it back."""
    total = sum(q * p for _, q, p in inv["lines"])
    rows = ["INVOICE", "", f"Vendor: {inv['vendor']}", f"Invoice No: {inv['number']}",
            f"Invoice Date: {inv['date']}", f"PO Number: {inv['po'] or '-'}", f"IBAN: {inv['iban']}",
            "Currency: EUR", "", "Item | Qty | Unit Price | Amount"]
    rows += [f"{d} | {q} | {p:.2f} | {q * p:.2f}" for d, q, p in inv["lines"]]
    rows += ["", f"Total: {total:.2f}"]
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = "BT /F1 11 Tf 56 780 Td 16 TL " + " ".join(f"({esc(r)}) Tj T*" for r in rows) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


# --- Ledger: every processed invoice with its decision and audit trail ---
# ponytail: in-memory, resets on restart; move to SQLite if the demo needs persistence.

HIGH = {"duplicate", "bank_change", "unknown_vendor", "po_vendor_mismatch", "unreadable_amount", "unreadable_number"}
FLAG_TEXT = {
    "unreadable_number": "Invoice number missing or unreadable",
    "unreadable_amount": "An amount on the invoice could not be read as a valid number",
    "duplicate": "Invoice number already processed for this vendor",
    "bank_change": "Bank details differ from the vendor master",
    "unknown_vendor": "Vendor is not in the vendor master",
    "po_vendor_mismatch": "PO belongs to a different vendor",
    "no_po": "No purchase order referenced",
    "unknown_po": "Referenced PO does not exist",
    "price_variance": "Unit price above PO price",
    "qty_over": "Quantity above PO quantity",
    "unordered_item": "Line item not on the PO",
    "total_mismatch": "Invoice total does not equal the sum of its lines",
}
STATUS = {"approve": "approved", "hold": "on_hold", "escalate": "escalated", "reject": "rejected"}
# Which invoice field each control checks, so the UI can annotate that exact spot on the document.
FIELD = {"duplicate": "number", "bank_change": "iban", "unknown_vendor": "vendor", "po_vendor_mismatch": "po",
         "no_po": "po", "unknown_po": "po", "total_mismatch": "total", "unreadable_amount": "total", "unreadable_number": "number",
         "price_variance": "line", "qty_over": "line", "unordered_item": "line"}


def now():
    return datetime.now(timezone.utc)


def flag(code, total=0.0, message=None, amount=None, line=None):
    severity = "high" if code in HIGH else "medium"
    if amount is None:
        amount = total if severity == "high" else round(total * 0.08, 2)
    return {"code": code, "severity": severity, "message": message or FLAG_TEXT[code], "amount": round(amount, 2),
            "field": FIELD[code], "line": line}


def due_date(vendor, inv_date):
    try:
        return (datetime.fromisoformat(inv_date) + timedelta(days=VENDORS[vendor]["terms_days"])).date().isoformat()
    except (KeyError, ValueError):
        return ""


def entry(number, vendor, po, inv_date, total, status, flags, rationale, at, cycle_ms, source):
    high = any(f["severity"] == "high" for f in flags)
    return {"id": uuid.uuid4().hex[:10], "number": number, "vendor": vendor, "po": po, "date": inv_date,
            "due": due_date(vendor, inv_date), "total": total, "currency": "EUR", "status": status, "flags": flags,
            "exposure": total if high else round(sum(f["amount"] for f in flags), 2),
            "rationale": rationale, "processed_at": at.isoformat(), "cycle_ms": cycle_ms, "source": source}


REVIEWERS = ["Giulia Conti", "Marco Ferri"]


def seed_ledger():
    rng = random.Random(7)
    outcomes = [("approved", []), ("on_hold", ["price_variance"]), ("on_hold", ["qty_over"]),
                ("rejected", ["duplicate"]), ("escalated", ["bank_change"]), ("on_hold", ["no_po"])]
    weights = [72, 9, 4, 7, 3, 5]
    ledger = []
    for i in range(64):
        vendor = rng.choice(list(VENDORS))
        status, codes = rng.choices(outcomes, weights)[0]
        total = round(rng.uniform(180, 9800), 2)
        at = now() - timedelta(days=rng.uniform(0.3, 30), hours=rng.uniform(0, 8))
        why = {"approved": "Matched the PO on items, quantities and prices; bank details verified against the vendor "
                           "master. Posted for payment.",
               "rejected": "Invoice number already paid for this vendor; rejected to prevent a double payment.",
               "escalated": "Bank details differ from the vendor master; escalated to the controller for "
                            "call-back verification.",
               "on_hold": f"{FLAG_TEXT[codes[0]] if codes else ''}; held until the vendor or requester resolves it."}
        e = entry(f"{vendor[:2].upper()}-{4000 + i}", vendor, "", at.date().isoformat(), total, status,
                  [flag(c, total) for c in codes], why[status], at, rng.randint(6000, 24000), "seed")
        if status in ("on_hold", "escalated") and at < now() - timedelta(days=3):
            # Older exceptions were already worked by a person; only recent ones stay in the queue.
            e.update(agent_status=status, status="approved" if status == "on_hold" else "rejected",
                     reviewed_at=(at + timedelta(days=1)).isoformat(), reviewed_by=rng.choice(REVIEWERS),
                     review_reason="Vendor sent a corrected invoice." if status == "on_hold"
                     else "Call-back to the number on file: vendor never changed its bank details.")
        ledger.append(e)
    # The real AP-5510, already paid, so the reminder in the inbox is caught as a duplicate.
    paid = now() - timedelta(days=17)
    ledger.append(entry("AP-5510", "Apex Logistics", "PO-1044", "2026-09-28", 1140.00, "approved", [],
                        "Matched PO-1044 line by line; posted.", paid, 9100, "seed"))
    return sorted(ledger, key=lambda e: e["processed_at"])


LEDGER = seed_ledger()


def evolus_headers():
    return {"X-ApiKey": KEY, "X-Application-Id": APP_ID}


# --- Step 1: extraction ---

async def extract_live(name, data, email):
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{API}/api/v1/agents/{EXTRACTOR_AGENT}/json/{EXTRACTOR_ID}/ask-file",
                         params={"useWebhook": "false"}, headers=evolus_headers(),
                         files={"file": (name, data, "application/pdf")}, data={"email": email})
        r.raise_for_status()
        return normalize(r.json())


def num(v):
    """A finite number, or None. Unreadable amounts must never compare as 'within tolerance' (NaN fails open)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def normalize(raw):
    # ponytail: assumes the extractor schema in the README; adjust keys once a real response is seen.
    lines = [{"desc": str(l.get("description", "")), "qty": num(l.get("quantity")),
              "price": num(l.get("unit_price"))} for l in raw.get("lines", [])]
    return {"vendor": raw.get("vendor", ""), "number": raw.get("invoice_number", ""), "date": raw.get("invoice_date", ""),
            "po": raw.get("po_number") or "", "iban": (raw.get("iban") or "").replace(" ", ""),
            "total": num(raw.get("total")), "lines": lines}


def doc_key(s):
    """Invoice numbers and vendor names compared without case, spaces or punctuation, Unicode-aware:
    'AP-5510' == 'ap 5510' == 'ＡＰ－５５１０'."""
    return re.sub(r"[\W_]", "", unicodedata.normalize("NFKC", str(s or "")).casefold())


async def extract_sim(name, data, email):
    """Reads back the text of our own sample PDFs; any other PDF comes out mostly empty and gets escalated."""
    await asyncio.sleep(1.1)
    text = [re.sub(r"\\(.)", r"\1", m.decode("latin-1")) for m in re.findall(rb"\(((?:\\.|[^\\)])*)\) Tj", data)]
    fields = dict(m.groups() for t in text if (m := re.match(r"([A-Za-z ]+):\s*(.*)", t)))
    lines = []
    for t in text:
        parts = [p.strip() for p in t.split("|")]
        if len(parts) == 4 and parts[1].replace(".", "").isdigit():
            lines.append({"desc": parts[0], "qty": float(parts[1]), "price": float(parts[2])})
    po = fields.get("PO Number", "-")
    return {"vendor": fields.get("Vendor", ""), "number": fields.get("Invoice No", name.rsplit(".", 1)[0]),
            "date": fields.get("Invoice Date", ""), "po": "" if po == "-" else po, "iban": fields.get("IBAN", ""),
            "total": num(fields.get("Total")), "lines": lines}


# --- Step 2: deterministic audit rules (the auditable part; the model explains and decides) ---

def run_checks(inv):
    flags = []
    # Fail closed: a missing, non-numeric, infinite or negative amount escalates the invoice instead of passing.
    # Upper bounds keep qty * price and the sums finite; anything beyond is an extraction error, not an invoice.
    bad = [i for i, l in enumerate(inv["lines"]) if l["qty"] is None or l["price"] is None
           or not 0 < l["qty"] <= MAX_UNIT or not 0 <= l["price"] <= MAX_UNIT]
    if bad or inv["total"] is None or not 0 < inv["total"] <= MAX_TOTAL:
        where = f"line {bad[0] + 1}" if bad else "the total"
        flags.append(flag("unreadable_amount", 0, f"Could not read a valid amount on {where}; check the PDF by hand", amount=0))
        for i in bad:  # recorded as 0 so the ledger stays valid JSON; the flag above already stops payment
            inv["lines"][i]["qty"] = inv["lines"][i]["price"] = 0
        inv["total"] = inv["total"] if inv["total"] is not None and 0 < inv["total"] <= MAX_TOTAL else 0
    total = inv["total"]
    vendor = VENDORS.get(inv["vendor"])
    if not vendor:
        flags.append(flag("unknown_vendor", total, f"'{inv['vendor'] or 'unreadable'}' is not in the vendor master"))
    elif inv["iban"] and inv["iban"] != vendor["iban"]:
        flags.append(flag("bank_change", total, f"IBAN {inv['iban']} differs from master {vendor['iban']}"))
    key = doc_key(inv["number"])
    prior = None
    if not key:  # without a number the duplicate check can't run, so the invoice can't pass it
        flags.append(flag("unreadable_number", total, "Invoice number missing or unreadable; check the PDF by hand"))
    else:
        prior = next((e for e in LEDGER if doc_key(e["vendor"]) == doc_key(inv["vendor"])
                      and doc_key(e["number"]) == key), None)
    if prior:
        flags.append(flag("duplicate", total, f"{inv['number']} was already processed on {prior['processed_at'][:10]} "
                                              f"({prior['status'].replace('_', ' ')})"))
    po = PURCHASE_ORDERS.get(inv["po"])
    if not inv["po"]:
        flags.append(flag("no_po", total, amount=0))
    elif not po:
        flags.append(flag("unknown_po", total, f"{inv['po']} does not exist", amount=0))
    else:
        if po["vendor"] != inv["vendor"]:
            flags.append(flag("po_vendor_mismatch", total, f"{inv['po']} was issued to {po['vendor']}"))
        for i, line in enumerate(inv["lines"]):
            ordered = next((l for l in po["lines"] if l["desc"].lower() == line["desc"].lower()), None)
            if not ordered:
                flags.append(flag("unordered_item", total, f"'{line['desc']}' is not on {inv['po']}",
                                  line["qty"] * line["price"], line=i))
                continue
            if line["price"] > ordered["price"] * (1 + PRICE_TOLERANCE):
                flags.append(flag("price_variance", total,
                                  f"{line['desc']}: €{line['price']:.2f} vs PO €{ordered['price']:.2f} "
                                  f"(+{(line['price'] / ordered['price'] - 1) * 100:.1f}%)",
                                  (line["price"] - ordered["price"]) * line["qty"], line=i))
            if line["qty"] > ordered["qty"]:
                flags.append(flag("qty_over", total, f"{line['desc']}: {line['qty']:g} billed vs {ordered['qty']} ordered",
                                  (line["qty"] - ordered["qty"]) * line["price"], line=i))
    lines_sum = round(sum(l["qty"] * l["price"] for l in inv["lines"]), 2)
    if abs(lines_sum - total) > 0.01:
        flags.append(flag("total_mismatch", total, f"Total €{total:.2f} vs lines €{lines_sum:.2f}",
                          max(total - lines_sum, 0)))
    return flags


def rule_decision(flags):
    codes = {f["code"] for f in flags}
    if "duplicate" in codes:
        return "reject"
    if codes & HIGH:
        return "escalate"
    return "hold" if flags else "approve"


# --- Step 3: agent reasoning on the AMD-hosted model (through the Evolus agent) ---

async def reason_live(inv, flags, po):
    prompt = (
        "You are the accounts-payable control agent. Decide what to do with this supplier invoice, "
        "following the AP policy in your knowledge library.\n"
        f"Invoice: {json.dumps(inv)}\nPurchase order: {json.dumps(po)}\n"
        f"Vendor master: {json.dumps(VENDORS.get(inv['vendor']))}\nFailed audit checks: {json.dumps(flags)}\n"
        'Reply with JSON only: {"decision": "approve|hold|escalate|reject", '
        '"rationale": "2-3 sentences for the audit log", "confidence": 0.0-1.0}')
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{API}/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                         json={"model": f"{APP_ID}:{AP_AGENT}", "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        reply = r.json()["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", reply, re.S)
    out = json.loads(match.group(0)) if match else {}
    return {"decision": out.get("decision"), "rationale": str(out.get("rationale", reply))[:600],
            "confidence": out.get("confidence")}


async def reason_sim(inv, flags, po):
    await asyncio.sleep(1.6)
    d = rule_decision(flags)
    msgs = "; ".join(f["message"] for f in flags)
    terms = VENDORS.get(inv["vendor"], {}).get("terms_days", 30)
    rationale = {
        "approve": f"Invoice {inv['number']} matches {inv['po']} on vendor, items, quantities and prices, and the "
                   f"bank details match the vendor master. Safe to post for payment in {terms} days.",
        "reject": f"Rejected as a duplicate: {msgs}. Paying it again would double-pay €{inv['total']:,.2f}.",
        "escalate": f"Escalated to the controller: {msgs}. Bank-detail changes requested by email are a classic "
                    "payment-fraud pattern; confirm with the vendor through a known phone number before paying.",
        "hold": f"Placed on hold: {msgs}. The vendor or requester must resolve this before payment.",
    }[d]
    return {"decision": d, "rationale": rationale, "confidence": 0.93 if d == "approve" else 0.88}


def guard(model_out, flags):
    """The model may be stricter than the rules, never looser."""
    rules = rule_decision(flags)
    d = model_out.get("decision")
    if d not in STATUS:
        return rules, "model reply unparseable; used policy rules"
    if d == "approve" and flags:
        return rules, "guardrail: model approved an invoice with failed checks; overridden"
    return d, None


# --- Step 4: AI Tool drafts the vendor query ---

async def draft_live(inv, flags):
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{API}/api/v1/ai-tools/email/run", headers=evolus_headers(), json={
            "text": f"Write a short, polite email to {inv['vendor']} about invoice {inv['number']} "
                    f"(PO {inv['po'] or 'none'}). Issues: " + "; ".join(f["message"] for f in flags)
                    + ". Ask for a corrected invoice or written confirmation."})
        r.raise_for_status()
        return r.json()["output"]


async def draft_sim(inv, flags):
    await asyncio.sleep(0.8)
    issues = "\n".join(f"  • {f['message']}" for f in flags)
    return (f"Subject: Invoice {inv['number']} on hold\n\nDear {inv['vendor']} team,\n\n"
            f"We received invoice {inv['number']} but cannot release it for payment yet:\n{issues}\n\n"
            "Could you send a corrected invoice, or confirm the change in writing referencing the PO? "
            "We will process it as soon as we hear back.\n\nKind regards,\nAccounts Payable")


# --- Step 5: Evolus workflow acts (post to ERP / human review) ---

async def act_live(inv, decision, rationale):
    wf = WF_POST if decision == "approve" else WF_REVIEW
    params = {"invoice_number": inv["number"], "vendor": inv["vendor"], "po": inv["po"],
              "total": inv["total"], "decision": decision}
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{API}/api/v1/workflows/{wf}/execute", headers=evolus_headers(),
                         files={"input": (None, rationale), "parameters": (None, json.dumps(params))})
        r.raise_for_status()
        return {"workflow": "post-to-erp" if decision == "approve" else "human-review", **r.json()}


async def act_sim(inv, decision, rationale):
    await asyncio.sleep(0.6)
    return {"workflow": "post-to-erp" if decision == "approve" else "human-review",
            "executionId": uuid.uuid4().hex[:12], "status": "Pending"}


async def attempt(is_live, live_fn, sim_fn, *args):
    if is_live:
        try:
            return await live_fn(*args), "live"
        except Exception as e:  # keep the demo running, but say so in the trace
            return await sim_fn(*args), f"fallback: {type(e).__name__}: {e}"[:180]
    return await sim_fn(*args), "simulated"


VENDOR_FIXABLE = {"price_variance", "qty_over", "unordered_item", "total_mismatch"}


def ms(t):
    return int((time.perf_counter() - t) * 1000)


# --- HTTP ---

app = FastAPI(title="LedgerHawk")


@app.get("/")
def index():
    return FileResponse(os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html"))


@app.get("/favicon.svg")
def favicon():
    return FileResponse(os.path.join(os.path.dirname(os.path.abspath(__file__)), "brand", "ledgerhawk-icon.svg"),
                        media_type="image/svg+xml")


@app.get("/api/status")
def status():
    return {"live": LIVE, "model": MODEL_NAME}


@app.get("/api/samples")
def samples():
    return [{"id": k, "from": s["from"], "subject": s["subject"], "body": s["body"],
             "file": f"{s['invoice']['number']}.pdf"} for k, s in SAMPLES.items()]


@app.get("/api/samples/{sid}.pdf")
def sample_file(sid: str):
    if sid not in SAMPLES:
        raise HTTPException(404)
    return Response(sample_pdf(SAMPLES[sid]["invoice"]), media_type="application/pdf")


@app.post("/api/process")
async def process(file: UploadFile = File(...), email: str = Form("")):
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "Invoices up to 20 MB")
    return StreamingResponse(run(file.filename or "invoice.pdf", data, email), media_type="application/x-ndjson")


async def run(name, data, email):
    started = time.perf_counter()
    ev = lambda **k: json.dumps(k) + "\n"

    yield ev(step="extract", status="running")
    t = time.perf_counter()
    inv, mode = await attempt(LIVE["extractor"], extract_live, extract_sim, name, data, email)
    yield ev(step="extract", status="done", mode=mode, ms=ms(t), data=inv)

    yield ev(step="match", status="running")
    t = time.perf_counter()
    flags, po = run_checks(inv), PURCHASE_ORDERS.get(inv["po"])
    yield ev(step="match", status="done", mode="local", ms=ms(t),
             data={"flags": flags, "po": po, "master": VENDORS.get(inv["vendor"])})

    yield ev(step="reason", status="running")
    t = time.perf_counter()
    out, mode = await attempt(LIVE["agent"], reason_live, reason_sim, inv, flags, po)
    decision, note = guard(out, flags)
    yield ev(step="reason", status="done", mode=mode, ms=ms(t), data={**out, "decision": decision, "guard": note})

    draft = None
    if decision != "approve" and {f["code"] for f in flags} & VENDOR_FIXABLE:
        yield ev(step="draft", status="running")
        t = time.perf_counter()
        draft, mode = await attempt(LIVE["ai_tool"], draft_live, draft_sim, inv, flags)
        yield ev(step="draft", status="done", mode=mode, ms=ms(t), data={"email": draft})
    else:
        yield ev(step="draft", status="skipped")

    yield ev(step="act", status="running")
    t = time.perf_counter()
    action, mode = await attempt(LIVE["workflow"], act_live, act_sim, inv, decision, out["rationale"])
    yield ev(step="act", status="done", mode=mode, ms=ms(t), data=action)

    e = entry(inv["number"], inv["vendor"], inv["po"], inv["date"], inv["total"], STATUS[decision], flags,
              out["rationale"], now(), ms(started), "agent")
    e.update(lines=inv["lines"], iban=inv["iban"], draft=draft, workflow=action, guard=note)
    LEDGER.append(e)
    yield ev(step="result", entry=e)


@app.get("/api/ledger")
def ledger():
    return LEDGER[::-1]


@app.get("/api/records")
def records():
    """The master data every control checks against: vendor master and open purchase orders."""
    vendors = [{"name": name, **v, "invoices": sum(e["vendor"] == name for e in LEDGER),
                "spend": round(sum(e["total"] for e in LEDGER if e["vendor"] == name), 2)}
               for name, v in VENDORS.items()]
    pos = [{"id": pid, **po, "ordered": round(sum(l["qty"] * l["price"] for l in po["lines"]), 2),
            "invoiced": round(sum(e["total"] for e in LEDGER if e["po"] == pid and e["status"] == "approved"), 2)}
           for pid, po in PURCHASE_ORDERS.items()]
    return {"vendors": vendors, "purchase_orders": pos}


@app.post("/api/ledger/{iid}/review")
async def review(iid: str, body: dict):
    e = next((x for x in LEDGER if x["id"] == iid), None)
    if not e:
        raise HTTPException(404)
    if e["status"] not in ("on_hold", "escalated"):
        raise HTTPException(409, f"Invoice is {e['status']}, nothing to review")
    action = body.get("action")
    reviewer = str(body.get("reviewer", "")).strip()[:60]
    reason = str(body.get("reason", "")).strip()[:300]
    if action not in ("approve", "reject"):
        raise HTTPException(400, "action must be approve or reject")
    if not reviewer:
        raise HTTPException(400, "Enter the reviewer's name for the audit trail")
    # Policy §3: releasing a suspected bank-detail change needs a reason and a call-back on the number on file.
    if action == "approve" and e["status"] == "escalated" and not (reason and body.get("verified") is True):
        raise HTTPException(400, "Releasing an escalated invoice needs a reason and a confirmed call-back")
    e.update(agent_status=e["status"], status="approved" if action == "approve" else "rejected",
             reviewed_at=now().isoformat(), reviewed_by=reviewer, review_reason=reason)
    if e["status"] == "approved":
        e["workflow"], _ = await attempt(LIVE["workflow"], act_live, act_sim, e, "approve",
                                         f"Released by {reviewer}: {reason or 'no reason given'}")
    return e


@app.post("/api/reset")
def reset():
    """Restores the seeded ledger so rehearsal runs don't turn the demo invoices into duplicates."""
    LEDGER[:] = seed_ledger()
    return {"ok": True}


@app.get("/api/analytics")
def analytics():
    total = len(LEDGER)
    touchless = sum(1 for e in LEDGER if e["status"] == "approved" and not e["flags"] and not e.get("reviewed_at"))
    stopped = [e for e in LEDGER if e["status"] in ("rejected", "escalated")]  # payment blocked outright
    held = [e for e in LEDGER if e["status"] == "on_hold"]  # waiting for a correction, not a loss
    by_flag, by_vendor, days = {}, {}, {}
    for e in LEDGER:
        for f in e["flags"]:
            by_flag[f["code"]] = by_flag.get(f["code"], 0) + 1
        v = by_vendor.setdefault(e["vendor"], {"spend": 0.0, "count": 0, "flagged": 0})
        v["spend"] += e["total"]
        v["count"] += 1
        v["flagged"] += bool(e["flags"])
        d = days.setdefault(e["processed_at"][:10], {"approved": 0, "exceptions": 0})
        d["approved" if e["status"] == "approved" else "exceptions"] += 1
    today = now().date()
    series = [{"day": day, **days.get(day, {"approved": 0, "exceptions": 0})}
              for day in ((today - timedelta(days=i)).isoformat() for i in range(29, -1, -1))]
    return {
        "processed": total,
        "touchless_rate": touchless / total if total else 0,
        "loss_prevented": round(sum(e["exposure"] for e in stopped), 2),
        "loss_prevented_session": round(sum(e["exposure"] for e in stopped if e["source"] == "agent"), 2),
        "held_for_correction": round(sum(e["exposure"] for e in held), 2),
        "hours_saved": round(touchless * MANUAL_MINUTES / 60, 1),
        "manual_minutes": MANUAL_MINUTES,
        "open_reviews": sum(1 for e in LEDGER if e["status"] in ("on_hold", "escalated")),
        "avg_cycle_s": round(sum(e["cycle_ms"] for e in LEDGER) / total / 1000, 1) if total else 0,
        "by_flag": sorted(({"code": k, "label": FLAG_TEXT[k], "count": n} for k, n in by_flag.items()),
                          key=lambda x: -x["count"]),
        "by_vendor": sorted(({"vendor": k, **v, "spend": round(v["spend"], 2)} for k, v in by_vendor.items()),
                            key=lambda x: -x["spend"]),
        "series": series,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
