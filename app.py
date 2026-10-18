"""LedgerHawk: AP invoice audit demo with deterministic controls and Evolus workflows."""
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
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse

from evolus_workflows import (WorkflowError, assessment_output, execute_workflow,
                              extraction_output, route_output, ROUTES)


ROOT = Path(__file__).resolve().parent


def load_local_env():
    """Load simple KEY=value entries from this project's .env without overriding process env."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if separator and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", key):
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            os.environ.setdefault(key, value)


load_local_env()

API = os.getenv("EVOLUS_BASE_URL", "https://api.evolus.ai").rstrip("/")
KEY = os.getenv("EVOLUS_API_KEY")
APP_ID = os.getenv("EVOLUS_APPLICATION_ID")
WORKFLOWS = {
    "Extraction": os.getenv("EVOLUS_WORKFLOW_EXTRACT_ID"),
    "Assessment": os.getenv("EVOLUS_WORKFLOW_ASSESS_ID"),
    "Routing": os.getenv("EVOLUS_WORKFLOW_ROUTE_ID"),
}
MODE = os.getenv("LEDGERHAWK_MODE", "demo").strip().lower()
if MODE not in ("demo", "live"):
    raise ValueError("LEDGERHAWK_MODE must be demo or live")
MODEL_NAME = os.getenv("AMD_MODEL_NAME", "AMD TokenFactory")
POLICY_TEXT = (ROOT / "ap_policy.md").read_text(encoding="utf-8")
PRICE_TOLERANCE = 0.02  # 2% unit-price variance allowed before a hold
MAX_UNIT, MAX_TOTAL = 1e9, 1e12  # any quantity, unit price or total beyond these is treated as unreadable
MANUAL_MINUTES = 12  # assumed manual handling time per invoice, used for "hours saved"


def require_live_config():
    configured = {"EVOLUS_API_KEY": KEY, "EVOLUS_APPLICATION_ID": APP_ID,
                  "EVOLUS_WORKFLOW_EXTRACT_ID": WORKFLOWS["Extraction"],
                  "EVOLUS_WORKFLOW_ASSESS_ID": WORKFLOWS["Assessment"],
                  "EVOLUS_WORKFLOW_ROUTE_ID": WORKFLOWS["Routing"]}
    missing = [key for key, value in configured.items() if not value]
    if missing:
        raise WorkflowError("Live mode is missing configuration: " + ", ".join(missing))

# --- Demo-only in-memory vendor and PO records; there is no ERP connection. ---

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
    grouped_iban = " ".join(inv["iban"][i:i + 4] for i in range(0, len(inv["iban"]), 4))
    rows = ["INVOICE", "", f"Vendor: {inv['vendor']}", f"Invoice No: {inv['number']}",
            f"Invoice Number: {inv['number']}", f"Invoice Date: {inv['date']}",
            f"PO Number: {inv['po'] or 'NONE'}", f"IBAN: {grouped_iban}",
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
                           "master. Recorded in the demo approval queue.",
               "rejected": "Invoice number already processed for this vendor; rejected to prevent a duplicate.",
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
    # A prior AP-5510 record makes the reminder in the demo inbox a duplicate.
    paid = now() - timedelta(days=17)
    ledger.append(entry("AP-5510", "Apex Logistics", "PO-1044", "2026-09-28", 1140.00, "approved", [],
                        "Matched PO-1044 line by line; previously recorded in the demo ledger.", paid, 9100, "seed"))
    return sorted(ledger, key=lambda e: e["processed_at"])


LEDGER = seed_ledger()


# --- Step 1: extraction ---

async def extract_live(name, data, email):
    result = await execute_workflow("Extraction", WORKFLOWS["Extraction"],
                                    {"file": (os.path.basename(name), data, "application/pdf")},
                                    KEY, APP_ID, API)
    return normalize(extraction_output(result))


def num(v):
    """A finite number, or None. Unreadable amounts must never compare as 'within tolerance' (NaN fails open)."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def normalize(raw):
    po = str(raw.get("po_number") or "").strip()
    if po.casefold() in {"-", "n/a", "none", "null", "no po", "not provided"}:
        po = ""
    lines = [{"desc": str(l.get("description", "")), "qty": num(l.get("quantity")),
              "price": num(l.get("unit_price"))} for l in raw.get("lines", [])]
    return {"vendor": raw.get("vendor") or "", "number": raw.get("invoice_number") or "",
            "date": raw.get("invoice_date") or "", "po": po,
            "iban": re.sub(r"[\s-]", "", raw.get("iban") or "").upper(),
            "currency": raw.get("currency") or "EUR", "total": num(raw.get("total")), "lines": lines}


