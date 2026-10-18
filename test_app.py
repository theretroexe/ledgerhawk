"""python test_app.py: each demo invoice round-trips through the PDF and lands on the expected decision."""
import asyncio
import os

os.environ["LEDGERHAWK_MODE"] = "demo"  # Keep this regression check offline even if local .env selects live.
import app

EXPECTED = {"northwind-clean": "approve", "helix-price": "hold", "apex-duplicate": "reject",
            "orbit-bank": "escalate", "brightline-nopo": "hold"}

for sid, want in EXPECTED.items():
    inv = asyncio.run(app.extract_sim("x.pdf", app.sample_pdf(app.SAMPLES[sid]["invoice"]), ""))
    assert inv["vendor"] == app.SAMPLES[sid]["invoice"]["vendor"], inv
    got = app.rule_decision(app.run_checks(inv))
    assert got == want, (sid, got, app.run_checks(inv))

# The deterministic decision is authoritative even if the assessment disagrees.
flags = [app.flag("price_variance", 100)]
assert app.guard({"decision": "approve"}, flags)[0] == "hold"
assert app.guard({"decision": "escalate"}, flags)[0] == "hold"
assert app.guard({"decision": "yes"}, [])[0] == "approve"
# Line flags point at the exact invoice line; field flags at the exact field.
helix = asyncio.run(app.extract_sim("x.pdf", app.sample_pdf(app.SAMPLES["helix-price"]["invoice"]), ""))
assert [(f["field"], f["line"]) for f in app.run_checks(helix)] == [("line", 0)]
orbit = asyncio.run(app.extract_sim("x.pdf", app.sample_pdf(app.SAMPLES["orbit-bank"]["invoice"]), ""))
assert app.run_checks(orbit)[0]["field"] == "iban"
missing_iban = asyncio.run(app.extract_sim("x.pdf", app.sample_pdf(app.SAMPLES["northwind-clean"]["invoice"]), ""))
missing_iban["iban"] = ""
assert "bank_change" in {f["code"] for f in app.run_checks(missing_iban)}

# Releasing a suspected bank-fraud invoice needs a reviewer, a reason and a confirmed call-back.
esc = app.entry("T-1", "Apex Logistics", "", "2026-10-01", 10.0, "escalated",
                [app.flag("bank_change", 10.0)], "", app.now(), 1, "agent")
app.LEDGER.append(esc)
for body in ({"action": "approve", "reviewer": "x"}, {"action": "approve", "reason": "ok", "verified": True}):
    try:
        asyncio.run(app.review(esc["id"], body))
        raise AssertionError(f"release should be refused: {body}")
    except app.HTTPException as err:
        assert err.status_code == 400
out = asyncio.run(app.review(esc["id"], {"action": "approve", "reviewer": "x", "reason": "called", "verified": True}))
assert out["status"] == "approved" and out["agent_status"] == "escalated" and out["reviewed_by"] == "x"
# Unreadable or non-finite amounts fail closed (NaN would otherwise pass every tolerance check).
for raw_total, raw_qty in (("nan", 40), ("1000", "inf"), (None, 40), ("abc", 40), ("3400", -5), ("3400", "1e200"), ("1e300", 40)):
    inv = app.normalize({"vendor": "Northwind Components", "invoice_number": f"NW-T{raw_total}{raw_qty}", "po_number": "PO-1042",
                         "iban": "IT60X0542811101000000123456", "total": raw_total,
                         "lines": [{"description": "Servo motor SM-200", "quantity": raw_qty, "unit_price": 85}]})
    fl = app.run_checks(inv)
    assert "unreadable_amount" in {f["code"] for f in fl} and app.rule_decision(fl) == "escalate", (raw_total, raw_qty, fl)
    assert all(app.math.isfinite(x) for x in (inv["total"], inv["lines"][0]["qty"], inv["lines"][0]["price"]))

# Duplicates are caught whatever the formatting: AP-5510 == "ap 5510" == "AP_5510".
for variant in ("ap 5510", "AP_5510", " Ap-5510 ", "ＡＰ－５５１０"):
    inv = asyncio.run(app.extract_sim("x.pdf", app.sample_pdf(app.SAMPLES["apex-duplicate"]["invoice"]), ""))
    inv["number"] = variant
    assert "duplicate" in {f["code"] for f in app.run_checks(inv)}, variant
# ...and a missing or unreadable number fails closed instead of skipping the duplicate check.
for blank in ("", "  ", "---", None, "АР-5510", "AP-5510​", "APㅤ-5510"):  # empty, Cyrillic look-alike, invisible chars
    fl = app.run_checks(dict(inv, number=blank))
    # payment must stop: escalated, or rejected outright when it also matches a paid invoice
    assert "unreadable_number" in {f["code"] for f in fl} and app.rule_decision(fl) in ("escalate", "reject"), (blank, fl)

rec = app.records()
assert len(rec["vendors"]) == len(app.VENDORS) and rec["purchase_orders"][0]["ordered"] == 3900.0
print("ok")
