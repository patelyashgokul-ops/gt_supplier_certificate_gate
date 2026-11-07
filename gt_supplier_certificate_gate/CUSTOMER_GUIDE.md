# Supplier Certificate Gate — Customer Guide

**Publisher:** Golok Technology  
**Supported platform:** Odoo 20 Community  
**Dependencies:** Purchase and Mail  
**Version:** 20.0.1.0.0

## Install

1. Extract `gt_supplier_certificate_gate_20.0.zip`; the archive contains one `gt_supplier_certificate_gate` folder.
2. Copy that folder to an Odoo custom-addons directory and add the directory to `addons_path`.
3. Restart Odoo, update the Apps list, search for Supplier Certificate Gate, and install it. Purchase and Mail must be available.
4. In Users, grant Certificate User to buyers and renewal owners. Grant Certificate Reviewer separately to authorized document reviewers. Use Certificate Manager for configuration and owner assignment. Manager access alone does not permit reading certificate PDFs.

## Configure

1. Create Certificate Types.
2. Add active requirements for the purchasing company and product categories. Parent category requirements inherit to descendants.
3. Configure a renewal policy per company: reminder lead time defaults to 30 days and the default renewal owner must be an internal user authorized for that company.
4. Set the company partner timezone; UTC is used if none is configured.

## Certificate and review workflow

Create a supplier certificate with the exact supplier, company, type, reference and validity dates. Use the restricted PDF submission wizard, then Submit for Review. An independent Certificate Reviewer opens the pending queue and inspects the evidence. Approval or rejection is explicit; rejection requires a reason. A submitter cannot approve their own submission. Create a new record for a renewal or correction so prior decisions and files remain historical.

PDFs must be readable and unencrypted; limits are 10 MiB and 500 pages. Active content and embedded files are rejected. Evidence is reviewer restricted and is not shared through chatter. Human review records a decision; it does not prove legal authenticity.

## Buyer and procurement workflow

The purchase gate checks each positive-quantity product line against active requirements on its category and ancestors. A failing requirement blocks the entire confirmation and reports the affected line, certificate type and reason. No requirement means the line passes. Re-check current certificates, resolve outstanding requirements and retry using the native Confirm Order action. Final manager approval checks the evidence again. Native purchase approval rights and thresholds continue to apply.

If a certificate expires after an order is already confirmed, the module does not cancel that order or its receipts. The gate applies when confirming or finally approving eligible orders; customers manage already-confirmed commitments under their own process.

## Renewal owner

Review Pending Renewals and assigned Odoo Activities. Follow up with the supplier and submit evidence through the certificate workflow. Activity completion records follow-up only; it does not verify a certificate. The daily scheduler creates duplicate-safe activities. If an owner is inactive or unauthorized, management should assign an eligible owner.

## Reviewer

Open the review queue, inspect restricted evidence and approve or reject with a reason. Reviewer permission is separate from configuration management. Authorized reviewers may revoke an approval with a reason. The same person who submitted a version cannot approve it.

## Procurement manager

Maintain certificate types, category requirements and renewal policies; assign owners; monitor blocked orders, pending reviews and overdue work in the dashboard. A dashboard status is informational. Purchase confirmation and final approval always run the current server-side gate; renewed certificates never automatically confirm or approve an order.

## Dashboard

Supplier Certificates → Dashboard provides five request-refreshed counts: currently blocked purchase orders, covered requirements expiring within 30 days, uncovered requirements from relevant demand, pending evidence submissions and overdue follow-up activities. The expiry chart uses exclusive buckets. Company, supplier, type, category, status, expiry and owner filters apply under server-side permissions. Requirement reports are timestamped snapshots; return to the dashboard and refresh for current status. Reporting sources above 20,000 records require narrower filters. Mobile users can expand the Filters controls.

## Troubleshooting and scope

- A blocked order: inspect each line's displayed certificate reason, company and exact supplier; check current valid dates and review state.
- Reviewer cannot open a file: verify the user's Reviewer role and authorized company; a Manager or owner role alone is not evidence access.
- Renewal owner is unassigned: choose an active internal Certificate User with access to the company.
- Missing menu: verify the intended GT role and refresh the browser after installation.
- Delayed reminders do not relax the purchase gate; current evidence is checked at confirmation and final approval.

The customer configures the requirements. This application does not provide regulatory guarantees, supplier self-service, OCR/AI, batch certificates of analysis or automatic PO approval. Existing confirmed orders are not automatically cancelled when evidence later expires. Trusted database administrators and direct SQL are outside application-level controls.

**Support:** Golok Technology — [patelyash.gokul@gmail.com](mailto:patelyash.gokul@gmail.com). Include Odoo version, module version and a concise description; do not email confidential certificate PDFs unless your own security policy permits it.