def doc_key(s):
    """Invoice numbers and vendor names compared without case, spaces or punctuation, after NFKC folding:
    'AP-5510' == 'ap 5510' == 'ＡＰ－５５１０'. Only ASCII letters and digits survive."""
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKC", str(s or "")).casefold())


def odd_chars(s):
    """True when an invoice number has anything beyond ASCII letters, digits, spaces and common separators
    after NFKC, e.g. Cyrillic look-alikes ('АР-5510') or invisible characters, which could dodge the duplicate check."""
    return bool(re.search(r"[^A-Za-z0-9 \-_/.#]", unicodedata.normalize("NFKC", str(s or "")).strip()))


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
    po = fields.get("PO Number", "NONE")
    return {"vendor": fields.get("Vendor", ""), "number": fields.get("Invoice No", name.rsplit(".", 1)[0]),
            "date": fields.get("Invoice Date", ""), "po": "" if po.upper() in ("-", "NONE") else po,
            "iban": re.sub(r"[\s-]", "", fields.get("IBAN", "")).upper(),
            "currency": fields.get("Currency", "EUR"), "total": num(fields.get("Total")), "lines": lines}


# --- Step 2: deterministic audit rules and authoritative decision ---

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
    elif inv["iban"] != vendor["iban"]:
        message = (f"IBAN {inv['iban']} differs from master {vendor['iban']}" if inv["iban"]
                   else "Invoice IBAN is missing; check against the vendor master")
        flags.append(flag("bank_change", total, message))
    key = doc_key(inv["number"])
    prior = None
    if not key:  # without a number the duplicate check can't run, so the invoice can't pass it
        flags.append(flag("unreadable_number", total, "Invoice number missing or unreadable; check the PDF by hand"))
    elif odd_chars(inv["number"]):
        flags.append(flag("unreadable_number", total, "Invoice number contains unusual characters, possibly look-alikes; "
                                                       "check it against the PDF by hand"))
    if key:
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


# --- Step 3: Evolus assessment, with a local policy decision ---

async def reason_live(inv, flags, po):
    invoice = {
        "vendor": inv["vendor"], "invoice_number": inv["number"], "invoice_date": inv["date"],
        "po_number": inv["po"], "iban": inv["iban"], "currency": inv["currency"],
        "total": inv["total"], "lines": [
            {"description": line["desc"], "quantity": line["qty"], "unit_price": line["price"]}
            for line in inv["lines"]
        ],
    }
    context = {"extracted_invoice": invoice, "purchase_order": po,
               "vendor_master": VENDORS.get(inv["vendor"]), "deterministic_flags": flags,
               "ap_policy": POLICY_TEXT}
    result = await execute_workflow("Assessment", WORKFLOWS["Assessment"],
                                    {"input": (None, json.dumps(context, ensure_ascii=False))},
                                    KEY, APP_ID, API)
    return assessment_output(result)


async def reason_sim(inv, flags, po):
    await asyncio.sleep(1.6)
    d = rule_decision(flags)
    msgs = "; ".join(f["message"] for f in flags)
    terms = VENDORS.get(inv["vendor"], {}).get("terms_days", 30)
    rationale = {
        "approve": f"Invoice {inv['number']} matches {inv['po']} on vendor, items, quantities and prices, and the "
                   f"bank details match the vendor master. Approved in this demo on {terms}-day terms.",
        "reject": f"Rejected as a duplicate: {msgs}. Paying it again would double-pay €{inv['total']:,.2f}.",
        "escalate": f"Escalated to the controller: {msgs}. Bank-detail changes requested by email are a classic "
                    "payment-fraud pattern; confirm with the vendor through a known phone number before paying.",
        "hold": f"Placed on hold: {msgs}. The vendor or requester must resolve this before payment.",
    }[d]
    return {"decision": d, "rationale": rationale, "confidence": 0.93 if d == "approve" else 0.88}


def guard(model_out, flags):
    """The deterministic rule decision is authoritative for every outcome."""
    rules = rule_decision(flags)
    d = model_out.get("decision")
    if d != rules:
        return rules, f"policy override: assessment said {d}; deterministic checks require {rules}"
    return rules, None


# --- Step 4: optional display-only draft ---
async def draft_sim(inv, flags):
    await asyncio.sleep(0.8)
    issues = "\n".join(f"  • {f['message']}" for f in flags)
    return (f"Subject: Invoice {inv['number']} on hold\n\nDear {inv['vendor']} team,\n\n"
            f"We received invoice {inv['number']} but cannot release it for payment yet:\n{issues}\n\n"
            "Could you send a corrected invoice, or confirm the change in writing referencing the PO? "
            "We will process it as soon as we hear back.\n\nKind regards,\nAccounts Payable")


# --- Step 5: side-effect-free demo routing acknowledgement ---

