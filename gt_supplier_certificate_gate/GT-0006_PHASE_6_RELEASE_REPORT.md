# GT-0006 Phase 6 Release Report

Prepared 7 November 2026. Workspace: `C:\PycharmProjects\odoo20\custom_addons\gt_supplier_certificate_gate`. No public submission or publisher-account changes were made.

## A. Product Identity

- App ID: GT-0006
- Technical module: `gt_supplier_certificate_gate`
- Human-readable listing name: Supplier Certificate Renewal Gate (manifest short name: Supplier Certificate Gate)
- Publisher: Golok Technology
- Target price: USD $39 (publisher/store price not configured or verified)
- Version: 20.0.1.0.0
- Platform verified: Odoo 20.0 Community
- Dependencies: purchase, mail; native Community dependencies
- Manifest license: OPL-1; license text file is not included pending legal text/rights confirmation

## B. Phase 5 Verification

Phase 5 report and source were inspected. The prior Phase 5 suite ran 62 Python/Odoo tests successfully, 0 failures, 0 errors, 0 skipped, plus 6 HOOT tests / 21 assertions and 3 live PostgreSQL concurrency scenarios. Actual dashboard browser tests checked buyer and reviewer flows, attachment denial for buyer, filter RPC authorization, and responsive layouts. SME performance fixture: 100 suppliers, 1,010 certificate metadata records, 505 purchase orders, 2 companies, 50 activities; combined dashboard measured 33 queries / 0.5977 seconds at final checkpoint. These results are recorded under `.development/`.

The previous run identified and fixed renewal Activity authorization and live dashboard domain issues. No unresolved Critical/High defect was found in the tested development source. Phase 5 report verdict was PASS. That evidence does not substitute for the package test below.

## C. Final Implementation Status

Certificate configuration, parent-category requirements, restricted evidence submission/review/revocation, renewal history, current validity, purchase confirmation and final approval gates, line-level reasons, company isolation, owner Activities, daily reminders, selective rechecks, dashboard KPIs/chart/filters/reports exist in the inspected source and passed the Phase 1-5 regression suite. Renewal never automatically confirms an order. This report does not certify legal authenticity or claim protection from direct SQL or unrestricted administrator code.

## D. Automated Testing Evidence

Final Phase 5 command (PowerShell; module workspace):

```powershell
$py='C:\PycharmProjects\odoo20\.venv\Scripts\python.exe'
$odoo='C:\PycharmProjects\odoo20\odoo-20.0\odoo-bin'
$env:ODOO_BROWSER_BIN='C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
& $py $odoo -c C:\PycharmProjects\odoo20\odoo-20.0\odoo.conf -d gt0006_dev_clean_20261107 -u gt_supplier_certificate_gate --test-tags gt_phase1,gt_phase2,gt_phase3,gt_phase4,gt_phase5_backend,gt_phase5_frontend,gt_phase5_browser,gt_phase5_performance,gt_phase5_stock --stop-after-init --http-port 8176 --data-dir .development\clean-data --screenshots .development\phase5-screenshots --logfile .development\phase5-acceptance-final.log
```

Results: 62 passed; 0 failed; 0 errors; 0 skipped. HOOT: 6 passed, 21 assertions. Live PostgreSQL concurrency: 3 scenarios passed. Fast Python compile passed. Fresh minimal Community development install/update and installed-state inspection passed. These were development-copy tests, not all tests run against the commercial archive.

Commercial artifact install/update command used isolated extracted addons path:

```powershell
& $py $odoo -c C:\PycharmProjects\odoo20\odoo-20.0\odoo.conf -d gt0006_release_zip_20261107 -u gt_supplier_certificate_gate --stop-after-init --no-http --max-cron-threads 0 --addons-path='C:\PycharmProjects\odoo20\custom_addons\gt_supplier_certificate_gate\.development\release\addons,C:\PycharmProjects\odoo20\odoo-20.0\odoo\addons,C:\PycharmProjects\odoo20\odoo-20.0\addons' --data-dir .development\release\data --logfile .development\release\zip-final-update.log
```

