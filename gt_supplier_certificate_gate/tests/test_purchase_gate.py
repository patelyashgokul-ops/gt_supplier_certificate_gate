from datetime import date
from unittest.mock import patch
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from .test_foundation import TestFoundation
from .test_lifecycle import LifecycleFixtures


@tagged('post_install', '-at_install', 'gt_phase3')
class TestPurchaseGate(LifecycleFixtures, TestFoundation):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.buyer.group_ids = [Command.link(cls.env.ref('purchase.group_purchase_user').id)]
        cls.manager.group_ids = [Command.link(cls.env.ref('purchase.group_purchase_manager').id)]
        cls.product = cls.env['product.product'].create({'name': 'Food Grade Pouch', 'categ_id': cls.category.id, 'purchase_ok': True, 'type': 'consu'})
        cls.service = cls.env['product.product'].create({'name': 'Food Service', 'categ_id': cls.category.id, 'purchase_ok': True, 'type': 'service'})

    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(type(self.a), '_gt_today', lambda c: date(2026, 11, 4)))

    def requirement(self, kind=None, category=None, company=None, **extra):
        return self.env['gt.certificate.requirement'].create({'company_id': (company or self.a).id, 'category_id': (category or self.category).id, 'type_id': (kind or self.kind).id, **extra})

    def order(self, products=None, **extra):
        return self.env['purchase.order'].with_user(self.buyer).create({'partner_id': self.vendor.id, 'company_id': self.a.id, 'order_line': [Command.create({'product_id': p.id, 'name': p.name, 'product_qty': q, 'price_unit': 10}) for p, q in (products if products is not None else [(self.product, 1)])], **extra})

    def assert_blocked(self, order, text=None, action='button_confirm'):
        with self.assertRaises(UserError) as caught:
            getattr(order, action)()
        if text:
            self.assertIn(text, str(caught.exception))
        self.assertIn(order.state, ('draft', 'sent', 'to approve'))
        self.assertFalse(order.date_approve)

    def test_missing_and_retry_renewal(self):
        self.requirement()
        po = self.order()
        self.cert.unlink()
        self.assert_blocked(po, 'Missing')
        self.verified(valid_from='2025-01-01', valid_until='2026-10-31')
        self.assert_blocked(po, 'expired on 2026-10-31')
        self.verified(valid_from='2026-11-01', valid_until='2027-10-31')
        po.button_confirm()
        self.assertEqual(po.state, 'purchase')
        self.assertTrue(po.date_approve)

    def test_no_requirement_and_unrelated_expired(self):
        self.verified(valid_from='2024-01-01', valid_until='2025-01-01')
        po = self.order()
        po.button_confirm()
        self.assertEqual(po.state, 'purchase')

    def test_pending_rejected_revoked_future(self):
        self.requirement()
        po = self.order()
        self.submit()
        self.assert_blocked(po, 'pending')
        self.cert.with_user(self.reviewer).action_reject('Scope is incorrect')
        self.assert_blocked(po, 'rejected')
        current = self.verified()
        current.with_user(self.reviewer).action_revoke('Issuer revoked certificate')
        self.assert_blocked(po, 'revoked')
        self.verified(valid_from='2026-11-10', valid_until='2027-11-10')
        self.assert_blocked(po, 'not yet effective')

    def test_inheritance_duplicates_and_rule_changes(self):
        root = self.env['product.category'].create({'name': 'Packaging'})
        middle = self.env['product.category'].create({'name': 'Food Packaging', 'parent_id': root.id})
        self.category.parent_id = middle
        r = self.requirement(category=root)
        self.requirement(category=middle)
        self.requirement()
        po = self.order()
        self.assertEqual(len(po._gt_evaluate()['failures']), 1)
        self.verified()
        self.assertEqual(po._gt_evaluate()['status'], 'ready')
        other = self.requirement(kind=self.other)
        self.assertEqual(len(po._gt_evaluate()['failures']), 1)
        other.active = False
        self.assertEqual(po._gt_evaluate()['status'], 'ready')
        other.active = True
        self.product.categ_id = self.env['product.category'].create({'name': 'Office'})
        self.assertEqual(po._gt_evaluate()['status'], 'not_required')
        self.product.categ_id = self.category
        self.assertEqual(po._gt_evaluate()['status'], 'blocked')

    def test_mixed_lines_services_and_zero(self):
        self.requirement()
        office = self.env['product.product'].create({'name': 'Office Paper', 'type': 'consu'})
        po = self.order([(self.product, 1), (office, 1), (self.service, 1), (self.product, 0)])
        po.order_line = [Command.create({'display_type': 'line_section', 'name': 'Section', 'product_qty': 0})]
        result = po._gt_evaluate()
        self.assertEqual(len(result['failures']), 2)
        text = po._gt_format(result)
        self.assertIn('Food Grade Pouch', text)
        self.assertIn('Food Service', text)
        self.assertNotIn('Office Paper', text)
        self.assert_blocked(po)
        self.assertFalse(po.invoice_ids)

    def test_date_context_and_boundaries(self):
        self.requirement()
        c = self.verified(valid_from='2026-11-04', valid_until='2026-11-04')
        po = self.order()
        self.assertEqual(po._gt_evaluate()['status'], 'ready')
        with patch.object(type(self.a), '_gt_today', lambda company: date(2026, 11, 5)):
            self.assert_blocked(po.with_context(date='2026-11-04', tz='Pacific/Honolulu', skip_certificate_check=True), 'expired')
        with patch.object(type(self.a), '_gt_today', lambda company: date(2026, 11, 3)):
            self.assert_blocked(po, 'not yet effective')

    def test_pending_rejected_overlap_do_not_invalidate_old(self):
        self.requirement()
        self.verified()
        self.submit()
        po = self.order()
        self.assertEqual(po._gt_evaluate()['status'], 'ready')
        self.cert.with_user(self.reviewer).action_reject('Incorrect renewal scope')
        self.assertEqual(po._gt_evaluate()['status'], 'ready')
        self.verified(valid_from='2026-11-01', valid_until='2027-11-01')
        po.button_confirm()
        self.assertEqual(po.state, 'purchase')

    def test_final_approval_rechecks_and_native_threshold(self):
        self.a.po_double_validation = 'two_step'
        self.a.po_double_validation_amount = 1
        self.requirement()
        self.verified(valid_until='2026-11-04')
        po = self.order()
        po.button_confirm()
        self.assertEqual(po.state, 'to approve')
        with patch.object(type(self.a), '_gt_today', lambda company: date(2026, 11, 5)):
            self.assert_blocked(po.with_user(self.manager), 'expired', action='button_approve')
            self.verified(valid_from='2026-11-05', valid_until='2027-11-05')
            po.with_user(self.manager).button_approve(force=True)
        self.assertEqual(po.state, 'purchase')

    def test_state_write_create_bulk_and_combined_attack(self):
        self.requirement()
        po, other = self.order(), self.order()
        for state in ('to approve', 'purchase'):
            with self.assertRaises(UserError):
                po.with_context(skip_certificate_check=True).write({'state': state})
        with self.assertRaises(UserError):
            (po | other).button_confirm()
        self.assertEqual((po | other).mapped('state'), ['draft', 'draft'])
        with self.assertRaises(UserError):
            self.order(state='purchase')
        with self.assertRaises(UserError):
            self.order().write({'state': 'purchase', 'order_line': [Command.create({'product_id': self.product.id, 'product_qty': 1, 'name': 'Attack'})]})
        po.write({'note': 'Harmless draft edit'})
        po.button_cancel()
        po.button_draft()
        self.assertEqual(po.state, 'draft')

    def test_exact_supplier_and_company_matching(self):
        self.requirement()
        self.verified()
        child = self.env['res.partner'].create({'name': 'Supplier contact', 'parent_id': self.vendor.id})
        po = self.order(partner_id=child.id)
        self.assert_blocked(po, 'Missing')
        self.requirement(company=self.b)
        foreign_requirement = self.requirement(kind=self.other, company=self.b)
        po.partner_id = self.vendor
        self.assertEqual(po._gt_evaluate()['status'], 'ready')
        self.buyer.company_ids = [Command.set((self.a | self.b).ids)]
        bpo = self.order().with_context(allowed_company_ids=(self.a | self.b).ids)
        bpo.company_id = self.b
        self.assert_blocked(bpo, 'Missing')

    def test_downpayment_flag_cannot_hide_product(self):
        self.requirement()
        po = self.order()
        po.order_line.is_downpayment = True
        self.assert_blocked(po)

    def test_manual_check_is_non_authoritative(self):
        self.requirement()
        po = self.order()
        po.action_gt_check_certificates()
        self.assertEqual(po.gt_check_result, 'blocked')
        self.verified()
        po.action_gt_check_certificates()
        self.assertEqual(po.gt_check_result, 'ready')
        self.assertEqual(po.state, 'draft')
        self.assertTrue(po.gt_checked_at)
        with self.assertRaises(AccessError):
            po.write({'gt_check_result': 'ready'})
        self.env['gt.supplier.certificate'].search([('state', '=', 'verified')]).with_user(self.reviewer).action_revoke('Incorrect issuer scope')
        self.assert_blocked(po, 'revoked')
        self.assertNotIn('%PDF-', po.gt_check_summary)