async def act_live(inv, decision, rationale):
    payload = {"invoice": {"invoice_number": inv["number"], "vendor": inv["vendor"],
                           "po_number": inv["po"], "currency": inv.get("currency", "EUR"),
                           "total": inv["total"]},
               "final_decision": decision, "reason": rationale}
    result = await execute_workflow("Routing", WORKFLOWS["Routing"],
                                    {"input": (None, json.dumps(payload, ensure_ascii=False))},
                                    KEY, APP_ID, API)
    return route_output(result, inv["number"], decision)


async def act_sim(inv, decision, rationale):
    await asyncio.sleep(0.6)
    return {"workflow": "demo-routing", "executionId": uuid.uuid4().hex[:12],
            "status": "recorded", "route": ROUTES[decision],
            "message": "Invoice recorded in the demo queue."}


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
    configured = bool(KEY and APP_ID and all(WORKFLOWS.values()))
    return {"mode": MODE, "configured": configured, "model": MODEL_NAME,
            "live": {"extract": MODE == "live", "assess": MODE == "live", "route": MODE == "live"}}


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
    if not data.startswith(b"%PDF-"):
        raise HTTPException(400, "Upload a PDF invoice")
    return StreamingResponse(run(file.filename or "invoice.pdf", data, email), media_type="application/x-ndjson")


async def run(name, data, email):
    try:
        async for event in run_pipeline(name, data, email):
            yield event
    except WorkflowError as exc:
        yield json.dumps({"step": "error", "status": "error", "message": str(exc)}) + "\n"
    except Exception:
        yield json.dumps({"step": "error", "status": "error",
                          "message": "Invoice processing failed unexpectedly"}) + "\n"


async def run_pipeline(name, data, email):
    if MODE == "live":
        require_live_config()
    started = time.perf_counter()
    ev = lambda **k: json.dumps(k) + "\n"

    yield ev(step="extract", status="running")
    t = time.perf_counter()
    inv = await (extract_live(name, data, email) if MODE == "live" else extract_sim(name, data, email))
    mode = MODE
    yield ev(step="extract", status="done", mode=mode, ms=ms(t), data=inv)

    yield ev(step="match", status="running")
    t = time.perf_counter()
    flags, po = run_checks(inv), PURCHASE_ORDERS.get(inv["po"])
    yield ev(step="match", status="done", mode="local", ms=ms(t),
             data={"flags": flags, "po": po, "master": VENDORS.get(inv["vendor"])})

    yield ev(step="reason", status="running")
    t = time.perf_counter()
    out = await (reason_live(inv, flags, po) if MODE == "live" else reason_sim(inv, flags, po))
    decision, note = guard(out, flags)
    if note:
        issues = "; ".join(f["message"] for f in flags)
        out = {**out, "rationale": f"{decision.title()} by local AP policy: {issues or 'all mandatory checks passed'}."}
    yield ev(step="reason", status="done", mode=mode, ms=ms(t), data={**out, "decision": decision, "guard": note})

    draft = None
    if MODE == "live" and decision != "approve" and out.get("draft"):
        draft = out["draft"]
        yield ev(step="draft", status="done", mode="live", ms=0, data={"email": draft})
    elif MODE == "demo" and decision != "approve" and {f["code"] for f in flags} & VENDOR_FIXABLE:
        yield ev(step="draft", status="running")
        t = time.perf_counter()
        draft = await draft_sim(inv, flags)
        yield ev(step="draft", status="done", mode="demo", ms=ms(t), data={"email": draft})
    else:
        yield ev(step="draft", status="skipped")

    yield ev(step="act", status="running")
    t = time.perf_counter()
    action = await (act_live(inv, decision, out["rationale"]) if MODE == "live"
                    else act_sim(inv, decision, out["rationale"]))
    yield ev(step="act", status="done", mode=mode, ms=ms(t), data=action)

    e = entry(inv["number"], inv["vendor"], inv["po"], inv["date"], inv["total"], STATUS[decision], flags,
              out["rationale"], now(), ms(started), "agent")
    e.update(lines=inv["lines"], iban=inv["iban"], currency=inv["currency"], draft=draft,
             workflow=action, guard=note)
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
    try:
        if MODE == "live":
            require_live_config()
        route = await (act_live(e, action, f"Reviewed by {reviewer}: {reason or 'no reason given'}")
                       if MODE == "live" else act_sim(e, action, reason))
    except WorkflowError as exc:
        raise HTTPException(502, str(exc)) from exc
    e.update(agent_status=e["status"], status="approved" if action == "approve" else "rejected",
             reviewed_at=now().isoformat(), reviewed_by=reviewer, review_reason=reason, workflow=route)
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
