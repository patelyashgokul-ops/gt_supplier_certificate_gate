import base64
import io
from datetime import date
from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import HttpCase, tagged
from odoo.tools.pdf import PdfWriter
from .test_foundation import TestFoundation


def pdf_content():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = io.BytesIO()
    writer.write(output)
    return base64.b64encode(output.getvalue()).decode()


class LifecycleFixtures:
    def submit(self, certificate=None, user=None):
        c = certificate or self.cert
        wizard = self.env['gt.certificate.upload'].with_user(user or self.manager).with_context(allowed_company_ids=c.company_id.ids).create({'certificate_id': c.id, 'data': pdf_content()})
        self.assertFalse(wizard.data)
        return c

    def verified(self, **changes):
        c = self.env['gt.supplier.certificate'].with_user(self.manager).create(dict(self.values(), **changes))
        self.submit(c)
        c.with_user(self.reviewer).action_approve()
        return c


@tagged('post_install', '-at_install', 'gt_phase2')
class TestLifecycle(LifecycleFixtures, TestFoundation):
    # Inherited foundation assertions are deliberately retained as regressions.
    def test_context_forgery_and_copy(self):
        c = self.env['gt.supplier.certificate'].with_user(self.manager).with_context(default_state='verified', default_reviewer_id=self.manager.id, default_evidence_id=123).create(self.values())
        self.assertEqual(c.state, 'draft')
        self.assertFalse(c.reviewer_id)
        self.assertFalse(c.evidence_id)
        c = self.verified()
        copied = c.copy()
        self.assertEqual(copied.state, 'draft')
        self.assertFalse(copied.evidence_id)

    def test_submission_validation(self):
        self.assertEqual(self.cert.state, 'draft')
        with self.assertRaises(UserError):
            self.cert.with_user(self.reviewer).action_approve()
        for data in ('', base64.b64encode(b'not a PDF').decode(), base64.b64encode(b'%PDF-1.4\n%%EOF').decode()):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.env['gt.certificate.upload'].with_user(self.manager).create({'certificate_id': self.cert.id, 'data': data})
        self.submit()
        self.assertEqual(self.cert.state, 'pending')
        self.assertEqual(self.cert.submitter_id, self.manager)
        self.assertTrue(self.cert.submitted_at)
        with self.assertRaises(UserError):
            self.submit()
        with self.assertRaises(AccessError):
            self.submit(self.cert_b)

    def test_review_and_immutability(self):
        self.submit(user=self.reviewer)
        with self.assertRaises(AccessError):
            self.cert.with_user(self.reviewer).action_approve()
        with self.assertRaises(AccessError):
            self.cert.with_user(self.buyer).action_approve()
        second = self.make_user('secondreviewer', 'group_reviewer')
        self.cert.with_user(second).action_approve()
        self.assertEqual(self.cert.reviewer_id, second)
        self.assertTrue(self.cert.reviewed_at)
        for vals in ({'valid_until': '2027-12-31'}, {'supplier_id': self.vendor.id}, {'company_id': self.b.id}, {'type_id': self.other.id}, {'reference': 'replacement'}):
            with self.assertRaises(UserError), self.cr.savepoint():
                self.cert.with_user(self.manager).write(vals)
        with self.assertRaises(UserError):
            self.cert.with_user(self.manager).unlink()
        evidence = self.cert.evidence_id.with_user(second)
        self.assertTrue(evidence.data.content.startswith(b'%PDF-'))
        for vals in ({'data': pdf_content()}, {'company_id': self.b.id}, {'certificate_id': self.cert_b.id}):
            with self.assertRaises(AccessError):
                evidence.write(vals)
        with self.assertRaises(AccessError):
            evidence.unlink()
        with self.assertRaises(UserError):
            self.cert.with_user(second).action_approve()

    def test_rejection_revocation_and_renewals(self):
        old = self.verified(valid_from='2024-01-01', valid_until='2025-12-31')
        current = self.verified()
        future = self.verified(valid_from='2027-01-01', valid_until='2027-12-31')
        self.submit()
        with self.assertRaises(ValidationError):
            self.cert.with_user(self.reviewer).action_reject(' ')
        self.cert.with_user(self.reviewer).action_reject('Unreadable certificate scope')
        self.assertEqual(self.cert.state, 'rejected')
        self.assertTrue(self.cert.evidence_id)
        self.assertTrue(current.is_effective('2026-01-01', self.a.id, self.vendor.id, self.kind.id))
        self.assertTrue(current.is_effective('2026-12-31', self.a.id, self.vendor.id, self.kind.id))
        self.assertFalse(old.is_effective('2026-11-04', self.a.id, self.vendor.id, self.kind.id))
        self.assertFalse(future.is_effective('2026-11-04', self.a.id, self.vendor.id, self.kind.id))
        self.assertFalse(current.is_effective('2026-11-04', self.b.id, self.vendor.id, self.kind.id))
        self.assertFalse(self.cert.is_effective('2026-11-04', self.a.id, self.vendor.id, self.kind.id))
        reviewer, timestamp, evidence = current.reviewer_id, current.reviewed_at, current.evidence_id
        with self.assertRaises(AccessError):
            current.with_user(self.buyer).action_revoke('Invalidated by issuer')
        with self.assertRaises(ValidationError):
            current.with_user(self.reviewer).action_revoke('')
        current.with_user(self.reviewer).action_revoke('Invalidated by issuer')
        self.assertEqual(current.reviewer_id, reviewer)
        self.assertEqual(current.reviewed_at, timestamp)
        self.assertEqual(current.evidence_id, evidence)
        self.assertEqual(current.revoked_by_id, self.reviewer)
        self.assertFalse(current.is_effective('2026-11-04', self.a.id, self.vendor.id, self.kind.id))
        with self.assertRaises(UserError):
            current.with_user(self.reviewer).action_approve()

    def test_binary_isolation_and_company(self):
        c = self.verified()
        foreign = self.cert_b
        self.manager.company_ids = [Command.set((self.a | self.b).ids)]
        self.submit(foreign, self.manager.with_context(allowed_company_ids=[self.b.id]))
        evidence = c.evidence_id
        for user in (self.buyer, self.manager):
            user.group_ids = [Command.link(self.env.ref('base.group_allow_export').id)]
            with self.assertRaises(AccessError):
                evidence.with_user(user).read(['data'])
            with self.assertRaises(AccessError):
                evidence.with_user(user).export_data(['data'])
            with self.assertRaises(AccessError):
                self.env['gt.certificate.evidence'].with_user(user).search([])
        with self.assertRaises(AccessError):
            foreign.evidence_id.with_user(self.reviewer).read(['data'])
        with self.assertRaises(AccessError):
            foreign.with_user(self.reviewer).action_approve()
        with self.assertRaises(AccessError):
            foreign.evidence_id.with_user(self.reviewer).with_context(allowed_company_ids=[self.b.id]).read(['data'])
        self.assertFalse(self.env['ir.attachment'].search([('res_model', '=', 'gt.certificate.evidence'), ('res_id', '=', evidence.id)]))


