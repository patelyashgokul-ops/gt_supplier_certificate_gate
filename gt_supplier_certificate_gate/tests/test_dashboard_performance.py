import json
import logging
import time
from datetime import timedelta
from pathlib import Path
from odoo import Command
from odoo.tests import tagged
from .test_dashboard import TestDashboard
from .test_lifecycle import pdf_content

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install', 'gt_phase5_performance', '-gt_phase5_backend', '-standard')
class TestDashboardPerformance(TestDashboard):
    def test_representative_sme_dataset_and_batch_queries(self):
        self.requirement()
        self.env['gt.certificate.policy'].create({'company_id': self.a.id, 'owner_id': self.buyer.id})
        suppliers = self.env['res.partner'].create([{'name': 'GT Performance Supplier %03d' % i} for i in range(100)])
        today = self.a._gt_today()
        certificates = self.env['gt.supplier.certificate'].create([dict(self.values(), supplier_id=supplier.id, reference='PERF-%s-%s' % (supplier.id, i), valid_from=str(today - timedelta(days=30)), valid_until=str(today + timedelta(days=7 if i == 0 else 365))) for supplier in suppliers for i in range(10)])
        for cert in certificates[::10][:50]:
            self.env['gt.certificate.upload'].with_user(self.manager).create({'certificate_id': cert.id, 'data': pdf_content()})
            cert.with_user(self.reviewer).action_approve()
        orders = self.env['purchase.order'].create([{'company_id': self.a.id, 'partner_id': suppliers[i % 100].id, 'order_line': [Command.create({'product_id': self.product.id, 'product_qty': 1, 'price_unit': 10, 'name': 'Performance product'})]} for i in range(500)])
        foreign_certificates = self.env['gt.supplier.certificate'].with_company(self.b).create([dict(self.values(), company_id=self.b.id, supplier_id=suppliers[i].id, reference='PRIVATE-PERF-%s' % i) for i in range(10)])
        self.requirement(company=self.b)
        foreign_orders = self.env['purchase.order'].with_company(self.b).create([{'company_id': self.b.id, 'partner_id': suppliers[i].id, 'order_line': [Command.create({'product_id': self.product.id, 'name': 'Private B demand', 'product_qty': 1})]} for i in range(5)])
        work = self.env['gt.certificate.renewal'].search([('company_id', '=', self.a.id), ('supplier_id', 'in', suppliers.ids)])
        work[:25].with_user(self.manager).write({'due_date': str(today - timedelta(days=1))})
        self.env.flush_all()
        self.assertEqual(self.env['mail.activity'].search_count([('gt_renewal_id', 'in', work.ids), ('active', '=', True)]), 50)
        self.assertEqual(len(certificates), 1000)
        self.assertEqual(len(orders), 500)
        def measure(callback):
            self.env.invalidate_all()
            before = self.cr.sql_log_count
            start = time.perf_counter()
            value = callback()
            return value, {'queries': self.cr.sql_log_count - before, 'seconds': round(time.perf_counter() - start, 4)}
        values, naive = measure(lambda: [o.with_user(self.buyer)._gt_evaluate() for o in orders])
        data, optimized = measure(lambda: self.dashboard())
        self.assertEqual(data['kpis']['blocked'], 250)
        self.assertEqual(data['kpis']['missing'], 50)
        self.assertEqual(data['kpis']['expiring'], 50)
        self.assertEqual(data['kpis']['pending'], 0)
        self.assertEqual(data['kpis']['overdue'], 25)
        self.assertLess(optimized['queries'], naive['queries'])
        self.assertLess(optimized['queries'], 200)
        self.assertLess(optimized['seconds'], 15)
        self.assertLessEqual(len(data['blocked']), 8)
        evidence = {'suppliers': 100, 'certificates': 1010, 'purchase_orders': 505, 'companies': 2, 'authorized_company_certificates': 1000, 'authorized_company_purchase_orders': 500, 'active_renewal_activities': 50, 'overdue_renewal_activities': 25, 'verified_current_certificates': 50, 'naive_per_order_gate': naive, 'combined_batched_dashboard': optimized, 'expected_and_actual_kpis': data['kpis'], 'binary_fields_read': 'none; separate evidence model is not accessed by dashboard'}
        Path('.development/phase5-performance.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        _logger.info('GT dashboard performance: %s', json.dumps(evidence))
