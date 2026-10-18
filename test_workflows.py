"""Offline tests for Evolus polling, response contracts, and the five AP scenarios."""

import json
import os
import unittest
from unittest.mock import patch

import httpx

os.environ["LEDGERHAWK_MODE"] = "demo"  # Importing app must never start a live run in tests.
import app
from evolus_workflows import (ROUTES, WorkflowError, assessment_output,
                              execute_workflow, extraction_output, route_output)


EXPECTED = {
    "northwind-clean": "approve",
    "orbit-bank": "escalate",
    "apex-duplicate": "reject",
    "helix-price": "hold",
    "brightline-nopo": "hold",
}


def raw_sample(sid):
    inv = app.SAMPLES[sid]["invoice"]
    lines = [{"description": desc, "quantity": qty, "unit_price": price}
             for desc, qty, price in inv["lines"]]
    return {"vendor": inv["vendor"], "invoice_number": inv["number"], "invoice_date": inv["date"],
            "po_number": inv["po"], "iban": inv["iban"], "currency": "EUR",
            "total": sum(qty * price for _, qty, price in inv["lines"]), "lines": json.dumps(lines)}


class WorkflowContractTests(unittest.TestCase):
    def test_extraction_parses_all_fields_and_json_lines(self):
        raw = raw_sample("northwind-clean")
        parsed = extraction_output({"output": json.dumps(raw)})
        self.assertEqual(set(parsed), {"vendor", "invoice_number", "invoice_date", "po_number",
                                       "iban", "currency", "total", "lines"})
        self.assertEqual(parsed["lines"][0]["quantity"], 40)
        with self.assertRaisesRegex(WorkflowError, "lines must be a JSON array"):
            extraction_output({"output": {**raw, "lines": "broken"}})

    def test_assessment_and_route_reject_invalid_outputs(self):
        with self.assertRaisesRegex(WorkflowError, "invalid decision"):
            assessment_output({"output": {"decision": "pay", "rationale": "wrong"}})
        with self.assertRaisesRegex(WorkflowError, "rationale is missing"):
            assessment_output({"output": {"decision": "hold", "rationale": ""}})
        with self.assertRaisesRegex(WorkflowError, "invalid route acknowledgement"):
            route_output({"output": {"invoice_number": "NW-2291", "decision": "approve",
                                     "route": "post_to_erp", "status": "recorded", "message": "done"}},
                         "NW-2291", "approve")


class PollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_posts_multipart_and_waits_for_completion(self):
        seen = []

        def handler(request):
            seen.append(request)
            self.assertEqual(request.headers["X-ApiKey"], "test-key")
            self.assertEqual(request.headers["X-Application-Id"], "test-app")
            if request.url.path.endswith("/execute"):
                self.assertIn(b'name="file"', request.content)
                return httpx.Response(200, json={"executionId": "job-1", "status": "pending"})
            if len(seen) == 2:
                return httpx.Response(200, json={"status": "running"})
            return httpx.Response(200, json={"status": "completed", "output": "{}"})

        result = await execute_workflow(
            "Extraction", "test-workflow", {"file": ("invoice.pdf", b"%PDF-1.4", "application/pdf")},
            "test-key", "test-app", poll_interval=0, transport=httpx.MockTransport(handler),
        )
        self.assertEqual(result["executionId"], "job-1")
        self.assertEqual(len(seen), 3)

    async def test_failed_and_timed_out_executions_surface_errors(self):
        def failed(request):
            if request.url.path.endswith("/execute"):
                return httpx.Response(200, json={"executionId": "job-2"})
            return httpx.Response(200, json={"status": "failed"})

        with self.assertRaisesRegex(WorkflowError, "ended with status: failed"):
            await execute_workflow("Assessment", "test", {"input": (None, "{}")}, "key", "app",
                                   poll_interval=0, transport=httpx.MockTransport(failed))
        with self.assertRaisesRegex(WorkflowError, "timed out"):
            await execute_workflow("Assessment", "test", {"input": (None, "{}")}, "key", "app",
                                   max_wait=0, transport=httpx.MockTransport(failed))


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app.reset()

    async def asyncTearDown(self):
        app.reset()

    async def test_five_scenarios_keep_local_decisions_and_complete_routing(self):
        for sid, expected in EXPECTED.items():
            with self.subTest(sample=sid):
                app.reset()
                calls = []
                raw = raw_sample(sid)

                async def execute(kind, workflow_id, files, api_key, application_id, base_url):
                    calls.append(kind)
                    self.assertEqual(api_key, "test-key")
                    self.assertEqual(application_id, "test-app")
                    self.assertEqual(base_url, "https://api.evolus.ai")
                    if kind == "Extraction":
                        self.assertIn("file", files)
                        return {"executionId": "extract-1", "status": "completed", "output": json.dumps(raw)}
                    payload = json.loads(files["input"][1])
                    if kind == "Assessment":
                        self.assertEqual(payload["extracted_invoice"]["invoice_number"], raw["invoice_number"])
                        self.assertIn("deterministic_flags", payload)
                        self.assertIn("ap_policy", payload)
                        self.assertEqual(payload["vendor_master"], app.VENDORS[raw["vendor"]])
                        return {"executionId": "assess-1", "status": "completed", "output": {
                            "decision": "approve", "rationale": "Model proposal", "draft": "Draft for review",
                        }}
                    self.assertEqual(kind, "Routing")
                    self.assertEqual(payload["final_decision"], expected)
                    self.assertEqual(payload["invoice"]["invoice_number"], raw["invoice_number"])
                    return {"executionId": "route-1", "status": "completed", "output": {
                        "invoice_number": raw["invoice_number"], "decision": expected,
                        "route": ROUTES[expected], "status": "recorded", "message": "Demo route recorded.",
                    }}

                with patch.multiple(app, MODE="live", KEY="test-key", APP_ID="test-app",
                                    API="https://api.evolus.ai", WORKFLOWS={
                                        "Extraction": "extract-id", "Assessment": "assess-id", "Routing": "route-id",
                                    }), patch.object(app, "execute_workflow", side_effect=execute):
                    events = [json.loads(line) async for line in app.run(
                        f"{sid}.pdf", app.sample_pdf(app.SAMPLES[sid]["invoice"]), "",
                    )]
                self.assertEqual(calls, ["Extraction", "Assessment", "Routing"])
                self.assertFalse(any(event.get("status") == "error" for event in events), events)
                entry = events[-1]["entry"]
                self.assertEqual(entry["status"], app.STATUS[expected])
                self.assertEqual(entry["workflow"]["route"], ROUTES[expected])
                self.assertEqual(entry["workflow"]["status"], "recorded")
                if expected != "approve":
                    self.assertIn("policy override", entry["guard"])

    async def test_live_failure_has_no_simulation_fallback_or_audit_entry(self):
        before = len(app.LEDGER)

        async def failing_execute(*args, **kwargs):
            raise WorkflowError("Extraction workflow ended with status: failed")

        with patch.multiple(app, MODE="live", KEY="test-key", APP_ID="test-app",
                            WORKFLOWS={"Extraction": "a", "Assessment": "b", "Routing": "c"}), \
                patch.object(app, "execute_workflow", side_effect=failing_execute):
            events = [json.loads(line) async for line in app.run("test.pdf", b"%PDF-1.4", "")]
        self.assertEqual(events[-1]["status"], "error")
        self.assertIn("failed", events[-1]["message"])
        self.assertFalse(any(event.get("step") == "result" for event in events))
        self.assertEqual(len(app.LEDGER), before)

    async def test_review_route_failure_does_not_change_the_ledger(self):
        entry = app.entry("TEST-1", "Helix Industrial", "PO-1043", "2026-10-15", 100.0,
                          "on_hold", [app.flag("price_variance", 100.0)], "Held", app.now(), 1, "agent")
        app.LEDGER.append(entry)

        async def failing_route(*args):
            raise WorkflowError("Routing workflow ended with status: failed")

        with patch.multiple(app, MODE="live", KEY="test-key", APP_ID="test-app",
                            WORKFLOWS={"Extraction": "a", "Assessment": "b", "Routing": "c"}), \
                patch.object(app, "act_live", side_effect=failing_route):
            with self.assertRaises(app.HTTPException) as caught:
                await app.review(entry["id"], {"action": "approve", "reviewer": "Tester"})
        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual(entry["status"], "on_hold")
        self.assertNotIn("reviewed_at", entry)


if __name__ == "__main__":
    unittest.main()
