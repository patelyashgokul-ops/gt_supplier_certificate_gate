# Supplier Certificate Gate

Golok Technology · Odoo 20.0 Community · GT-0006

Development scope implemented: company-specific certificate requirements, restricted PDF submission, independent review, immutable renewal versions, purchase confirmation/final approval enforcement, renewal ownership and native Activities.

## Initial setup

1. Install the module on Odoo 20 Community with Purchase and Mail.
2. Assign Certificate Manager to configuration owners. Assign Certificate Reviewer separately to authorized reviewers; manager permissions do not include confidential file access. Purchase Users inherit Certificate User metadata/submission access.
3. Configure certificate types and active company/category requirements. Parent category requirements are inherited and duplicate types are evaluated once per product line.
4. Configure a Renewal Policy per company (30 calendar days by default) and a valid default renewal owner. Certificate-specific owners take precedence for new cycles. Owners need the Certificate User role and company access.
5. Set the company partner timezone; UTC is the deterministic fallback. Business validity is inclusive at both date boundaries.

## Certificate workflow

Create certificate metadata with exact supplier, company, classification, reference and dates. Use Submit Restricted PDF. The write-only upload wizard does not retain a readable file. The submission enters Pending Review and freezes that version's identity/evidence. A different Certificate Reviewer downloads and explicitly approves or rejects it. Rejection/revocation requires a meaningful reason. A renewal or correction is a new record; historical evidence and decisions remain intact.

PDF policy: maximum 10 MiB and 500 pages; readable, unencrypted PDFs only, with no active actions or embedded files. The file is held in a separate reviewer-only database binary, without attachment tokens or chatter links. This workflow records human review; it does not establish regulatory authenticity.

## Purchasing

Certificates match the exact PO supplier ID and purchasing company. Supplier contacts do not automatically inherit commercial partner certificates. All positive-quantity product lines (including services and products flagged as downpayments) are evaluated. Display lines, product-less native downpayments and quantities <=0 create no positive product commitment for this gate. Native missing-product validation remains in force.

Confirmation and final approval always evaluate current requirements and effective verified evidence. Direct state advancement is also checked. Native purchase thresholds/authorization remain applicable. Check Certificates stores a timestamped informational result; it is never an authorization token. Failed confirmation does not persist blocker history outside its rolled-back transaction.

## Renewals

The daily job considers maintained certificate relationships for active required types and actual draft/sent/to-approve procurement demand. It does not generate every theoretical supplier/category combination. One open renewal cycle per company/supplier/type and one active linked Activity are enforced by database indexes.

Follow-up deadlines are independent from validity dates. Completing an Activity acknowledges follow-up but does not resolve missing evidence or grant approval. Open work remains visible; managers can explicitly request another follow-up. Effective coverage beyond the reminder window resolves the cycle; future approved evidence does not resolve a current gap. Deactivated requirements close work as No Longer Required.

Effective approvals, submissions, rejections and revocations selectively refresh outstanding orders for the same company/supplier and inherited certificate type. The job handles future-effective renewals too. No renewal action confirms or approves a PO.

The cron processes 200-record pages for each source, with persisted per-company cursors, at most ten batches per company/invocation and native progress reporting. Large backlogs may require subsequent runs. The purchase gate remains independent and authoritative even if reminders are delayed.

## Developer evidence

Tests are under `tests/`; internal reports, commands, logs and disposable runtime data are under `.development/` because this workspace permits writes only within the module root. Exclude `.development`, tests and caches from the future customer-only package in Phase 6. No customer ZIP, dashboard or release assets have been prepared.

Existing certificate/order rows are locked during confirmation/revocation. PostgreSQL/Odoo retries resolve incompatible concurrent transactions. Administrative configuration changes use normal transaction snapshots; no global serialization of all configuration is claimed. Trusted unrestricted superuser code and direct database writes are outside application-level protection.
