/** @odoo-module **/
import { beforeEach, expect, test } from "@odoo/hoot";
import { contains, mockService, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { animationFrame } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
defineMailModels();
import { CertificateDashboard } from "@gt_supplier_certificate_gate/dashboard/dashboard";

function payload(overrides = {}) {
    return { kpis: { blocked: 2, expiring: 1, missing: 3, pending: 4, overdue: 1 }, chart: [{ key: "bucket_missing", label: "Missing Effective Evidence", count: 3 }, { key: "bucket_expired", label: "Already Expired", count: 0 }], blocked: [], requirements: [], pending: [], overdue: [], updated_at: "2026-11-04 10:00:00", can_review: false, can_manage: true, can_purchase: true, options: { companies: [{ id: 1, name: "Company A" }, { id: 2, name: "Company B" }], owners: [], suppliers: [], types: [], categories: [] }, ...overrides };
}
let handler;
let actions;
beforeEach(() => {
    handler = async (model, method) => method === "get_data" ? payload() : { type: "ir.actions.act_window", res_model: "purchase.order", domain: [["id", "in", [7, 8]]] };
    actions = [];
    mockService("orm", { call: (...args) => handler(...args) });
    mockService("action", { doAction: action => { actions.push(action); } });
});

test("five server values and accessible chart are rendered", async () => {
    await mountWithCleanup(CertificateDashboard);
    expect(".gt-kpi").toHaveCount(5);
    expect(".gt-kpi:first-child strong").toHaveText("2");
    expect(".gt-kpi:nth-child(4) strong").toHaveText("4");
    expect(".gt-bar-row").toHaveCount(2);
    expect(".gt-bar-row:first-child").toHaveAttribute("aria-label", "Missing Effective Evidence: 3 coverage relationships. View records.");
    expect(".gt-refresh").toHaveCount(1);
});

test("company selection sends a validated filter payload and uses new values", async () => {
    await mountWithCleanup(CertificateDashboard);
    handler = async (model, method, args) => {
        expect(args[0].company_id).toBe(2);
        return payload({ kpis: { blocked: 9, expiring: 0, missing: 1, pending: 0, overdue: 0 } });
    };
    await contains('select[name="company_id"]').select("2");
    expect(".gt-kpi:first-child strong").toHaveText("9");
});

test("card and chart drilldowns invoke the server-scoped native action", async () => {
    await mountWithCleanup(CertificateDashboard);
    const metrics = [];
    handler = async (model, method, args) => {
        metrics.push(args[0]);
        return { type: "ir.actions.act_window", res_model: "purchase.order", domain: [["id", "in", [7, 8]]] };
    };
    await contains(".gt-kpi:first-child").click();
    await contains(".gt-bar-row:first-child").click();
    expect(metrics).toEqual(["blocked", "bucket_missing"]);
    expect(actions).toHaveLength(2);
    expect(actions[0].domain).toEqual([["id", "in", [7, 8]]]);
});

test("empty and permission-limited populations remain explicit", async () => {
    handler = async () => payload({ kpis: { blocked: null, expiring: 0, missing: 0, pending: 0, overdue: 0 }, chart: [{ key: "bucket_missing", label: "Missing Effective Evidence", count: 0 }], can_purchase: false });
    await mountWithCleanup(CertificateDashboard);
    expect(".gt-kpi:first-child strong").toHaveText("Unavailable");
    expect(".gt-kpi:first-child").toHaveProperty("disabled", true);
    expect(".gt-chart .gt-empty").toHaveText("No coverage risks in these buckets for the selected filters.");
    expect(".gt-bar-fill").toHaveAttribute("style", "width: 0%;");
});

test("loading clears previous totals and server failure offers retry without traceback", async () => {
    const instance = await mountWithCleanup(CertificateDashboard);
    let rejectRequest;
    handler = () => new Promise((resolve, reject) => { rejectRequest = reject; });
    const request = instance.load();
    await animationFrame();
    expect('.gt-state[role="status"]').toHaveCount(1);
    expect(".gt-kpi").toHaveCount(0);
    rejectRequest(new Error("AccessError: protected internal traceback"));
    await request;
    await animationFrame();
    expect('.gt-error[role="alert"]').toHaveCount(1);
    expect(".gt-dashboard").not.toHaveText(/protected internal traceback/);
    handler = async () => payload();
    await contains(".gt-error .btn-primary").click();
    expect(".gt-kpi").toHaveCount(5);
});

test("late response cannot restore another filter's protected totals", async () => {
    const instance = await mountWithCleanup(CertificateDashboard);
    const resolve = [];
    handler = () => new Promise(r => resolve.push(r));
    const first = instance.load();
    instance.state.filters.company_id = 2;
    const second = instance.load();
    resolve[1](payload({ kpis: { blocked: 20, expiring: 0, missing: 0, pending: 0, overdue: 0 } }));
    await second;
    resolve[0](payload());
    await first;
    await animationFrame();
    expect(".gt-kpi:first-child strong").toHaveText("20");
});
