/** @odoo-module **/
import { Component, onWillStart, proxy } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class CertificateDashboard extends Component {
    static template = "gt_supplier_certificate_gate.Dashboard";
    static props = ["*"];
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({ loading: true, error: false, data: null, showFilters: false, filters: { company_id: 0, owner_id: 0, supplier_id: 0, type_id: 0, category_id: 0, window: "all", status: "all" } });
        this.request = 0;
        onWillStart(() => this.load());
    }
    get cards() {
        return [
            { key: "blocked", label: "Blocked Purchase Orders", path: "M2 3h3l3 12h10l3-8H6 M9 20h.01 M18 20h.01", tone: "danger", unit: "Distinct current RFQs / approvals" },
            { key: "expiring", label: "Expiring Certificates", path: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l3 2", tone: "warning", unit: "Coverage relationships · next 30 days" },
            { key: "missing", label: "Missing / Expired Requirements", path: "M12 3 20 6v6c0 5-8 9-8 9s-8-4-8-9V6Z M12 8v5 M12 16v1", tone: "danger", unit: "Uncovered demand · includes pending/future" },
            { key: "pending", label: "Pending Verification", path: "M6 2h8l4 4v16H6Z M14 2v5h4 M9 12h6 M9 16h4", tone: "primary", unit: "Submitted documents awaiting review" },
            { key: "overdue", label: "Overdue Follow-ups", path: "M5 5h14v16H5Z M8 2v6 M16 2v6 M5 10h14 M12 13v4 M12 19v.1", tone: "warning", unit: "Open Activities past their deadline" },
        ];
    }
    async load() {
        const request = ++this.request;
        this.state.loading = true;
        this.state.error = false;
        // Clear protected data immediately; a failed/new filter must never show
        // the previous company's totals as belonging to the new selection.
        this.state.data = null;
        try {
            const data = await this.orm.call("gt.certificate.dashboard", "get_data", [ { ...this.state.filters } ]);
            if (request === this.request) this.state.data = data;
        } catch {
            if (request === this.request) this.state.error = true;
        } finally {
            if (request === this.request) this.state.loading = false;
        }
    }
    changeFilter(event) {
        const name = event.target.name;
        const value = event.target.value;
        this.state.filters[name] = ["window", "status"].includes(name) || value === "unassigned" ? value : Number(value);
        if (name === "company_id") Object.assign(this.state.filters, { owner_id: 0, supplier_id: 0, category_id: 0 });
        return this.load();
    }
    clearFilters() {
        Object.assign(this.state.filters, { company_id: 0, owner_id: 0, supplier_id: 0, type_id: 0, category_id: 0, window: "all", status: "all" });
        return this.load();
    }
    get chartMax() { return Math.max(1, ...this.state.data.chart.map(x => x.count)); }
    async open(metric) {
        try {
            const action = await this.orm.call("gt.certificate.dashboard", "open_kpi", [metric, { ...this.state.filters }]);
            await this.action.doAction(action);
        } catch { this.state.data = null; this.state.error = true; }
    }
    async openRecord(kind, id) {
        try {
            const action = await this.orm.call("gt.certificate.dashboard", "open_record", [kind, id, { ...this.state.filters }]);
            await this.action.doAction(action);
        } catch { this.state.data = null; this.state.error = true; }
    }
}
registry.category("actions").add("gt_supplier_certificate_gate.dashboard", CertificateDashboard);
