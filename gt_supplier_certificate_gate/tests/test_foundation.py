from psycopg2 import IntegrityError
from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'gt_phase1')
class TestFoundation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.a = cls.env.company
        cls.b = cls.env['res.company'].create({'name': 'GT Test B'})
        cls.kind = cls.env['gt.certificate.type'].create({'name': 'Food Safety', 'code': 'FOOD'})
        cls.other = cls.env['gt.certificate.type'].create({'name': 'ISO', 'code': 'ISO'})
        cls.vendor = cls.env['res.partner'].create({'name': 'Shared supplier'})
        cls.category = cls.env['product.category'].create({'name': 'Food'})
        cls.buyer = cls.make_user('buyer', 'group_user')
        cls.manager = cls.make_user('manager', 'group_manager')
        cls.reviewer = cls.make_user('reviewer', 'group_reviewer')
        cls.cert = cls.env['gt.supplier.certificate'].create(cls.values())
        cls.cert_b = cls.env['gt.supplier.certificate'].create(dict(cls.values(), company_id=cls.b.id))

    @classmethod
    def make_user(cls, login, group):
        return cls.env['res.users'].create({'name': login, 'login': 'gt_' + login, 'company_id': cls.a.id, 'company_ids': [Command.set(cls.a.ids)], 'group_ids': [Command.set([cls.env.ref('gt_supplier_certificate_gate.' + group).id])]})

    @classmethod
    def values(cls):
        return {'company_id': cls.a.id, 'supplier_id': cls.vendor.id, 'type_id': cls.kind.id, 'reference': 'FOOD-1', 'valid_from': '2026-01-01', 'valid_until': '2026-12-31'}

    def test_metadata_and_history(self):
        c = self.env['gt.supplier.certificate'].with_user(self.manager).create(self.values())
        self.assertEqual(c.state, 'draft')
        self.assertNotEqual(c.id, self.cert.id)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            c.write({'valid_until': '2025-01-01'})

    def test_forgery(self):
        for user in (self.buyer, self.manager, self.reviewer):
            for vals in ({'state': 'verified'}, {'reviewer_id': user.id}, {'reviewed_at': '2026-01-01 00:00:00'}):
                with self.assertRaises(AccessError), self.cr.savepoint():
                    self.cert.with_user(user).write(vals)
            with self.assertRaises(AccessError), self.cr.savepoint():
                self.env['gt.supplier.certificate'].with_user(user).create(dict(self.values(), state='verified'))

    def test_requirements(self):
        model = self.env['gt.certificate.requirement']
        vals = {'company_id': self.a.id, 'category_id': self.category.id, 'type_id': self.kind.id}
        model.create(vals)
        with self.assertRaises((IntegrityError, ValidationError)), self.cr.savepoint():
            model.create(vals)
        model.create(dict(vals, active=False))
        model.create(dict(vals, type_id=self.other.id))
        with self.assertRaises(AccessError), self.cr.savepoint():
            model.with_user(self.buyer).create(vals)
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.kind.with_user(self.buyer).write({'name': 'Forged'})

    def test_company_isolation(self):
        model = self.env['gt.supplier.certificate'].with_user(self.manager)
        self.assertNotIn(self.cert_b, model.search([]))
        with self.assertRaises(AccessError):
            self.cert_b.with_user(self.manager).read(['reference'])
        with self.assertRaises(AccessError):
            self.cert_b.with_user(self.manager).write({'reference': 'Attack'})
        grouped = model._read_group([], ['company_id'], ['__count'])
        self.assertNotIn(self.b, [r[0] for r in grouped])
        with self.assertRaises(AccessError):
            model.with_context(allowed_company_ids=[self.b.id]).search([])
        self.manager.company_ids = [Command.set((self.a | self.b).ids)]
        self.assertIn(self.cert_b, model.with_context(allowed_company_ids=[self.a.id, self.b.id]).search([]))

    def test_company_relations(self):
        foreign = self.env['res.partner'].create({'name': 'B vendor', 'company_id': self.b.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.cert.write({'supplier_id': foreign.id})
        foreign_cat = self.env['product.category'].create({'name': 'B category', 'company_id': self.b.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['gt.certificate.requirement'].create({'company_id': self.a.id, 'category_id': foreign_cat.id, 'type_id': self.kind.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.cert.write({'owner_id': self.env.ref('base.public_user').id})

    def test_disabled_evidence_boundary(self):
        model = self.env['gt.certificate.evidence']
        for user in (self.buyer, self.manager):
            with self.assertRaises(AccessError):
                model.with_user(user).search([])
        self.assertFalse(model.with_user(self.reviewer).search([]))
        with self.assertRaises(AccessError):
            model.with_user(self.reviewer).create({'certificate_id': self.cert.id, 'company_id': self.a.id})
        self.assertFalse(model._fields['data'].attachment)

    def test_views_acl_and_purchase(self):
        for key in ('type', 'requirement', 'certificate'):
            action = self.env.ref('gt_supplier_certificate_gate.action_' + key)
            self.assertTrue(action.res_model in self.env)
            for kind in ('list', 'form', 'search'):
                view = self.env.ref('gt_supplier_certificate_gate.view_' + key + '_' + kind)
                self.env[action.res_model].with_user(self.manager).get_view(view.id, kind)
        acls = self.env['ir.model.access'].search([('model_id.model', 'like', 'gt.%')])
        self.assertTrue(acls)
        self.assertTrue(all(a.group_id for a in acls))
        po = self.env['purchase.order'].create({'partner_id': self.vendor.id})
        po.button_confirm()
        self.assertEqual(po.state, 'purchase')

