from datetime import date, timedelta
from unittest.mock import patch
from psycopg2.errors import CheckViolation
from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from .test_purchase_gate import TestPurchaseGate


@tagged('post_install', '-at_install', 'gt_phase4')
class TestRenewals(TestPurchaseGate):
    def policy(self, owner=None, lead=30, company=None):
        return self.env['gt.certificate.policy'].create({'company_id': (company or self.a).id, 'lead_days': lead, 'owner_id': (owner or self.manager).id})

    def sync(self, company=None, supplier=None, kind=None):
        return self.env['gt.certificate.renewal']._sync_key(company or self.a, supplier or self.vendor, kind or self.kind)

    def active_activities(self, work):
        return self.env['mail.activity'].search([('gt_renewal_id', '=', work.id), ('active', '=', True)])

    def test_reminder_boundaries_and_covered_history(self):
        self.requirement()
        self.policy()
        c = self.verified(valid_until='2026-12-05')  # 31 days
        self.assertFalse(self.sync())
        with patch.object(type(self.a), '_gt_today', lambda company: date(2026, 11, 5)):
            work = self.sync()
            self.assertTrue(work)
            self.assertEqual(len(self.active_activities(work)), 1)
            self.assertEqual(work.expiry, date(2026, 12, 5))
        for day in (date(2026, 11, 28), date(2026, 12, 5), date(2026, 12, 6)):
            with patch.object(type(self.a), '_gt_today', lambda company, d=day: d):
                self.assertEqual(self.sync().id, work.id)
        self.verified(valid_from='2026-11-04', valid_until='2027-12-05')
        self.assertEqual(work.state, 'covered')
        self.assertFalse(self.active_activities(work))
        self.assertFalse(self.sync())
        self.assertEqual(c.state, 'verified')

    def test_demand_missing_duplicate_cron_and_no_auto_confirm(self):
        self.requirement()
        self.policy()
        self.cert.unlink()
        orders = self.order() | self.order() | self.order() | self.order()
        cron = self.env.ref('gt_supplier_certificate_gate.cron_certificate_renewals')
        with self.registry_test_mode():
            self.assertTrue(cron.method_direct_trigger())
            self.assertTrue(cron.method_direct_trigger())
        work = self.env['gt.certificate.renewal'].search([('company_id', '=', self.a.id), ('supplier_id', '=', self.vendor.id), ('type_id', '=', self.kind.id), ('state', 'not in', ['covered', 'cancelled'])])
        self.assertEqual(len(work), 1)
        self.assertEqual(len(self.active_activities(work)), 1)
        orders.action_gt_check_certificates()
        orders.action_gt_check_certificates()
        self.assertEqual(len(self.active_activities(work)), 1)
        self.assertEqual(set(orders.mapped('state')), {'draft'})
        self.assertEqual(set(orders.mapped('gt_check_result')), {'blocked'})
        self.verified()
        self.assertEqual(work.state, 'covered')
        self.assertEqual(set(orders.mapped('gt_check_result')), {'ready'})
        self.assertEqual(set(orders.mapped('state')), {'draft'})
        orders.button_confirm()
        self.assertEqual(set(orders.mapped('state')), {'purchase'})

    def test_owner_reassignment_deadline_and_inactive(self):
        self.requirement()
        self.policy()
        work = self.sync()
        activity = self.active_activities(work)
        self.assertEqual(activity.user_id, self.manager)
        deadline = work.due_date
        new_owner = self.make_user('newowner', 'group_user')
        work.with_user(self.manager).write({'owner_id': new_owner.id})
        self.assertEqual(self.active_activities(work), activity)
        self.assertEqual(activity.user_id, new_owner)
        self.assertEqual(work.due_date, deadline)
        work.with_user(new_owner).write({'due_date': '2026-11-03'})
        self.assertEqual(activity.date_deadline, date(2026, 11, 3))
        self.assertTrue(work.overdue)
        with self.assertRaises(AccessError):
            work.with_user(self.buyer).write({'owner_id': self.buyer.id})
        unauthorized = self.env['res.users'].create({'name': 'B owner', 'login': 'gt_bowner', 'company_id': self.b.id, 'company_ids': [Command.set(self.b.ids)], 'group_ids': [Command.set([self.env.ref('gt_supplier_certificate_gate.group_user').id])]})
        with self.assertRaises((UserError, ValidationError)), self.cr.savepoint():
            work.with_user(self.manager).write({'owner_id': unauthorized.id})
        new_owner.active = False
        self.sync()
        self.assertFalse(work.owner_id)
        self.assertTrue(work.unassigned)
        self.assertFalse(self.active_activities(work))
        self.assertIn(work, self.env['gt.certificate.renewal'].search([('unassigned', '=', True)]))
        self.assertIn(work, self.env['gt.certificate.renewal'].search([('overdue', '=', True)]))

    def test_activity_completion_does_not_resolve_or_duplicate(self):
        self.requirement()
        self.policy()
        work = self.sync()
        self.active_activities(work).with_user(self.manager).action_feedback(feedback='Requested renewal')
        self.assertTrue(work.activity_acknowledged)
        self.assertEqual(work.state, 'supplier')
        self.assertFalse(self.active_activities(work))
        self.sync()
        self.assertFalse(self.active_activities(work))
        work.with_user(self.manager).action_request_followup()
        self.assertEqual(len(self.active_activities(work)), 1)
        self.assert_blocked(self.order())
        with self.assertRaises(AccessError):
            work.with_user(self.buyer).write({'state': 'covered'})
        with self.assertRaises(AccessError):
            work.with_user(self.buyer).unlink()

    def test_pending_rejected_future_and_new_cycle(self):
        self.requirement()
        self.policy()
        work = self.sync()
        self.submit()
        self.assertEqual(work.state, 'review')
        self.cert.with_user(self.reviewer).action_reject('Wrong scope on renewal')
        self.assertEqual(work.state, 'supplier')
        future = self.verified(valid_from='2026-11-10', valid_until='2027-11-10')
        self.assertEqual(work.state, 'future')
        self.assert_blocked(self.order(), 'not yet effective')
        with patch.object(type(self.a), '_gt_today', lambda company: date(2026, 11, 10)):
            self.sync()
            self.assertEqual(work.state, 'covered')
        with patch.object(type(self.a), '_gt_today', lambda company: date(2027, 11, 1)):
            next_cycle = self.sync()
            self.assertNotEqual(next_cycle.id, work.id)
            self.assertEqual(len(self.active_activities(next_cycle)), 1)
            self.assertEqual(work.state, 'covered')

    def test_selective_recheck_partial_inherited_and_company(self):
        root = self.env['product.category'].create({'name': 'Root packaging'})
        self.category.parent_id = root
        self.requirement(category=root)
        self.requirement(kind=self.other)
        self.policy()
        affected = self.order()
        office_cat = self.env['product.category'].create({'name': 'Unrelated office'})
        office = self.env['product.product'].create({'name': 'Office', 'categ_id': office_cat.id})
        unrelated_category = self.order([(office, 1)])
        another_vendor = self.env['res.partner'].create({'name': 'Another supplier'})
        unrelated_vendor = self.order(partner_id=another_vendor.id)
        self.buyer.company_ids = [Command.set((self.a | self.b).ids)]
        foreign = self.order().with_context(allowed_company_ids=(self.a | self.b).ids)
        foreign.company_id = self.b
        self.verified()
        self.assertEqual(affected.gt_check_result, 'blocked')
        self.assertIn('ISO', affected.gt_check_summary)
        self.assertNotIn('Food Safety', affected.gt_check_summary)
        for untouched in (unrelated_category, unrelated_vendor, foreign):
            self.assertFalse(untouched.gt_checked_at)
        self.verified(type_id=self.other.id)
        self.assertEqual(affected.gt_check_result, 'ready')
        self.assertEqual(affected.state, 'draft')
        self.env['gt.supplier.certificate'].search([('type_id', '=', self.kind.id), ('state', '=', 'verified')]).with_user(self.reviewer).action_revoke('Issuer withdrew scope')
        self.assertEqual(affected.gt_check_result, 'blocked')
        self.assert_blocked(affected, 'revoked')

    def test_company_and_activity_confidentiality(self):
        self.requirement()
        self.requirement(company=self.b)
        self.policy()
        work_a = self.sync()
        bwork = self.env['gt.certificate.renewal'].with_context(allowed_company_ids=self.b.ids)._sync_key(self.b, self.vendor, self.kind)
        with self.assertRaises(AccessError):
            bwork.with_user(self.manager).read(['supplier_id'])
        with self.assertRaises(AccessError):
            bwork.with_user(self.manager).write({'due_date': '2026-12-01'})
        self.assertNotIn(bwork, self.env['gt.certificate.renewal'].with_user(self.manager).search([]))
        for activity in self.active_activities(work_a):
            self.assertNotIn('%PDF-', activity.note or '')
            self.assertNotIn('/web/content', activity.note or '')
            self.assertEqual(activity.res_model, 'gt.certificate.renewal')
        with self.assertRaises(AccessError):
            self.env['gt.certificate.evidence'].with_user(self.manager).search([])
        with self.assertRaises(AccessError):
            work_a.with_user(self.buyer).write({'company_id': self.b.id})

    def test_policy_validation_and_disabled_scheduler_gate(self):
        self.requirement()
        policy = self.policy()
        with self.assertRaises((CheckViolation, ValidationError)), self.cr.savepoint():
            policy.write({'lead_days': -1})
        with self.assertRaises(AccessError):
            policy.with_user(self.buyer).write({'lead_days': 10})
        self.env.ref('gt_supplier_certificate_gate.cron_certificate_renewals').active = False
        self.assert_blocked(self.order())
        for key, model in (('renewal', 'gt.certificate.renewal'), ('policy', 'gt.certificate.policy')):
            for kind in ('list', 'form'):
                view = self.env.ref('gt_supplier_certificate_gate.view_' + key + '_' + kind)
                self.env[model].with_user(self.manager).get_view(view.id, kind)
