from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

SNAPSHOT = {'gt_checked_at', 'gt_check_result', 'gt_check_summary'}


class Requirement(models.Model):
    _inherit = 'gt.certificate.requirement'

    @api.model
    def _for_categories(self, categories, company):
        if not self.env.su and company not in self.env.user.company_ids:
            raise AccessError('Purchasing company is not authorized.')
        paths = {cat.id: {int(i) for i in cat.parent_path.split('/') if i} for cat in categories}
        ancestor_ids = set().union(*paths.values()) if paths else set()
        rules = self.search([('company_id', '=', company.id), ('category_id', 'in', list(ancestor_ids)), ('active', '=', True)])
        return {cat_id: rules.filtered(lambda r: r.category_id.id in ancestors).type_id for cat_id, ancestors in paths.items()}


class Purchase(models.Model):
    _inherit = 'purchase.order'
    gt_dashboard_blocked = fields.Boolean(compute='_compute_gt_dashboard_blocked', search='_search_gt_dashboard_blocked', groups='gt_supplier_certificate_gate.group_user')

    def _compute_gt_dashboard_blocked(self):
        values = self._gt_evaluations(_limit=20000)
        for order in self:
            order.gt_dashboard_blocked = values[order.id]['status'] == 'blocked'

    @api.model
    def _search_gt_dashboard_blocked(self, operator, value):
        if operator not in ('in', 'not in') or not isinstance(value, (list, tuple)) or any(type(v) is not bool for v in value):
            return NotImplemented
        service, companies, filters = self.env['gt.certificate.dashboard']._scope(self.env.context.get('gt_dashboard_filters', {}))
        data = service._build(companies, filters)
        positive = (True in value) if operator == 'in' else (True not in value)
        return [('id', 'in' if positive else 'not in', list(data['blocked']))]

    gt_current_status = fields.Selection([('blocked', 'Blocked'), ('ready', 'Ready for Retry'), ('not_required', 'No Requirement')], compute='_compute_gt_current', string='Current Certificate Gate', groups='gt_supplier_certificate_gate.group_user')
    gt_current_details = fields.Text(compute='_compute_gt_current', string='Current Blocking Details', groups='gt_supplier_certificate_gate.group_user')

    def _compute_gt_current(self):
        results = self._gt_evaluations()
        for order in self:
            order.gt_current_status = results[order.id]['status']
            order.gt_current_details = order._gt_format(results[order.id])

    gt_checked_at = fields.Datetime(string='Last Certificate Check', readonly=True, copy=False)
    gt_check_result = fields.Selection([('blocked', 'Blocked'), ('ready', 'Ready for Retry'), ('not_required', 'No Requirement')], string='Last Check Result', readonly=True, copy=False)
    gt_check_summary = fields.Text(string='Last Check Details', readonly=True, copy=False)

    def _gt_lock(self):
        self.check_access('write')
        if self:
            self.flush_recordset()
            self.env.cr.execute('SELECT id FROM purchase_order WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(self.ids)])
            self.order_line.flush_recordset()
            self.env.cr.execute('SELECT id FROM purchase_order_line WHERE order_id IN %s ORDER BY id FOR UPDATE', [tuple(self.ids)])
            self.invalidate_recordset()
            self.order_line.invalidate_recordset()

    def _gt_touch_for_line_change(self):
        # Version the parent before changing children. A concurrent confirmation
        # using an older repeatable-read snapshot must retry, including when a
        # zero-priced new line would leave native monetary totals unchanged.
        self._gt_lock()
        super(Purchase, self).write({'write_date': fields.Datetime.now()})
        self.flush_recordset(['write_date'])

    def _gt_evaluations(self, _limit=None):
        """Request-local batch preparation; enforcement still locks and reads fresh."""
        self.check_access('read')
        prepared = {}
        for company, orders in self.grouped('company_id').items():
            categories = orders.order_line.product_id.categ_id
            requirements = self.env['gt.certificate.requirement']._for_categories(categories, company)
            type_ids = {i for types in requirements.values() for i in types.ids}
            versions = self.env['gt.supplier.certificate'].search([('company_id', '=', company.id), ('supplier_id', 'in', orders.partner_id.ids), ('type_id', 'in', list(type_ids))], limit=_limit + 1 if _limit else None)
            if _limit and len(versions) > _limit:
                raise UserError('Reporting scope is too large. Narrow the company or supplier filter; no partial totals are displayed.')
            by_supplier = versions.grouped('supplier_id')
            for order in orders:
                prepared[order.id] = order._gt_evaluate(_prepared=(requirements, by_supplier.get(order.partner_id, versions.browse())))
        return prepared

    def _gt_evaluate(self, lock=False, _prepared=None):
        self.ensure_one()
        self.check_access('read')
        if not self.env.su and self.company_id not in self.env.user.company_ids:
            raise AccessError('Purchasing company is not authorized.')
        if lock:
            self._gt_lock()
        lines = self.order_line.filtered(lambda l: not l.display_type and l.product_id and l.product_qty > 0)
        if _prepared is not None and not lock:
            requirements, candidates = _prepared
        else:
            requirements = self.env['gt.certificate.requirement']._for_categories(lines.product_id.categ_id, self.company_id)
            type_ids = set().union(*(set(t.ids) for t in requirements.values())) if requirements else set()
            candidates = self.env['gt.supplier.certificate'].search([('company_id', '=', self.company_id.id), ('supplier_id', '=', self.partner_id.id), ('type_id', 'in', list(type_ids))])
        if lock and candidates:
            # Serialize certificate revocation with confirmation; no PDF reads.
            candidates.flush_recordset()
            self.env.cr.execute('SELECT id FROM gt_supplier_certificate WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(candidates.ids)])
            candidates.invalidate_recordset()
        today = self.company_id._gt_today()
        failures = []
        required = 0
        for line in lines:
            for kind in requirements.get(line.product_id.categ_id.id, self.env['gt.certificate.type']):
                required += 1
                versions = candidates.filtered(lambda c: c.type_id == kind)
                if any(c.is_effective(today, self.company_id.id, self.partner_id.id, kind.id) for c in versions):
                    continue
                reason = self._gt_reason(versions, today)
                failures.append({'line_id': line.id, 'product': line.product_id.display_name, 'type_id': kind.id, 'certificate': kind.name, 'reason': reason})
        return {'status': 'blocked' if failures else 'ready' if required else 'not_required', 'failures': failures, 'required': required, 'date': today}

    def _gt_reason(self, versions, today):
        if not versions:
            return 'Missing certificate. Submit evidence for independent review.'
        future = versions.filtered(lambda c: c.state == 'verified' and c.valid_from > today)
        expired = versions.filtered(lambda c: c.state == 'verified' and c.valid_until < today)
        if future:
            return 'Verified certificate is not yet effective (starts %s).' % min(future.mapped('valid_from'))
        if versions.filtered(lambda c: c.state == 'pending'):
            return 'Certificate is pending reviewer approval.'
        if expired:
            return 'Verified certificate expired on %s. Submit a renewal for review.' % max(expired.mapped('valid_until'))
        if versions.filtered(lambda c: c.state == 'revoked'):
            return 'Certificate approval was revoked. Submit new evidence.'
        if versions.filtered(lambda c: c.state == 'rejected'):
            return 'Certificate was rejected. Submit corrected evidence.'
        return 'Certificate is unverified. Submit evidence for independent review.'

    def _gt_format(self, result):
        if not result['failures']:
            return 'No applicable certificate requirements.' if result['status'] == 'not_required' else 'All certificate requirements satisfied. Retry the normal purchase action.'
        return '\n'.join('Line %s - %s | %s: %s' % (next((i for i, l in enumerate(self.order_line, 1) if l.id == f['line_id']), '?'), f['product'], f['certificate'], f['reason']) for f in result['failures'])

    def _gt_assert(self):
        failures = []
        for order in self.sorted('id'):
            result = order._gt_evaluate(lock=True)
            if result['failures']:
                failures.append('%s cannot proceed:\n%s' % (order.name, order._gt_format(result)))
        if failures:
            raise UserError('\n\n'.join(failures))

    def action_gt_check_certificates(self):
        for order in self:
            order.check_access('write')
            result = order._gt_evaluate()
            super(Purchase, order).write({'gt_checked_at': fields.Datetime.now(), 'gt_check_result': result['status'], 'gt_check_summary': order._gt_format(result)})
        return True

    def button_confirm(self):
        self.filtered(lambda o: o.state in ('draft', 'sent'))._gt_assert()
        return super().button_confirm()

    def button_approve(self, force=False):
        self.filtered(lambda o: o.state in ('draft', 'sent', 'to approve') and o._approval_allowed())._gt_assert()
        return super().button_approve(force=force)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('state', self.env.context.get('default_state', 'draft')) in ('purchase', 'to approve'):
                raise UserError('Create an RFQ and use the native purchase confirmation action.')
            if SNAPSHOT & vals.keys():
                raise AccessError('Check results are generated by the certificate evaluator.')
        return super().create(vals_list)

    def write(self, vals):
        if SNAPSHOT & vals.keys():
            raise AccessError('Check results are generated by the certificate evaluator.')
        if vals.get('state') in ('purchase', 'to approve'):
            advancing = self.filtered(lambda o: o.state != vals['state'])
            if advancing and {'partner_id', 'company_id', 'order_line'} & vals.keys():
                raise UserError('Save RFQ changes before advancing its state.')
            advancing._gt_assert()
            if vals['state'] == 'purchase' and any(not o._approval_allowed() for o in advancing):
                raise AccessError('Native purchase approval authorization is required.')
        result = super().write(vals)
        if {'partner_id', 'company_id', 'order_line'} & vals.keys():
            self.filtered(lambda o: o.state == 'purchase')._gt_assert()
        return result


class PurchaseLine(models.Model):
    _inherit = 'purchase.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        order_ids = {v.get('order_id') or self.env.context.get('default_order_id') for v in vals_list}
        self.env['purchase.order'].browse([i for i in order_ids if i])._gt_touch_for_line_change()
        lines = super().create(vals_list)
        lines.order_id.filtered(lambda o: o.state == 'purchase')._gt_assert()
        return lines

    def write(self, vals):
        orders = self.order_id
        if {'product_id', 'product_qty', 'order_id', 'display_type', 'is_downpayment'} & vals.keys():
            targets = orders | self.env['purchase.order'].browse(vals.get('order_id', []))
            targets._gt_touch_for_line_change()
        result = super().write(vals)
        if {'product_id', 'product_qty', 'order_id', 'display_type', 'is_downpayment'} & vals.keys():
            (orders | self.order_id).filtered(lambda o: o.state == 'purchase')._gt_assert()
        return result
