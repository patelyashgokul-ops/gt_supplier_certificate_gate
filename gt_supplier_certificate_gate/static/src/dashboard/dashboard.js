import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class CertificateDashboard extends Component {
    static template = "gt_supplier_certificate_gate.Dashboard";
    static props = ["*"];
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, error: false, data: null, filters: { company_id: 0, owner_id: 0, supplier_id: 0, type_id: 0, category_id: 0, window: "all", status: "all" } });
        this.request = 0;
        onWillStart(() => this.load());
    }
    get cards() {
        return [
            { key: "blocked", label: "Blocked Purchase Orders", icon: "fa-shopping-cart", tone: "danger", unit: "Distinct current RFQs / approvals" },
            { key: "expiring", label: "Expiring Certificates", icon: "fa-hourglass-half", tone: "warning", unit: "Coverage relationships · next 30 days" },
            { key: "missing", label: "Missing / Expired Requirements", icon: "fa-shield", tone: "danger", unit: "Uncovered demand · includes pending/future" },
            { key: "pending", label: "Pending Verification", icon: "fa-file-text-o", tone: "primary", unit: "Submitted documents awaiting review" },
            { key: "overdue", label: "Overdue Follow-ups", icon: "fa-calendar-check-o", tone: "warning", unit: "Open Activities past their deadline" },
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
        if (name === "company_id") this.state.filters.owner_id = 0;
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
