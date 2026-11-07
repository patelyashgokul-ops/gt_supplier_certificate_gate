from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)
from psycopg2 import IntegrityError
from odoo import api, fields, models
from odoo.exceptions import AccessError, ConcurrencyError, UserError, ValidationError


class Policy(models.Model):
    _name = 'gt.certificate.policy'
    _description = 'Company Certificate Renewal Policy'
    _check_company_auto = True
    _rec_name = 'company_id'
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, ondelete='restrict')
    lead_days = fields.Integer(default=30, required=True)
    owner_id = fields.Many2one('res.users', string='Default Renewal Owner', check_company=True)
    certificate_cursor = fields.Integer(default=0, readonly=True)
    order_cursor = fields.Integer(default=0, readonly=True)
    work_cursor = fields.Integer(default=0, readonly=True)
    _company_unique = models.Constraint('UNIQUE(company_id)', 'One renewal policy per company.')
    _lead_check = models.Constraint('CHECK(lead_days >= 0 AND lead_days <= 365)', 'Reminder lead time must be between 0 and 365 days.')

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'certificate_cursor', 'order_cursor', 'work_cursor'}
        if any(protected & vals.keys() for vals in vals_list):
            raise AccessError('Scan cursors are controlled by the scheduler.')
        clean = {k: v for k, v in self.env.context.items() if k not in {'default_' + f for f in protected}}
        return super(Policy, self.with_context(clean)).create(vals_list)

    @api.constrains('owner_id', 'company_id')
    def _check_owner(self):
        for record in self:
            _validate_owner(record.owner_id, record.company_id)

    def write(self, vals):
        if {'certificate_cursor', 'order_cursor', 'work_cursor'} & vals.keys():
            raise AccessError('Scan cursors are controlled by the scheduler.')
        return super().write(vals)


def _validate_owner(owner, company):
    if owner and (not owner.active or owner.share or company not in owner.company_ids or not owner.has_group('gt_supplier_certificate_gate.group_user')):
        raise ValidationError('Owner must be an active Certificate User authorized for this company.')