from .test_lifecycle import TestDownloads


@tagged('post_install', '-at_install', 'gt_phase3')
class TestPurchaseRPC(TestDownloads):
    def test_rpc_actions_cannot_bypass(self):
        self.buyer.group_ids = [Command.link(self.env.ref('purchase.group_purchase_user').id)]
        category = self.env['product.category'].create({'name': 'RPC required'})
        product = self.env['product.product'].create({'name': 'RPC product', 'categ_id': category.id})
        self.env['gt.certificate.requirement'].create({'company_id': self.a.id, 'category_id': category.id, 'type_id': self.kind.id})
        po = self.env['purchase.order'].create({'partner_id': self.vendor.id, 'order_line': [Command.create({'product_id': product.id, 'name': 'RPC product', 'product_qty': 1})]})
        self.authenticate(self.buyer.login, 'gt-test-password')
        for method, args in [('button_confirm', [po.ids]), ('button_approve', [po.ids]), ('write', [po.ids, {'state': 'purchase'}])]:
            response = self.url_open('/web/dataset/call_kw', json={'jsonrpc': '2.0', 'id': 1, 'method': 'call', 'params': {'model': 'purchase.order', 'method': method, 'args': args, 'kwargs': {'context': {'skip_certificate_check': True}}}})
            self.assertIn('error', response.json())
            self.assertNotIn('%PDF-', response.text)
        po.invalidate_recordset()
        self.assertEqual(po.state, 'draft')
