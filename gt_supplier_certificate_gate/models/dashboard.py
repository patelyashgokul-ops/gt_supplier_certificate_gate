"""Authorized live dashboard projections. No evidence reads or elevated aggregation."""
from datetime import timedelta
from odoo import api, fields, models, Command
from odoo.exceptions import AccessError, ValidationError, UserError

STATUS = [('effective', 'Currently Covered'), ('missing', 'Missing'), ('expired', 'Expired'), ('future', 'Not Yet Effective'), ('pending', 'Pending Review'), ('rejected', 'Rejected'), ('revoked', 'Revoked'), ('draft', 'Unverified')]
BUCKETS = [('missing', 'Missing Effective Evidence'), ('expired', 'Already Expired'), ('seven', 'Expiring in 0-7 Days'), ('thirty', 'Expiring in 8-30 Days'), ('sixty', 'Expiring in 31-60 Days')]
LIMIT = 20000


class Dashboard(models.AbstractModel):
    _name = 'gt.certificate.dashboard'
    _description = 'Authorized Supplier Certificate Dashboard'

    def _scope(self, filters):
        if not self.env.user.has_group('gt_supplier_certificate_gate.group_user'):
            raise AccessError('Certificate User permission is required.')
        if filters is None:
            filters = {}
        if not isinstance(filters, dict) or filters.keys() - {'company_id', 'owner_id', 'supplier_id', 'type_id', 'category_id', 'window', 'status'}:
            raise ValidationError('Unsupported dashboard filters.')
        f = dict(filters)
        authorized = self.env.user.company_ids
        company_id = f.get('company_id', 0)
        for name in ('company_id', 'supplier_id', 'type_id', 'category_id'):
            value = f.get(name, 0)
            if type(value) is not int or value < 0:
                raise ValidationError('Filter identifiers must be non-negative integers.')
        if company_id and company_id not in authorized.ids:
            raise AccessError('Company selection is not authorized.')
        companies = authorized.filtered(lambda c: not company_id or c.id == company_id)
        # Replace client context: company defaults, active_test and arbitrary skip
        # flags must not affect a privileged-looking aggregation or navigation.
        scoped = self.with_context({'allowed_company_ids': companies.ids, 'lang': self.env.lang})
        for name, model in [('supplier_id', 'res.partner'), ('type_id', 'gt.certificate.type'), ('category_id', 'product.category')]:
            if f.get(name):
                record = scoped.env[model].browse(f[name])
                record.check_access('read')
                if not record.exists():
                    raise ValidationError('A selected record is unavailable.')
                if 'company_id' in record._fields and record.company_id and record.company_id not in companies:
                    raise AccessError('A selected record belongs to another company.')
        owner = f.get('owner_id', 0)
        if owner == 'unassigned':
            if not self.env.user.has_group('gt_supplier_certificate_gate.group_manager'):
                raise AccessError('Only Certificate Managers can select unassigned responsibilities.')
        elif type(owner) is not int or owner < 0:
            raise ValidationError('Invalid renewal owner.')
        elif owner:
            user = scoped.env['res.users'].browse(owner)
            user.check_access('read')
            if not user.exists() or not user.active or user.share or not (user.company_ids & companies):
                raise AccessError('Renewal owner is not authorized for the selected companies.')
        if f.get('window', 'all') not in ('all', '7', '30', '60', 'policy') or f.get('status', 'all') not in ('all', *(s for s, label in STATUS)):
            raise ValidationError('Unsupported reporting window or status.')
        return scoped, companies, f

    def _bounded(self, model, domain, field_names):
        records = self.env[model].search_fetch(domain, field_names, limit=LIMIT + 1, order='id')
        if len(records) > LIMIT:
            raise UserError('Reporting scope exceeds 20,000 records. Narrow the company or supplier filter; no partial totals are displayed.')
        return records

    def _build(self, companies, f):
        company_ids = companies.ids
        domain = [('company_id', 'in', company_ids)]
        if f.get('supplier_id'):
            domain.append(('supplier_id', '=', f['supplier_id']))
        if f.get('type_id'):
            domain.append(('type_id', '=', f['type_id']))
        versions = self._bounded('gt.supplier.certificate', domain, ['company_id', 'supplier_id', 'type_id', 'reference', 'valid_from', 'valid_until', 'state', 'owner_id', 'submitter_id', 'submitted_at', 'evidence_id'])
        rules = self._bounded('gt.certificate.requirement', [('company_id', 'in', company_ids), ('active', '=', True)], ['company_id', 'category_id', 'type_id'])
        works = self._bounded('gt.certificate.renewal', [('company_id', 'in', company_ids), ('state', 'not in', ['covered', 'cancelled'])], ['company_id', 'supplier_id', 'type_id', 'owner_id', 'due_date', 'state', 'expiry'])
        policies = self.env['gt.certificate.policy'].search([('company_id', 'in', company_ids)])
        policy_map = {p.company_id.id: p for p in policies}
        days = {c.id: c._gt_today() for c in companies}
        can_purchase = self.env['purchase.order'].has_access('read')
        order_domain = [('company_id', 'in', company_ids), ('state', 'in', ['draft', 'sent', 'to approve'])]
        if f.get('supplier_id'):
            order_domain.append(('partner_id', '=', f['supplier_id']))
        orders = self._bounded('purchase.order', order_domain, ['name', 'partner_id', 'company_id', 'state', 'user_id', 'order_line']) if can_purchase else self.env['purchase.order']
        evaluations = orders._gt_evaluations() if orders else {}
        by_key = {}
        key_for = lambda r: (r.company_id.id, r.supplier_id.id, r.type_id.id)
        for cert in versions:
            key = key_for(cert)
            by_key[key] = by_key.get(key, versions.browse()) | cert
        work_map = {key_for(w): w for w in works}
        rule_types = {c.id: set(rules.filtered(lambda r: r.company_id == c).type_id.ids) for c in companies}
        selected_category = self.env['product.category'].browse(f.get('category_id', []))
        family_ids = set(self.env['product.category'].search([('id', 'child_of', selected_category.id)]).ids) if selected_category else None
        if selected_category:
            path_ids = {int(x) for x in selected_category.parent_path.split('/') if x}
            rule_types = {c.id: set(rules.filtered(lambda r: r.company_id == c and (r.category_id.id in path_ids or r.category_id.id in family_ids)).type_id.ids) for c in companies}
        demand, order_keys, key_categories = set(), {}, {}
        for company, company_orders in orders.grouped('company_id').items():
            category_rules = self.env['gt.certificate.requirement']._for_categories(company_orders.order_line.product_id.categ_id, company)
            for order in company_orders:
                keys = set()
                for line in order.order_line:
                    if line.display_type or not line.product_id or line.product_qty <= 0 or (family_ids is not None and line.product_id.categ_id.id not in family_ids):
                        continue
                    for kind in category_rules.get(line.product_id.categ_id.id, self.env['gt.certificate.type']):
                        key = (company.id, order.partner_id.id, kind.id)
                        keys.add(key)
                        key_categories.setdefault(key, set()).add(line.product_id.categ_id.id)
                demand.update(keys)
                order_keys[order.id] = keys
        # Maintained relationships enable proactive expiry reporting; missing risk
        # KPI remains demand-scoped. Pending-only submissions still get a worklist.
        relevant = demand | {key for key in by_key if key[2] in rule_types.get(key[0], set())}
        universe = relevant | {key_for(c) for c in versions if c.state == 'pending'} | set(work_map)
        rows = {}
        for key in sorted(universe):
            company_id, supplier_id, type_id = key
            if (f.get('type_id') and type_id != f['type_id']) or (f.get('supplier_id') and supplier_id != f['supplier_id']):
                continue
            if selected_category and type_id not in rule_types.get(company_id, set()):
                continue
            cs = by_key.get(key, versions.browse()).sorted(lambda c: (c.valid_until, c.id), reverse=True)
            today = days[company_id]
            current = cs.filtered(lambda c: c.is_effective(today, company_id, supplier_id, type_id))
            expiry = max(current.mapped('valid_until'), default=False)
            if expiry:
                # Extend only contiguous, already approved, immutable coverage.
                approved = cs.filtered(lambda c: c.state == 'verified' and c.evidence_id)
                for cert in approved.sorted('valid_from'):
                    if cert.valid_from <= expiry + timedelta(days=1) and cert.valid_until > expiry:
                        expiry = cert.valid_until
                status = 'effective'
            else:
                status = 'future' if cs.filtered(lambda c: c.state == 'verified' and c.valid_from > today) else 'pending' if cs.filtered(lambda c: c.state == 'pending') else 'expired' if cs.filtered(lambda c: c.state == 'verified' and c.valid_until < today) else 'revoked' if cs.filtered(lambda c: c.state == 'revoked') else 'rejected' if cs.filtered(lambda c: c.state == 'rejected') else 'draft' if cs else 'missing'
                expiry = max(cs.filtered(lambda c: c.state == 'verified' and c.valid_until < today).mapped('valid_until'), default=False)
            work = work_map.get(key, works.browse())
            owner = work.owner_id if work else next((c.owner_id for c in cs if c.owner_id and c.owner_id.active and companies.browse(company_id) in c.owner_id.company_ids), policy_map[company_id].owner_id if company_id in policy_map else self.env['res.users'])
            if owner and (not owner.active or owner.share or company_id not in owner.company_ids.ids):
                owner = self.env['res.users']
            if f.get('owner_id') == 'unassigned' and owner or type(f.get('owner_id')) is int and f.get('owner_id') and owner.id != f['owner_id']:
                continue
            chosen = f.get('status', 'all')
            if chosen not in ('all', status) and not (chosen in ('pending', 'rejected', 'revoked', 'draft') and cs.filtered(lambda c: c.state == chosen)):
                continue
            remaining = (expiry - today).days if status == 'effective' else None
            window = f.get('window', 'all')
            horizon = policy_map[company_id].lead_days if window == 'policy' and company_id in policy_map else 30 if window == 'policy' else int(window) if window != 'all' else None
            if horizon is not None and (remaining is None or not 0 <= remaining <= horizon):
                continue
            bucket = 'expired' if status == 'expired' else 'missing' if remaining is None else 'seven' if remaining <= 7 else 'thirty' if remaining <= 30 else 'sixty' if remaining <= 60 else 'later'
            rule_categories = rules.filtered(lambda r: r.company_id.id == company_id and r.type_id.id == type_id).category_id.ids
            rows[key] = {'key': key, 'company': companies.browse(company_id), 'supplier': self.env['res.partner'].browse(supplier_id), 'kind': self.env['gt.certificate.type'].browse(type_id), 'owner': owner, 'work': work, 'status': status, 'expiry': expiry, 'days': remaining, 'bucket': bucket, 'demand': key in demand, 'relevant': key in relevant, 'categories': key_categories.get(key, set()) or set(rule_categories), 'versions': cs}
        blocked = {}
        for order in orders:
            matches = order_keys.get(order.id, set()).intersection(rows)
            selected_failures = [x for x in evaluations[order.id]['failures'] if (order.company_id.id, order.partner_id.id, x['type_id']) in matches]
            if selected_failures:
                blocked[order.id] = {'order': order, 'result': evaluations[order.id], 'selected_failures': selected_failures}
        pending = versions.filtered(lambda c: c.state == 'pending' and c.evidence_id and key_for(c) in rows)
        activities = self.env['mail.activity'].search([('gt_renewal_id', 'in', [r['work'].id for r in rows.values() if r['work']]), ('active', '=', True)])
        overdue = activities.filtered(lambda a: a.date_deadline < days[a.gt_renewal_id.company_id.id])
        return {'rows': rows, 'blocked': blocked, 'pending': pending, 'overdue': overdue, 'companies': companies, 'can_purchase': can_purchase, 'versions': versions, 'works': works, 'policies': policies}

    @api.model
    def get_data(self, filters=None):
        scoped, companies, f = self._scope(filters)
        data = scoped._build(companies, f)
        rows = data['rows']
        relevant = [r for r in rows.values() if r['relevant']]
        kpis = {'blocked': len(data['blocked']) if data['can_purchase'] else None, 'expiring': sum(r['status'] == 'effective' and r['days'] <= 30 for r in relevant), 'missing': sum(r['demand'] and r['status'] != 'effective' for r in relevant), 'pending': len(data['pending']), 'overdue': len(data['overdue'])}
        serialize = lambda r: {'key': list(r['key']), 'supplier': r['supplier'].display_name, 'company': r['company'].display_name, 'certificate': r['kind'].name, 'owner': r['owner'].name if r['owner'] else 'Unassigned', 'status': dict(STATUS)[r['status']], 'expiry': str(r['expiry']) if r['expiry'] else False}
        blocked_preview = [{'id': i, 'name': v['order'].name, 'supplier': v['order'].partner_id.display_name, 'company': v['order'].company_id.name, 'details': v['order']._gt_format(v['result']), 'state': v['order'].state} for i, v in list(data['blocked'].items())[:8]]
        options_keys = set((c.company_id.id, c.supplier_id.id, c.type_id.id) for c in data['versions']) | set(rows)
        suppliers = scoped.env['res.partner'].browse(sorted({k[1] for k in options_keys}))
        owners = scoped.env['res.users'].search([('share', '=', False), ('active', '=', True), ('company_ids', 'in', companies.ids)])
        categories = scoped.env['gt.certificate.requirement'].search([('company_id', 'in', companies.ids), ('active', '=', True)]).category_id
        ancestor_ids = {int(x) for c in categories for x in c.parent_path.split('/') if x}
        categories = scoped.env['product.category'].search([('id', 'in', list(ancestor_ids | set(categories.ids)))])
        return {'kpis': kpis, 'chart': [{'key': 'bucket_' + key, 'label': label, 'count': sum(r['bucket'] == key for r in relevant)} for key, label in BUCKETS], 'blocked': blocked_preview, 'requirements': [serialize(r) for r in relevant[:8]], 'pending': [{'id': c.id, 'supplier': c.supplier_id.display_name, 'certificate': c.type_id.name, 'company': c.company_id.name, 'submitted_at': fields.Datetime.to_string(c.submitted_at)} for c in data['pending'][:8]], 'overdue': [{'id': a.gt_renewal_id.id, 'supplier': a.gt_renewal_id.supplier_id.display_name, 'certificate': a.gt_renewal_id.type_id.name, 'owner': a.user_id.name, 'due_date': str(a.date_deadline)} for a in data['overdue'][:8]], 'updated_at': fields.Datetime.to_string(fields.Datetime.now()), 'can_review': self.env.user.has_group('gt_supplier_certificate_gate.group_reviewer'), 'can_manage': self.env.user.has_group('gt_supplier_certificate_gate.group_manager'), 'can_purchase': data['can_purchase'], 'options': {'companies': [{'id': c.id, 'name': c.name} for c in self.env.user.company_ids], 'owners': [{'id': u.id, 'name': u.name} for u in owners], 'suppliers': [{'id': s.id, 'name': s.display_name} for s in suppliers], 'types': [{'id': t.id, 'name': t.name} for t in scoped.env['gt.certificate.type'].search([])], 'categories': [{'id': c.id, 'name': c.display_name} for c in categories]}, 'contract': 'Current authorized RFQ gate failures, not historical confirmation attempts; distinct supplier/company/type coverage. Approved contiguous renewals extend the coverage horizon.'}

    @api.model
    def open_kpi(self, metric, filters=None):
        if metric not in ('blocked', 'expiring', 'missing', 'pending', 'overdue', 'coverage', *('bucket_' + k for k, label in BUCKETS)):
            raise ValidationError('Unsupported dashboard action.')
        scoped, companies, f = self._scope(filters)
        data = scoped._build(companies, f)
        context = {'allowed_company_ids': companies.ids}
        if metric == 'blocked':
            if not data['can_purchase']:
                raise AccessError('Purchase Order read permission is required.')
            return {'type': 'ir.actions.act_window', 'name': 'Currently Blocked Purchase Orders', 'res_model': 'purchase.order', 'views': [(self.env.ref('gt_supplier_certificate_gate.view_blocked_list').id, 'list'), (False, 'form')], 'domain': [('id', 'in', list(data['blocked']))], 'context': context}
        if metric in ('pending', 'overdue'):
            records = data[metric]
            return {'type': 'ir.actions.act_window', 'name': 'Pending Verification' if metric == 'pending' else 'Overdue Follow-ups', 'res_model': records._name, 'views': [(False, 'list'), (False, 'form')], 'domain': [('id', 'in', records.ids)], 'context': context}
        selected = [r for r in data['rows'].values() if r['relevant'] and (metric == 'coverage' or metric == 'expiring' and r['status'] == 'effective' and r['days'] <= 30 or metric == 'missing' and r['demand'] and r['status'] != 'effective' or metric == 'bucket_' + r['bucket'])]
        stamp = fields.Datetime.now()
        vals = []
        for r in selected:
            vals.append({'company_id': r['company'].id, 'supplier_id': r['supplier'].id, 'type_id': r['kind'].id, 'owner_id': r['owner'].id, 'expiry': r['expiry'], 'status': r['status'], 'bucket': r['bucket'], 'evaluated_at': stamp, 'work_id': r['work'].id, 'category_ids': [Command.set(list(r['categories']))], 'order_ids': [Command.set([i for i, v in data['blocked'].items() if (v['order'].company_id.id, v['order'].partner_id.id, r['kind'].id) == r['key'] and any(x['type_id'] == r['kind'].id for x in v['result']['failures'])])]})
        report = scoped.env['gt.certificate.coverage.report']
        records = super(CoverageReport, report).create(vals)
        return {'type': 'ir.actions.act_window', 'name': 'Certificate Coverage - Evaluated on Request', 'res_model': report._name, 'views': [(False, 'list'), (False, 'form')], 'domain': [('id', 'in', records.ids)], 'context': context}

    @api.model
    def open_record(self, kind, record_id, filters=None):
        if kind not in ('blocked', 'pending', 'overdue') or type(record_id) is not int:
            raise ValidationError('Unsupported dashboard record.')
        scoped, companies, f = self._scope(filters)
        data = scoped._build(companies, f)
        allowed = list(data['blocked']) if kind == 'blocked' else data['pending'].ids if kind == 'pending' else data['overdue'].gt_renewal_id.ids
        if record_id not in allowed:
            raise AccessError('The selected record is no longer in this authorized dashboard result. Refresh the dashboard.')
        model = {'blocked': 'purchase.order', 'pending': 'gt.supplier.certificate', 'overdue': 'gt.certificate.renewal'}[kind]
        scoped.env[model].browse(record_id).check_access('read')
        return {'type': 'ir.actions.act_window', 'name': 'Certificate Follow-up', 'res_model': model, 'res_id': record_id, 'views': [(False, 'form')], 'context': {'allowed_company_ids': companies.ids}}