The artifact was extracted from the final archive hash below, and Odoo loaded/updated it successfully. The initial fresh install log is `zip-install.log` but began with an earlier package build (before final icon/manifest metadata). Therefore a fresh database install of the final hash and its complete business smoke workflow remain NOT TESTED. No tests were skipped in the recorded 62-test run; final-archive end-to-end reviewer/buyer workflow is NOT RUN.

## E. Final Customer ZIP

- Filename: `gt_supplier_certificate_gate_20.0.zip`
- Absolute path: `C:\PycharmProjects\odoo20\custom_addons\gt_supplier_certificate_gate\.development\release\gt_supplier_certificate_gate_20.0.zip`
- SHA-256: `d92f65ba267ae1ddb1e3b7a85c4286f675533f811555cb4f4ff02787e42a1529`
- Size: 258,304 bytes
- Top-level folder: `gt_supplier_certificate_gate/`
- Files: 25
- Includes: runtime Python, security, data, views, dashboard Owl assets, listing, actual dashboard screenshots, icon, customer guide.
- Excludes: tests, `.development`, logs, databases, caches, credentials, `.git`.
- Name scan for tests/cache/secrets/development terms: no flagged archive paths.
- No automated secret scanner was available/run; archive names and source were reviewed. Full secret scan: NOT VERIFIED.
- Dependencies inspected as Odoo Community `purchase` and `mail`; no third-party JS/Python runtime dependencies.
- License compatibility is NOT VERIFIED: manifest says OPL-1 but distributable license text/ownership approval was not available in this workspace. Do not publish until confirmed and the appropriate notice is included.

## F. Exact ZIP Installation Test

- Odoo source/executable: `C:/PycharmProjects/odoo20/odoo-20.0/odoo-bin`, Odoo 20.0 Community.
- DB: `gt0006_release_zip_20261107`, disposable.
- Isolated module source: `.development/release/addons/gt_supplier_certificate_gate`, extracted from the final ZIP; core Odoo addons supplied separately. The development module directory was not in the explicit `--addons-path`.
- Final archive update: successful; registry loaded, exit code 0, log `zip-final-update.log`.
- Fresh install of the exact final ZIP hash: NOT VERIFIED. The earlier clean install was on an earlier ZIP hash.
- Artifact smoke workflow (all buyer/reviewer/PO/renewal/dashboard operations): NOT RUN against exact final hash. Development-copy browser and business coverage is reported in D.
- Missing runtime dependencies/errors on final artifact update: none observed. Store-distribution acceptance remains unverified.

## G. Apps Store Assets

- HTML: `static/description/index.html` (navy/ivory/gold, responsive Bootstrap columns, feature/setup/FAQ/support content, local relative images).
- Icon: `static/description/icon.png` (original 512x512 PNG).
- Genuine screenshots: `static/description/screenshots/dashboard.png`, `dashboard-tablet.png`, `dashboard-mobile.png`; captured from actual Odoo browser tests. Screens for requirements configuration, certificate/reviewer form, renewal history, blocked PO and activity are missing.
- Promotional banner graphics: no separate banners were prepared.
- Image format/dimensions and local references inspected; no external assets/scripts/fonts. Description references an external Gmail compose link as explicitly requested, but current Apps Store vendor guidance allows `mailto:` and selected video links rather than arbitrary external links; listing acceptance is therefore NOT VERIFIED and may reject this demo link.
- Branding matches Golok Technology. Verified support email: patelyash.gokul@gmail.com.
- Demo link in `live_test_url` is HTTPS Gmail Compose, with subject `Schedule Demo - Supplier Certificate Gate`. Recipient is the provided `patelyash.gokul@gmaiol.com` spelling, which differs from the support email; actual recipient validity was not checked. The manifest name is under the current 25-character limit. Price/currency are store-side and not set in supported manifest metadata.
- Current Odoo Apps vendor guidance reviewed: https://apps.odoo.com/apps/vendor-guidelines. It prohibits arbitrary external links in descriptions and requires actual accurate listing assets. External demo link needs publisher/Odoo review.
- Missing publisher-account access, store price confirmation, repository registration and post-publication checks.