class Renewal(models.Model):
    _name = 'gt.certificate.renewal'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Certificate Renewal Follow-up'
    _check_company_auto = True
    _rec_name = 'supplier_id'
    _order = 'due_date, id'
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True, ondelete='restrict')
    supplier_id = fields.Many2one('res.partner', required=True, check_company=True, index=True, ondelete='restrict')
    type_id = fields.Many2one('gt.certificate.type', required=True, index=True, ondelete='restrict')
    expiry = fields.Date(readonly=True)
    owner_id = fields.Many2one('res.users', string='Renewal Owner', check_company=True, tracking=True)
    due_date = fields.Date(string='Follow-up Deadline', required=True, tracking=True)
    state = fields.Selection([('supplier', 'Awaiting Supplier'), ('review', 'Pending Review'), ('future', 'Approved for Future Validity'), ('covered', 'Currently Covered'), ('cancelled', 'No Longer Required')], default='supplier', required=True, readonly=True, tracking=True, index=True)
    activity_acknowledged = fields.Boolean(readonly=True, copy=False)
    expiry_bucket = fields.Selection([('missing', 'No Effective Evidence'), ('expired', 'Expired'), ('7', 'Expiring within 7 Days'), ('30', 'Expiring within 30 Days'), ('later', 'Later')], compute='_compute_work_flags', search='_search_expiry_bucket')
    unassigned = fields.Boolean(compute='_compute_work_flags', search='_search_unassigned')
    overdue = fields.Boolean(compute='_compute_work_flags', search='_search_overdue')
    _open_unique = models.UniqueIndex("(company_id, supplier_id, type_id) WHERE state NOT IN ('covered', 'cancelled')", 'An open follow-up already exists for this supplier/company/type.')

    def _compute_work_flags(self):
        for record in self:
            days = (record.expiry - record.company_id._gt_today()).days if record.expiry else None
            record.expiry_bucket = 'missing' if days is None else 'expired' if days < 0 else '7' if days <= 7 else '30' if days <= 30 else 'later'
            record.unassigned = not record.owner_id or not record.owner_id.active
            record.overdue = record.state not in ('covered', 'cancelled') and record.due_date < record.company_id._gt_today()

    @api.model
    def _search_expiry_bucket(self, operator, value):
        if operator not in ('in', 'not in'):
            return NotImplemented
        ids = self.search([]).filtered(lambda r: r.expiry_bucket in value).ids
        return [('id', operator, ids)]

    @api.model
    def _search_unassigned(self, operator, value):
        if operator != 'in':
            return NotImplemented
        domain = ['|', ('owner_id', '=', False), ('owner_id.active', '=', False)]
        return domain if True in value else ['!', *domain]

    @api.model
    def _search_overdue(self, operator, value):
        if operator != 'in':
            return NotImplemented
        # Dates vary by company, so use the same deterministic business calendar.
        ids = self.search([('state', 'not in', ['covered', 'cancelled'])]).filtered(lambda r: r.due_date < r.company_id._gt_today()).ids
        return [('id', 'in' if True in value else 'not in', ids)]

    @api.constrains('owner_id', 'company_id')
    def _check_owner(self):
        for record in self:
            _validate_owner(record.owner_id, record.company_id)

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError('Renewal work is generated from certificate requirements and procurement demand.')

    def write(self, vals):
        self.check_access('write')
        if vals.keys() - {'owner_id', 'due_date'}:
            raise AccessError('Renewal identity and coverage are controlled by the evaluator.')
        manager = self.env.user.has_group('gt_supplier_certificate_gate.group_manager')
        if 'owner_id' in vals and not manager:
            raise AccessError('Only a Certificate Manager can reassign renewal ownership.')
        if not manager and any(r.owner_id != self.env.user for r in self):
            raise AccessError('Only the owner or manager can reschedule this follow-up.')
        self._lock_work()
        result = super().write(vals)
        for record in self:
            record._ensure_activity()
        return result

    def unlink(self):
        raise AccessError('Renewal cycles are retained for follow-up history.')

    def _lock_work(self):
        if self:
            self.flush_recordset()
            self.env.cr.execute('SELECT id FROM gt_certificate_renewal WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(self.ids)])
            self.invalidate_recordset()

    def _update(self, vals):
        return super().write(vals)

    def _ensure_activity(self):
        self.ensure_one()
        self._lock_work()
        activities = self.env['mail.activity'].search([('gt_renewal_id', '=', self.id), ('active', '=', True)])
        if self.state in ('covered', 'cancelled'):
            activities.action_feedback(feedback='Renewal evaluated: %s.' % self.state)
            return
        if not self.owner_id:
            activities.unlink()
            return
        if activities:
            activities.write({'user_id': self.owner_id.id, 'date_deadline': self.due_date})
        elif not self.activity_acknowledged:
            # Ignore client automation-skip context: work generation is authoritative.
            self.with_context(mail_activity_automation_skip=False).activity_schedule('gt_supplier_certificate_gate.activity_type_renewal', date_deadline=self.due_date, user_id=self.owner_id.id, summary='Renew %s - %s' % (self.type_id.name, self.supplier_id.name), note='Company-specific certificate follow-up. Evidence requires independent reviewer approval.', gt_renewal_id=self.id)

    def action_refresh(self):
        if not self.env.user.has_group('gt_supplier_certificate_gate.group_manager'):
            raise AccessError('Certificate Manager permission is required.')
        for work in self:
            work.check_access('write')
            self._sync_key(work.company_id, work.supplier_id, work.type_id)
        return True

    def action_request_followup(self):
        if not self.env.user.has_group('gt_supplier_certificate_gate.group_manager'):
            raise AccessError('Certificate Manager permission is required.')
        for work in self:
            work.check_access('write')
            work._lock_work()
            work._update({'activity_acknowledged': False})
            work._ensure_activity()
        return True

    @api.model
    def _sync_key(self, company, supplier, kind):
        # Called only by private scheduler, validated manager refresh, or private
        # reviewer event hook. No public caller-selected privileged record scope.
        if not self.env.su and company not in self.env.companies:
            raise AccessError('Renewal company is not authorized.')
        today = company._gt_today()
        policy = self.env['gt.certificate.policy'].search([('company_id', '=', company.id)], limit=1)
        lead = policy.lead_days if policy else 30
        versions = self.env['gt.supplier.certificate'].search([('company_id', '=', company.id), ('supplier_id', '=', supplier.id), ('type_id', '=', kind.id)])
        current = versions.filtered(lambda c: c.is_effective(today, company.id, supplier.id, kind.id))
        expiry = max(current.mapped('valid_until')) if current else max(versions.filtered(lambda c: c.state in ('verified', 'revoked')).mapped('valid_until'), default=False)
        relevant = bool(self.env['gt.certificate.requirement'].search_count([('company_id', '=', company.id), ('type_id', '=', kind.id), ('active', '=', True)], limit=1))
        covered = bool(current and expiry > today + timedelta(days=lead))
        state = 'cancelled' if not relevant else 'covered' if covered else 'review' if versions.filtered(lambda c: c.state == 'pending') else 'future' if versions.filtered(lambda c: c.state == 'verified' and c.valid_from > today) else 'supplier'
        work = self.search([('company_id', '=', company.id), ('supplier_id', '=', supplier.id), ('type_id', '=', kind.id), ('state', 'not in', ['covered', 'cancelled'])], limit=1)
        if not work and state in ('covered', 'cancelled'):
            return self.browse()
        if not work:
            owner = next((c.owner_id for c in versions if c.owner_id and c.owner_id.active and not c.owner_id.share and company in c.owner_id.company_ids and c.owner_id.has_group('gt_supplier_certificate_gate.group_user')), policy.owner_id if policy and policy.owner_id.active and not policy.owner_id.share and company in policy.owner_id.company_ids and policy.owner_id.has_group('gt_supplier_certificate_gate.group_user') else self.env['res.users'])
            vals = {'company_id': company.id, 'supplier_id': supplier.id, 'type_id': kind.id, 'expiry': expiry, 'owner_id': owner.id, 'due_date': max(today, expiry - timedelta(days=7)) if expiry else today, 'state': state}
            # Partial unique index arbitrates concurrent creation. A real database
            # serialization conflict is retried by Odoo, never silently swallowed.
            try:
                with self.env.cr.savepoint():
                    work = super(Renewal, self).create(vals)
            except IntegrityError as exc:
                if exc.diag.constraint_name != 'gt_certificate_renewal_open_unique':
                    raise
                work = self.search([('company_id', '=', company.id), ('supplier_id', '=', supplier.id), ('type_id', '=', kind.id), ('state', 'not in', ['covered', 'cancelled'])], limit=1)
                if not work:
                    # Repeatable-read snapshots may not see the competing row.
                    # Odoo's bounded request retry must begin a fresh transaction.
                    raise ConcurrencyError('Concurrent renewal cycle; retry transaction.') from exc
        work._lock_work()
        updates = {'state': state, 'expiry': expiry}
        if work.owner_id and (not work.owner_id.active or work.owner_id.share or company not in work.owner_id.company_ids or not work.owner_id.has_group('gt_supplier_certificate_gate.group_user')):
            updates['owner_id'] = False
        work._update(updates)
        work._ensure_activity()
        return work

    @api.model
    def _refresh_company(self, company):
        # Demand scope: outstanding RFQs / pending approvals and explicitly
        # maintained supplier certificate relationships for active required types.
        policy = self.env['gt.certificate.policy'].search([('company_id', '=', company.id)], limit=1)
        if not policy:
            policy = self.env['gt.certificate.policy'].create({'company_id': company.id})
        active_types = self.env['gt.certificate.requirement'].search([('company_id', '=', company.id), ('active', '=', True)]).type_id
        certificates = self.env['gt.supplier.certificate'].search([('company_id', '=', company.id), ('type_id', 'in', active_types.ids), ('id', '>', policy.certificate_cursor)], order='id', limit=200)
        orders = self.env['purchase.order'].search([('company_id', '=', company.id), ('state', 'in', ['draft', 'sent', 'to approve']), ('id', '>', policy.order_cursor)], order='id', limit=200)
        works = self.search([('company_id', '=', company.id), ('state', 'not in', ['covered', 'cancelled']), ('id', '>', policy.work_cursor)], order='id', limit=200)
        keys = {(c.supplier_id.id, c.type_id.id) for c in certificates}
        for order in orders:
            lines = order.order_line.filtered(lambda l: not l.display_type and l.product_id and l.product_qty > 0)
            requirements = self.env['gt.certificate.requirement']._for_categories(lines.product_id.categ_id, company)
            for types in requirements.values():
                keys.update((order.partner_id.id, type_id) for type_id in types.ids)
            if any(requirements.values()):
                order.action_gt_check_certificates()
        keys.update((w.supplier_id.id, w.type_id.id) for w in works)
        for supplier_id, type_id in sorted(keys):
            try:
                with self.env.cr.savepoint():
                    self._sync_key(company, self.env['res.partner'].browse(supplier_id), self.env['gt.certificate.type'].browse(type_id))
            except (UserError, ValidationError):
                # Expected invalid owner/relationship errors are isolated. Unexpected
                # exceptions propagate so the scheduler records a genuine failure.
                _logger.warning('Invalid renewal relationship: company=%s supplier=%s type=%s', company.id, supplier_id, type_id)
        super(Policy, policy).write({'certificate_cursor': certificates[-1].id if len(certificates) == 200 else 0, 'order_cursor': orders[-1].id if len(orders) == 200 else 0, 'work_cursor': works[-1].id if len(works) == 200 else 0})
        return any(len(records) == 200 for records in (certificates, orders, works))

    @api.model
    def _cron_renewals(self):
        # ir.cron runs as explicitly configured trusted root. No arbitrary sudo
        # or client-driven company list. No PDF is read and no PO is confirmed.
        for company in self.env['res.company'].search([]):
            scoped = self.with_context(allowed_company_ids=company.ids)
            for batch in range(10):
                more = scoped._refresh_company(company)
                if self.env.context.get('cron_id') and not self.env['ir.cron']._commit_progress(1, remaining=1 if more else 0):
                    return
                if not more:
                    break


class Activity(models.Model):
    _inherit = 'mail.activity'
    gt_renewal_id = fields.Many2one('gt.certificate.renewal', ondelete='restrict', copy=False, index=True)
    _gt_open_unique = models.UniqueIndex('(gt_renewal_id) WHERE active AND gt_renewal_id IS NOT NULL', 'An active renewal Activity already exists.')

    @api.constrains('gt_renewal_id', 'res_model_id', 'res_id', 'user_id')
    def _check_gt_target(self):
        for activity in self.filtered('gt_renewal_id'):
            work = activity.gt_renewal_id
            work.check_access('read')
            if activity.res_model != work._name or activity.res_id != work.id or activity.user_id != work.owner_id:
                raise ValidationError('Renewal Activity must match its authorized work record and owner.')

    def write(self, vals):
        if 'gt_renewal_id' in vals:
            raise AccessError('Renewal Activity identity is immutable.')
        result = super().write(vals)
        if vals.get('active') is False:
            self.gt_renewal_id._update({'activity_acknowledged': True})
        if 'date_deadline' in vals:
            self.gt_renewal_id._update({'due_date': vals['date_deadline']})
        return result


class Certificate(models.Model):
    _inherit = 'gt.supplier.certificate'

    @api.model
    def _recheck_orders(self, company, supplier, kind):
        if not self.env.su and company not in self.env.companies:
            raise AccessError('Recheck company is not authorized.')
        candidates = self.env['purchase.order'].search([('company_id', '=', company.id), ('partner_id', '=', supplier.id), ('state', 'in', ['draft', 'sent', 'to approve'])])
        affected = self.env['purchase.order']
        for order in candidates:
            lines = order.order_line.filtered(lambda l: not l.display_type and l.product_id and l.product_qty > 0)
            requirements = self.env['gt.certificate.requirement']._for_categories(lines.product_id.categ_id, company)
            if any(kind in types for types in requirements.values()):
                affected |= order
        affected.action_gt_check_certificates()
        return affected

    def _after_review(self):
        for certificate in self:
            # Reviewer has authority over this certificate, not automatically
            # over purchasing/renewal configuration. Narrow privilege only to
            # derived metadata for the same company/supplier/type. Never bytes.
            certificate.check_access('read')
            if not self.env.su and certificate.company_id not in self.env.user.company_ids:
                raise AccessError('Certificate company is not authorized.')
            scoped = certificate.sudo().with_context({'allowed_company_ids': certificate.company_id.ids})
            scoped.env['gt.certificate.renewal']._sync_key(scoped.company_id, scoped.supplier_id, scoped.type_id)
            scoped._recheck_orders(scoped.company_id, scoped.supplier_id, scoped.type_id)

    def _upload(self, content):
        result = super()._upload(content)
        self._after_review()
        return result

    def action_approve(self):
        result = super().action_approve()
        self._after_review()
        return result

    def action_reject(self, reason=None):
        result = super().action_reject(reason)
        self._after_review()
        return result

    def action_revoke(self, reason=None):
        result = super().action_revoke(reason)
        self._after_review()
        return result