class CoverageReport(models.TransientModel):
    _name = 'gt.certificate.coverage.report'
    _description = 'Authorized Certificate Coverage Snapshot'
    _transient_max_hours = 1
    company_id = fields.Many2one('res.company', required=True, readonly=True)
    supplier_id = fields.Many2one('res.partner', required=True, readonly=True)
    type_id = fields.Many2one('gt.certificate.type', required=True, readonly=True)
    owner_id = fields.Many2one('res.users', readonly=True)
    expiry = fields.Date(string='Continuous Verified Coverage Until', readonly=True)
    status = fields.Selection(STATUS, readonly=True)
    bucket = fields.Selection(BUCKETS + [('later', 'Beyond 60 Days')], readonly=True)
    evaluated_at = fields.Datetime(readonly=True)
    work_id = fields.Many2one('gt.certificate.renewal', readonly=True)
    category_ids = fields.Many2many('product.category', readonly=True)
    order_ids = fields.Many2many('purchase.order', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError('Coverage rows are generated only by the authorized dashboard.')

    def write(self, vals):
        raise AccessError('Coverage report snapshots are read-only. Refresh from the dashboard.')

    def action_orders(self):
        self.ensure_one()
        self.check_access('read')
        return self.env['gt.certificate.dashboard'].open_kpi('blocked', {'company_id': self.company_id.id, 'supplier_id': self.supplier_id.id, 'type_id': self.type_id.id})

    def action_certificates(self):
        self.ensure_one()
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': 'Certificate Metadata and Versions', 'res_model': 'gt.supplier.certificate', 'views': [(False, 'list'), (False, 'form')], 'domain': [('company_id', '=', self.company_id.id), ('supplier_id', '=', self.supplier_id.id), ('type_id', '=', self.type_id.id)], 'context': {'allowed_company_ids': self.company_id.ids}}
