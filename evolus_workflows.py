"""Small async client and response validators for LedgerHawk's Evolus workflows."""

import asyncio
import json
import re
import time

import httpx


SUCCESS = {"completed", "succeeded", "success"}
FAILURE = {"failed", "cancelled", "canceled", "error", "timed_out"}
ROUTES = {
    "approve": "demo_approved_queue",
    "hold": "manual_review_queue",
    "escalate": "high_risk_review_queue",
    "reject": "rejected_invoice_log",
}


class WorkflowError(Exception):
    """A safe, user-visible workflow error; never includes credentials or document text."""


async def execute_workflow(kind, workflow_id, files, api_key, application_id,
                           base_url="https://api.evolus.ai", poll_interval=3, max_wait=300,
                           transport=None):
    """Start a workflow and return its completed execution, never its pending receipt."""
    url = f"{base_url.rstrip('/')}/api/v1/workflows/{workflow_id}"
    headers = {"X-ApiKey": api_key, "X-Application-Id": application_id}
    async with httpx.AsyncClient(transport=transport) as client:
        try:
            response = await client.post(url + "/execute", headers=headers, files=files, timeout=60)
        except httpx.RequestError as exc:
            raise WorkflowError(f"{kind} workflow could not be started (network error)") from exc
        if response.is_error:
            raise WorkflowError(f"{kind} workflow start returned HTTP {response.status_code}")
        receipt = _response_json(response, kind)
        execution_id = receipt.get("executionId") if isinstance(receipt, dict) else None
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise WorkflowError(f"{kind} workflow did not return an execution ID")

        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            try:
                response = await client.get(
                    f"{url}/executions/{execution_id}", headers=headers, timeout=30,
                )
            except httpx.RequestError as exc:
                raise WorkflowError(f"{kind} workflow polling failed (network error)") from exc
            if response.is_error:
                raise WorkflowError(f"{kind} workflow polling returned HTTP {response.status_code}")
            result = _response_json(response, kind)
            if not isinstance(result, dict):
                raise WorkflowError(f"{kind} workflow execution response must be a JSON object")
            status = str(result.get("status") or "").strip().lower()
            if status in SUCCESS:
                return {**result, "executionId": execution_id}
            if status in FAILURE:
                raise WorkflowError(f"{kind} workflow ended with status: {status}")
            await asyncio.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
    raise WorkflowError(f"{kind} workflow timed out after {max_wait}s")


def _response_json(response, kind):
    try:
        return response.json()
    except ValueError as exc:
        raise WorkflowError(f"{kind} workflow returned invalid JSON") from exc


def output_object(result, kind):
    """Evolus completed executions carry a JSON object or JSON text in output."""
    value = result.get("output") if isinstance(result, dict) else None
    if isinstance(value, str):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value.strip(), flags=re.I)
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise WorkflowError(f"{kind} workflow output is not valid JSON") from exc
    if not isinstance(value, dict):
        raise WorkflowError(f"{kind} workflow output must be a JSON object")
    return value


def extraction_output(result):
    data = output_object(result, "Extraction")
    required = ("vendor", "invoice_number", "invoice_date", "po_number", "iban", "currency", "total", "lines")
    missing = [key for key in required if key not in data]
    if missing:
        raise WorkflowError("Extraction workflow omitted fields: " + ", ".join(missing))
    for key in ("vendor", "invoice_number", "invoice_date", "po_number", "iban", "currency"):
        if data[key] is not None and not isinstance(data[key], str):
            raise WorkflowError(f"Extraction workflow {key} must be text")
    lines = data["lines"]
    if isinstance(lines, str):
        try:
            lines = json.loads(lines)
        except ValueError as exc:
            raise WorkflowError("Extraction workflow lines must be a JSON array") from exc
    if not isinstance(lines, list) or any(not isinstance(line, dict) for line in lines):
        raise WorkflowError("Extraction workflow lines must be an array of objects")
    for line in lines:
        if not all(key in line for key in ("description", "quantity", "unit_price")):
            raise WorkflowError("Extraction workflow line is missing description, quantity, or unit_price")
    if not isinstance(data["currency"], str) or not data["currency"].strip():
        raise WorkflowError("Extraction workflow currency is missing")
    return {**data, "lines": lines}


def assessment_output(result):
    data = output_object(result, "Assessment")
    decision, rationale, draft = data.get("decision"), data.get("rationale"), data.get("draft")
    if decision not in ROUTES:
        raise WorkflowError("Assessment workflow returned an invalid decision")
    if not isinstance(rationale, str) or not rationale.strip():
        raise WorkflowError("Assessment workflow rationale is missing")
    if draft is not None and not isinstance(draft, str):
        raise WorkflowError("Assessment workflow draft must be text or null")
    return {"decision": decision, "rationale": rationale.strip()[:1000],
            "draft": draft.strip()[:2000] if isinstance(draft, str) and draft.strip() else None}


def route_output(result, invoice_number, decision):
    data = output_object(result, "Routing")
    if data.get("invoice_number") != invoice_number or data.get("decision") != decision:
        raise WorkflowError("Routing workflow acknowledgement does not match the invoice decision")
    if data.get("route") != ROUTES[decision] or data.get("status") != "recorded":
        raise WorkflowError("Routing workflow returned an invalid route acknowledgement")
    if not isinstance(data.get("message"), str) or not data["message"].strip():
        raise WorkflowError("Routing workflow acknowledgement message is missing")
    if re.search(r"\b(paid|posted to (?:the )?erp|emailed|message sent)\b", data["message"], re.I):
        raise WorkflowError("Routing workflow message falsely claims an external action")
    return {"workflow": "demo-routing", "executionId": result.get("executionId"),
            "status": "recorded", "route": data["route"], "message": data["message"].strip()[:500]}
