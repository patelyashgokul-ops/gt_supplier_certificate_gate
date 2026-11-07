from datetime import date
from unittest.mock import patch
from odoo.exceptions import UserError
from odoo.tests import tagged
from .test_purchase_gate import TestPurchaseGate


@tagged('post_install', '-at_install', '-standard', 'gt_phase5_stock')
class TestStockCompatibility(TestPurchaseGate):
    def test_certificate_gate_prevents_receipts_until_compliant(self):
        self.assertIn('picking_ids', self.env['purchase.order']._fields, 'Install native purchase_stock on the disposable test database for this explicit integration tag.')
        self.requirement()
        po = self.order()
        self.assert_blocked(po)
        self.assertFalse(po.picking_ids)
        self.verified()
        po.button_confirm()
        self.assertEqual(po.state, 'purchase')
        self.assertEqual(len(po.picking_ids), 1)
        self.assertFalse(po.invoice_ids)
        self.assertEqual(po.picking_ids.partner_id, self.vendor)

    def test_delayed_final_approval_creates_no_receipt_when_expired(self):
        self.a.po_double_validation = 'two_step'
        self.a.po_double_validation_amount = 1
        self.requirement()
        self.verified(valid_until='2026-11-04')
        po = self.order()
        po.button_confirm()
        self.assertEqual(po.state, 'to approve')
        self.assertFalse(po.picking_ids)
        with patch.object(type(self.a), '_gt_today', lambda c: date(2026, 11, 5)):
            with self.assertRaises(UserError), self.cr.savepoint():
                po.with_user(self.manager).button_approve(force=True)
            self.assertEqual(po.state, 'to approve')
            self.assertFalse(po.picking_ids)
            self.verified(valid_from='2026-11-05', valid_until='2027-11-05')
            self.assertFalse(po.picking_ids)
            po.with_user(self.manager).button_approve()
        self.assertEqual(po.state, 'purchase')
        self.assertEqual(len(po.picking_ids), 1)
