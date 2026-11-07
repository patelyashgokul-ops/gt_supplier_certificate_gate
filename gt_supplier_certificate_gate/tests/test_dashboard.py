import json
from datetime import date
from unittest.mock import patch
from psycopg2 import IntegrityError
from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from .test_purchase_gate import TestPurchaseGate


@tagged('post_install', '-at_install', 'gt_phase5_backend', '-gt_phase1', '-gt_phase3')
class TestDashboard(TestPurchaseGate):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cert.unlink()
        cls.cert_b.unlink()

    def dashboard(self, filters=None, user=None):
        return self.env['gt.certificate.dashboard'].with_user(user or self.buyer).get_data(filters or {})

    def drill(self, metric, filters=None, user=None):
        return self.env['gt.certificate.dashboard'].with_user(user or self.buyer).open_kpi(metric, filters or {})

    def action_records(self, action, user=None):
        return self.env[action['res_model']].with_user(user or self.buyer).with_context(action.get('context', {})).search(action['domain'])

    def test_distinct_blocked_demand_and_live_partial_resolution(self):
        self.requirement()
        self.requirement(kind=self.other)
        one = self.order([(self.product, 1)] * 3)
        two = self.order()
        data = self.dashboard()
        self.assertEqual(data['kpis'], {'blocked': 2, 'expiring': 0, 'missing': 2, 'pending': 0, 'overdue': 0})
        self.assertEqual(set(self.action_records(self.drill('blocked')).ids), set((one | two).ids))
        self.assertEqual(len(self.action_records(self.drill('missing'))), 2)
        self.assertEqual(len(data['blocked']), 2)
        self.verified()
        self.assertEqual(self.dashboard()['kpis']['blocked'], 2)
        self.assertEqual(self.dashboard()['kpis']['missing'], 1)
        self.assertIn('ISO', self.dashboard()['blocked'][0]['details'])
        self.assertNotIn('Food Safety:', self.dashboard()['blocked'][0]['details'])
        self.verified(type_id=self.other.id)
        self.assertEqual(self.dashboard()['kpis']['blocked'], 0)
        one.button_confirm()
        two.button_cancel()
        self.assertEqual(self.dashboard()['kpis']['blocked'], 0)
        self.assertIn('not historical', self.dashboard()['contract'].lower())

    def test_expiry_buckets_history_overlaps_and_inclusive_windows(self):
        self.requirement()
        self.order()
        self.verified(valid_from='2025-01-01', valid_until='2026-11-03')
        data = self.dashboard()
        self.assertEqual(data['kpis']['missing'], 1)
        self.assertEqual([b['count'] for b in data['chart']], [0, 1, 0, 0, 0])
        self.verified(valid_from='2026-11-04', valid_until='2026-11-11')
        self.verified(valid_from='2026-11-01', valid_until='2026-11-08')
        data = self.dashboard()
        self.assertEqual(data['kpis']['expiring'], 1)
        self.assertEqual(data['kpis']['blocked'], 0)
        self.assertEqual([b['count'] for b in data['chart']], [0, 0, 1, 0, 0])
        self.assertEqual(len(self.action_records(self.drill('bucket_seven'))), 1)
        self.assertEqual(len(self.action_records(self.drill('expiring'))), 1)
        self.verified(valid_from='2026-11-12', valid_until='2027-11-12')
        self.assertEqual(self.dashboard()['kpis']['expiring'], 0)
        self.assertEqual(sum(b['count'] for b in self.dashboard()['chart']), 0)
        self.assertEqual(self.dashboard({'window': '30'})['kpis']['missing'], 0)

    def test_future_gap_and_boundary_buckets(self):
        self.requirement()
        po = self.order()
        self.verified(valid_from='2026-11-10', valid_until='2027-11-10')
        data = self.dashboard()
        self.assertEqual(data['kpis']['blocked'], 1)
        self.assertEqual([b['count'] for b in data['chart']], [1, 0, 0, 0, 0])
        self.assertEqual(self.action_records(self.drill('missing')).status, 'future')
        self.assertEqual(self.dashboard({'window': '7'})['kpis']['blocked'], 0)
        with patch.object(type(self.a), '_gt_today', lambda c: date(2026, 11, 10)):
            self.assertEqual(self.dashboard()['kpis']['blocked'], 0)
        # Separate exact day boundaries, without overwriting submitted history.
        for days, expected in ((0, 'bucket_seven'), (7, 'bucket_seven'), (8, 'bucket_thirty'), (30, 'bucket_thirty'), (31, 'bucket_sixty'), (60, 'bucket_sixty'), (61, None)):
            vendor = self.env['res.partner'].create({'name': 'Boundary %s' % days})
            from datetime import timedelta
            self.verified(supplier_id=vendor.id, valid_until=str(date(2026, 11, 4) + timedelta(days=days)))
            result = self.dashboard({'supplier_id': vendor.id})
            self.assertEqual([b['key'] for b in result['chart'] if b['count']], [expected] if expected else [])
            self.assertEqual(result['kpis']['expiring'], int(days <= 30))

    def test_pending_counts_documents_not_requirements_and_reviewer_navigation(self):
        self.requirement()
        for index in range(3):
            c = self.env['gt.supplier.certificate'].create(dict(self.values(), reference='Pending %s' % index))
            self.submit(c)
        draft = self.env['gt.supplier.certificate'].create(self.values())
        self.assertEqual(self.dashboard()['kpis']['pending'], 3)
        pending = self.action_records(self.drill('pending'))
        self.assertEqual(len(pending), 3)
        self.assertNotIn(draft, pending)
        one = pending[0]
        one.with_user(self.reviewer).action_reject('Scope is inconsistent')
        self.assertEqual(self.dashboard()['kpis']['pending'], 2)
        self.assertEqual(self.dashboard({'status': 'pending'})['kpis']['pending'], 2)
        payload = self.dashboard()
        encoded = json.dumps(payload)
        for forbidden in ('%PDF-', '/web/content', 'access_token', 'sha256', 'evidence_id'):
            self.assertNotIn(forbidden, encoded)
        self.assertFalse(payload['can_review'])
        self.assertTrue(self.dashboard(user=self.reviewer)['can_review'])
        with self.assertRaises(AccessError):
            pending[1].with_user(self.buyer).action_evidence()
        with self.assertRaises(AccessError):
            pending[1].with_user(self.manager).action_approve()

    def test_overdue_activity_unit_and_unassigned_visibility(self):
        self.requirement()
        self.env['gt.certificate.policy'].create({'company_id': self.a.id, 'owner_id': self.buyer.id})
        self.order()
        work = self.env['gt.certificate.renewal']._sync_key(self.a, self.vendor, self.kind)
        work.with_user(self.manager).write({'due_date': '2026-11-03'})
        self.verified(valid_until='2026-11-11')
        data = self.dashboard()
        self.assertEqual(data['kpis'], {'blocked': 0, 'expiring': 1, 'missing': 0, 'pending': 0, 'overdue': 1})
        activities = self.action_records(self.drill('overdue'))
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities.gt_renewal_id, work)
        activities.with_user(self.buyer).action_feedback('Followed up')
        self.assertEqual(self.dashboard()['kpis']['overdue'], 0)
        self.assertEqual(work.state, 'supplier')
        work.with_user(self.manager).write({'owner_id': False})
        result = self.dashboard({'owner_id': 'unassigned'}, user=self.manager)
        self.assertEqual(result['requirements'][0]['owner'], 'Unassigned')
        with self.assertRaises(AccessError):
            self.dashboard({'owner_id': 'unassigned'})

    def test_company_scope_owner_attacks_and_no_purchase_permission(self):
        self.requirement()
        for index in range(2):
            self.order()
        self.requirement(company=self.b)
        for index in range(3):
            self.env['purchase.order'].with_company(self.b).create({'company_id': self.b.id, 'partner_id': self.vendor.id, 'order_line': [Command.create({'name': 'B product', 'product_id': self.product.id, 'product_qty': 1})]})
        self.assertEqual(self.dashboard()['kpis']['blocked'], 2)
        hostile = self.env['gt.certificate.dashboard'].with_user(self.buyer).with_context(allowed_company_ids=self.b.ids, default_state='verified', skip_certificate_check=True).get_data()
        self.assertEqual(hostile['kpis']['blocked'], 2)
        with self.assertRaises(AccessError):
            self.dashboard({'company_id': self.b.id})
        b_owner = self.env['res.users'].create({'name': 'B private owner', 'login': 'gt_private_b', 'company_id': self.b.id, 'company_ids': [Command.set(self.b.ids)], 'group_ids': [Command.set([self.env.ref('gt_supplier_certificate_gate.group_user').id])]})
        with self.assertRaises(AccessError):
            self.dashboard({'owner_id': b_owner.id})
        self.assertNotIn('B private owner', json.dumps(self.dashboard()))
        self.buyer.company_ids = [Command.set((self.a | self.b).ids)]
        self.assertEqual(self.dashboard()['kpis']['blocked'], 5)
        self.assertEqual(self.dashboard({'company_id': self.b.id})['kpis']['blocked'], 3)
        self.assertEqual(self.dashboard({'company_id': self.a.id})['kpis']['blocked'], 2)
        with self.assertRaises(AccessError):
            self.dashboard({'company_id': self.a.id, 'owner_id': b_owner.id})
        manager = self.dashboard(user=self.reviewer)
        self.assertIsNone(manager['kpis']['blocked'])
        with self.assertRaises(AccessError):
            self.drill('blocked', user=self.reviewer)

    def test_composable_filters_parent_categories_and_exact_actions(self):
        parent = self.env['product.category'].create({'name': 'Dashboard parent'})
        self.category.parent_id = parent
        self.requirement(category=parent)
        self.requirement()
        self.env['gt.certificate.policy'].create({'company_id': self.a.id, 'owner_id': self.buyer.id})
        po = self.order()
        self.assertEqual(self.dashboard()['kpis']['missing'], 1)
        filters = {'company_id': self.a.id, 'supplier_id': self.vendor.id, 'type_id': self.kind.id, 'category_id': parent.id, 'owner_id': self.buyer.id}
        self.assertEqual(self.dashboard(filters)['kpis']['blocked'], 1)
        self.assertEqual(self.action_records(self.drill('blocked', filters)), po)
        self.assertEqual(len(self.action_records(self.drill('bucket_missing', filters))), 1)
        action = self.env['gt.certificate.dashboard'].with_user(self.buyer).open_record('blocked', po.id, filters)
        self.assertEqual(action['res_id'], po.id)
        other_vendor = self.env['res.partner'].create({'name': 'No demand'})
        empty = self.dashboard({'supplier_id': other_vendor.id})
        self.assertEqual(empty['kpis'], {'blocked': 0, 'expiring': 0, 'missing': 0, 'pending': 0, 'overdue': 0})
        self.assertEqual(self.dashboard()['kpis']['blocked'], 1)
        self.verified()
        with self.assertRaises(AccessError):
            self.env['gt.certificate.dashboard'].with_user(self.buyer).open_record('blocked', po.id)

    def test_report_is_private_readonly_and_no_arbitrary_rpc_filters(self):
        self.requirement()
        self.order()
        rows = self.action_records(self.drill('missing'))
        self.assertEqual(len(rows), 1)
        with self.assertRaises(AccessError):
            rows.with_user(self.manager).read(['supplier_id'])
        with self.assertRaises(AccessError):
            rows.write({'status': 'effective'})
        with self.assertRaises(AccessError):
            self.env['gt.certificate.coverage.report'].with_user(self.buyer).create({'company_id': self.a.id})
        for f in ({'domain': []}, {'company_id': True}, {'company_id': '1'}, {'status': '__class__'}, {'window': '-1'}, {'owner_id': {}}, {'supplier_id': [self.vendor.id]}):
            with self.assertRaises(ValidationError):
                self.dashboard(f)
        stranger = self.make_user('no_certificate_role', 'group_user')
        stranger.group_ids = [Command.set([self.env.ref('base.group_user').id])]
        with self.assertRaises(AccessError):
            self.dashboard(user=stranger)
        with self.assertRaises(ValidationError):
            self.drill('evidence')

    def test_delayed_scheduler_and_actual_company_date_not_cached_snapshot(self):
        self.requirement()
        c = self.verified(valid_until='2026-11-04')
        po = self.order()
        po.action_gt_check_certificates()
        self.assertEqual(po.gt_check_result, 'ready')
        self.env.ref('gt_supplier_certificate_gate.cron_certificate_renewals').active = False
        with patch.object(type(self.a), '_gt_today', lambda company: date(2026, 11, 5)):
            self.assertEqual(self.dashboard()['kpis']['blocked'], 1)
            self.assertEqual(self.dashboard()['kpis']['missing'], 1)
            self.assertEqual(po.gt_check_result, 'ready')
            self.assertEqual(po.gt_current_status, 'blocked')
        self.assertEqual(self.dashboard({'status': 'effective'})['kpis']['blocked'], 0)

    def test_bounded_scope_reports_error_and_max_date_coverage(self):
        self.requirement()
        self.verified(valid_until='9999-12-31')
        self.order()
        self.assertEqual(self.dashboard()['kpis']['blocked'], 0)
        self.env['gt.supplier.certificate'].create(self.values())
        with patch('odoo.addons.gt_supplier_certificate_gate.models.dashboard.LIMIT', 1):
            with self.assertRaises(UserError):
                self.dashboard()

    def test_accounting_viewer_keeps_native_purchase_metadata_access(self):
        po = self.order()
        viewer = self.make_user('dashboard_account_readonly', 'group_user')
        viewer.group_ids = [Command.set([self.env.ref('account.group_account_readonly').id])]
        self.assertEqual(po.with_user(viewer).read(['name'])[0]['name'], po.name)
        view = self.env.ref('purchase.purchase_order_form')
        arch = self.env['purchase.order'].with_user(viewer).get_view(view.id, 'form')['arch']
        self.assertNotIn('name="gt_current_details"', arch)
        with self.assertRaises(AccessError):
            self.dashboard(user=viewer)

    def test_native_blocked_list_refreshes_existing_action(self):
        self.requirement()
        po = self.order()
        action = self.drill('blocked', {'supplier_id': self.vendor.id})
        self.assertEqual(self.action_records(action), po)
        certificate = self.verified()
        self.assertFalse(self.action_records(action))
        certificate.with_user(self.reviewer).action_revoke('Issuer withdrew scope')
        self.assertEqual(self.action_records(action), po)

    def test_owner_role_loss_is_unassigned_without_waiting_for_cron(self):
        self.requirement()
        owner = self.make_user('dashboard_owner_removed', 'group_user')
        self.env['gt.certificate.policy'].create({'company_id': self.a.id, 'owner_id': owner.id})
        self.order()
        work = self.env['gt.certificate.renewal']._sync_key(self.a, self.vendor, self.kind)
        self.assertEqual(self.dashboard({'owner_id': owner.id})['kpis']['missing'], 1)
        owner.group_ids = [Command.set([self.env.ref('base.group_user').id])]
        with self.assertRaises(AccessError):
            self.dashboard({'owner_id': owner.id})
        result = self.dashboard({'owner_id': 'unassigned'}, user=self.manager)
        self.assertEqual(result['requirements'][0]['owner'], 'Unassigned')
        self.assertNotIn(owner.id, [x['id'] for x in result['options']['owners']])

    def test_nonowner_cannot_hide_overdue_work_via_native_activity_rpc_paths(self):
        self.requirement()
        self.env['gt.certificate.policy'].create({'company_id': self.a.id, 'owner_id': self.manager.id})
        self.order()
        work = self.env['gt.certificate.renewal']._sync_key(self.a, self.vendor, self.kind)
        work.with_user(self.manager).write({'due_date': '2026-11-03'})
        activity = self.env['mail.activity'].search([('gt_renewal_id', '=', work.id), ('active', '=', True)])
        with self.assertRaises(AccessError), self.cr.savepoint():
            activity.with_user(self.buyer).write({'date_deadline': '2027-01-01'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            activity.with_user(self.buyer).action_feedback('Unauthorized completion')
        with self.assertRaises(AccessError), self.cr.savepoint():
            activity.with_user(self.buyer).unlink()
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['mail.activity'].with_user(self.buyer).create({'gt_renewal_id': work.id, 'res_model_id': self.env['ir.model']._get_id(work._name), 'res_id': work.id, 'user_id': self.manager.id, 'activity_type_id': activity.activity_type_id.id, 'date_deadline': '2027-01-01'})
        self.assertEqual(self.dashboard()['kpis']['overdue'], 1)
        self.assertEqual(activity.date_deadline, date(2026, 11, 3))
        owner = self.make_user('dashboard_activity_owner', 'group_user')
        work.with_user(self.manager).write({'owner_id': owner.id})
        activity.with_user(owner).write({'date_deadline': '2026-11-02'})
        activity.with_user(owner).action_feedback('Requested new certificate')
        self.assertEqual(self.dashboard()['kpis']['overdue'], 0)
        self.assertEqual(self.dashboard()['kpis']['blocked'], 1)
        self.assertEqual(work.state, 'supplier')
