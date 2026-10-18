# Accounts Payable Control Policy

The app sends these rules to the Evolus AP assessment workflow. Local deterministic checks remain authoritative.

## 1. Approval
An invoice may be approved for payment only when all of these hold:
- The vendor is in the vendor master.
- The bank details (IBAN) on the invoice match the vendor master.
- The invoice references a valid purchase order issued to the same vendor.
- Every line item is on the PO, quantities do not exceed the PO, and unit prices are within 2% of the PO price.
- The invoice total equals the sum of its lines.
- The invoice number has not been processed before for that vendor.

## 2. Duplicates
An invoice whose number was already processed for the same vendor is rejected. Reminders and "second notices" are not new invoices.

## 3. Bank-detail changes
Any change to a vendor's bank details requested by email or shown only on an invoice is treated as possible payment fraud.
Escalate to the financial controller. Verify by phone using the number already on file, never one from the email.
Do not pay until the change is verified and the vendor master is updated by the controller.

## 4. Price and quantity variances
Hold the invoice and ask the vendor for a corrected invoice or written confirmation that references the PO.
Variances above 2% require buyer approval before payment.

## 5. Invoices without a PO
Hold and route to the requester to raise a PO retroactively, or to confirm the spend is approved.

## 6. Audit trail
Every decision records the checks performed, the failed checks, the decision, a short rationale and, when a person overrides the agent, who decided and when.