## H. Customer Documentation

`CUSTOMER_GUIDE.md` is included in the ZIP and covers installation, setup, buyer, owner, reviewer and manager workflows, troubleshooting, limits, privacy boundary and support. The guide reflects the README-supported settings and workflows. No separate PDF or RST guide exists. Support: patelyash.gokul@gmail.com. The OPL license text/notice is outstanding and is a release blocker.

## I. Security Audit

Development tests cover company isolation, separate reviewer evidence access, direct content routes, reviewer/approval integrity, four-eyes rules, PO state/RPC bypass, dashboard filter authorization and protected Activities. Final development suite passed. Final archive manifest and runtime source were loaded successfully from the isolated extracted copy. No archive test/credential path was found. A dedicated automated secret-content scanner and full source audit against final ZIP were not executed. Scheduler uses company-scoped operations; purchase gate independently checks current evidence. Direct SQL and unrestricted superuser code remain outside the supported application boundary. No Critical/High issue surfaced in tested workflows; full final-artifact security re-run is NOT VERIFIED.

## J. Performance and UX

Development dashboard tests used 1,010 certificates / 505 POs / 2 companies, with 33 combined queries / 0.5977s at the recorded checkpoint. Real Chromium/Edge viewports: 1440x1100, 900x1100, 390x844; five/three/one KPI columns and no horizontal page overflow. HOOT 6/6 and real browser buyer/reviewer tests passed. No development browser errors were reported in those tested flows. Same measurements have not been repeated against extracted customer archive. Package scope cap is 20,000 per source and previews are bounded to eight.

## K. Release Blockers

- **Critical ? Open:** Final archive hash has not passed a fresh-database install and complete customer-archive business smoke workflow. Corrective action: install this exact ZIP in a new disposable Odoo 20 CE DB and run the documented buyer/reviewer/company/PO/dashboard smoke scenarios.
- **High ? Open:** License text/rights compatibility not confirmed and no license notice file is included. Corrective action: confirm Golok's OPL-1 distribution rights and add the authoritative required license notice.
- **High ? Open:** Required commercial screenshots for configuration, reviewer, PO, renewal/activity and history are missing; no promotional banner art. Corrective action: capture genuine screens from isolated final-artifact installation and create original brand artwork.
- **High ? Open:** Odoo Apps listing policy acceptance of external Gmail compose URL is not verified; official vendor page restricts arbitrary external links. Corrective action: obtain publisher/Odoo acceptance or use permitted `mailto:` while keeping required internal demo contact behavior.
- **Medium ? Open:** Recipient address contains the requested `gmaiol.com` spelling, which differs from support email. Confirm actual intended address before publishing.
- **Medium ? Open:** Price/currency are not represented by a supported manifest field; publisher must set USD 39 in vendor account and verify.
- **Low ? Fixed:** icon and responsive dashboard listing captures included. **Low ? Not Verified:** complete secret scanner and listing HTML runtime preview were not run.

## L. Final Commercial Release Verdict

**NO-GO ? NOT READY**

The customer ZIP and documentation are prepared, but final-hash fresh install plus complete smoke is unverified. License notice/rights, required genuine listing captures and Apps Store link acceptance remain open. Do not submit this archive until the Critical and High blockers are resolved and the final rebuilt hash is retested.

## M. Manual Publishing Handoff

After resolving blockers: confirm publisher account and support email; set USD 39 pricing; confirm repository/submission configuration and license rights; review the demo link against Apps Store policy; inspect genuine screenshots and copy; submit through authorized Odoo Apps workflow; then verify the public listing. No publication occurred.