@tagged('post_install', '-at_install', 'gt_phase2', 'gt_download')
class TestDownloads(LifecycleFixtures, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.a = cls.env.company
        cls.b = cls.env['res.company'].create({'name': 'Download B'})
        cls.kind = cls.env['gt.certificate.type'].create({'name': 'Download test', 'code': 'DL'})
        cls.vendor = cls.env['res.partner'].create({'name': 'Download supplier'})
        cls.buyer = TestFoundation.make_user.__func__(cls, 'downloadbuyer', 'group_user')
        cls.manager = TestFoundation.make_user.__func__(cls, 'downloadmanager', 'group_manager')
        cls.reviewer = TestFoundation.make_user.__func__(cls, 'downloadreviewer', 'group_reviewer')
        for user in (cls.buyer, cls.manager, cls.reviewer):
            user.password = 'gt-test-password'
        cls.cert = cls.env['gt.supplier.certificate'].create({'company_id': cls.a.id, 'supplier_id': cls.vendor.id, 'type_id': cls.kind.id, 'reference': 'DOWNLOAD', 'valid_from': '2026-01-01', 'valid_until': '2027-01-01'})

    def test_actual_content_routes(self):
        self.submit()
        evidence = self.cert.evidence_id
        legacy = self.env['ir.attachment'].create({'name': 'restricted.pdf', 'raw': pdf_content(), 'res_model': 'gt.certificate.evidence', 'res_id': evidence.id, 'res_field': 'data', 'public': False})
        urls = ['/web/content/%s?download=true' % legacy.id, '/web/content/gt.certificate.evidence/%s/data?download=true' % evidence.id, '/web/content/gt.certificate.evidence/%s/data' % evidence.id, '/web/content?model=gt.certificate.evidence&id=%s&field=data' % evidence.id]
        for user in (self.buyer, self.manager):
            self.authenticate(user.login, 'gt-test-password')
            for url in urls:
                response = self.url_open(url)
                self.assertIn(response.status_code, (403, 404))
                self.assertNotIn(b'%PDF-', response.content)
        self.authenticate(self.reviewer.login, 'gt-test-password')
        response = self.url_open(urls[1])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'%PDF-'))
        self.assertIn('attachment', response.headers.get('Content-Disposition', ''))
        self.manager.company_ids = [Command.set((self.a | self.b).ids)]
        foreign = self.env['gt.supplier.certificate'].create({'company_id': self.b.id, 'supplier_id': self.vendor.id, 'type_id': self.kind.id, 'reference': 'FOREIGN', 'valid_from': '2026-01-01', 'valid_until': '2027-01-01'})
        self.submit(foreign)
        response = self.url_open('/web/content/gt.certificate.evidence/%s/data?download=true' % foreign.evidence_id.id)
        self.assertIn(response.status_code, (403, 404))
        self.assertNotIn(b'%PDF-', response.content)
