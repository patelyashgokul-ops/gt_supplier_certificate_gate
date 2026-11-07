from datetime import datetime
from zoneinfo import ZoneInfo
import base64
import binascii
import hashlib
import io

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.pdf import PdfReader
from .foundation import Certificate as FoundationCertificate, Evidence as FoundationEvidence

PROTECTED = {'state', 'reviewer_id', 'reviewed_at', 'submitter_id', 'submitted_at', 'evidence_id', 'rejection_reason', 'revoked_by_id', 'revoked_at', 'revocation_reason'}
IDENTITY = {'company_id', 'supplier_id', 'type_id', 'reference', 'valid_from', 'valid_until'}


class Company(models.Model):
    _inherit = 'res.company'

    def _gt_today(self):
        self.ensure_one()
        # Business date is fixed by company partner timezone; never by RPC context.
        return datetime.now(ZoneInfo(self.partner_id.tz or 'UTC')).date()


class Certificate(models.Model):
    _inherit = 'gt.supplier.certificate'

    submitter_id = fields.Many2one('res.users', readonly=True, copy=False)
    submitted_at = fields.Datetime(readonly=True, copy=False)
    evidence_id = fields.Many2one('gt.certificate.evidence', readonly=True, copy=False, ondelete='restrict')
    rejection_reason = fields.Text(readonly=True, copy=False)
    revoked_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    revoked_at = fields.Datetime(readonly=True, copy=False)
    revocation_reason = fields.Text(readonly=True, copy=False)
    validity = fields.Selection([('unverified', 'Unverified'), ('effective', 'Currently Effective'), ('future', 'Not Yet Effective'), ('expired', 'Expired'), ('revoked', 'Revoked')], compute='_compute_validity')

    @api.depends('state', 'valid_from', 'valid_until')
    def _compute_validity(self):
        for record in self:
            today = record.company_id._gt_today()
            record.validity = ('revoked' if record.state == 'revoked' else 'unverified' if record.state != 'verified' else 'future' if record.valid_from > today else 'expired' if record.valid_until < today else 'effective')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if PROTECTED & vals.keys():
                raise AccessError('Workflow fields are set only by controlled actions.')
        # Context defaults are untrusted RPC input too.
        clean = {k: v for k, v in self.env.context.items() if k not in {'default_' + f for f in PROTECTED}}
        return super(Certificate, self.with_context(clean)).create(vals_list)

    def _lock(self):
        self.check_access('write')
        if self:
            self.flush_recordset()
            self.env.cr.execute('SELECT id FROM gt_supplier_certificate WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(self.ids)])
            self.invalidate_recordset()
        for record in self:
            if record.company_id not in self.env.companies or (not self.env.su and record.company_id not in self.env.user.company_ids):
                raise AccessError('Certificate company is not authorized.')

    def write(self, vals):
        self._lock()
        if PROTECTED & vals.keys():
            raise AccessError('Workflow fields are set only by controlled actions.')
        if IDENTITY & vals.keys() and any(r.state != 'draft' or r.evidence_id for r in self):
            raise UserError('Submitted evidence and its identity are immutable. Create a new version.')
        return super().write(vals)

    def unlink(self):
        self._lock()
        if any(r.state != 'draft' or r.evidence_id for r in self):
            raise UserError('Evidence and decisions must remain in history.')
        return super().unlink()

    def _decision_write(self, vals):
        # Private, never RPC callable. Skip only the two workflow guards after
        # the action has authorized and locked every record. No context bypass.
        return super(FoundationCertificate, self).write(vals)

    def action_upload(self):
        self.ensure_one()
        self._lock()
        if self.state != 'draft' or self.evidence_id:
            raise UserError('Create a new certificate version for new evidence.')
        return {'type': 'ir.actions.act_window', 'name': 'Submit Restricted PDF', 'res_model': 'gt.certificate.upload', 'view_mode': 'form', 'target': 'new', 'context': {'default_certificate_id': self.id}}

    def _upload(self, content):
        self.ensure_one()
        self._lock()
        if self.state != 'draft' or self.evidence_id:
            raise UserError('Evidence already submitted. Create a new version.')
        data = self.env['gt.certificate.upload']._fields['data'].convert_to_cache(content, self)
        raw = data.content if data else b''
        if not raw or len(raw) > 10 * 1024 * 1024 or not raw.startswith(b'%PDF-') or b'%%EOF' not in raw[-1024:]:
            raise ValidationError('Submit a non-empty PDF up to 10 MiB.')
        try:
            pdf = PdfReader(io.BytesIO(raw), strict=True)
            if pdf.is_encrypted or not 0 < len(pdf.pages) <= 500:
                raise ValueError('encrypted or empty')
            # Inspect parsed names too: PDF name escapes must not hide actions.
            seen, todo = set(), [pdf.trailer]
            forbidden = {'/JavaScript', '/JS', '/Launch', '/EmbeddedFiles', '/EmbeddedFile', '/RichMedia', '/OpenAction', '/AA', '/A', '/XFA'}
            while todo:
                node = todo.pop()
                if hasattr(node, 'get_object'):
                    node = node.get_object()
                if id(node) in seen:
                    continue
                seen.add(id(node))
                if len(seen) > 20000:
                    raise ValueError('PDF object limit')
                if isinstance(node, dict):
                    if forbidden.intersection(map(str, node.keys())) or str(node.get('/S', '')) in forbidden:
                        raise ValueError('active content')
                    todo.extend(node.values())
                elif isinstance(node, (list, tuple)):
                    todo.extend(node)
            # Reject active content; PDF authenticity is a human review responsibility.
            if any(marker in raw for marker in (b'/JavaScript', b'/JS', b'/Launch', b'/EmbeddedFile', b'/RichMedia', b'/OpenAction', b'/AA')):
                raise ValueError('active content')
        except Exception as exc:
            raise ValidationError('PDF must be readable, unencrypted and contain no active or embedded content.') from exc
        vault = self.env['gt.certificate.evidence']
        # Narrow privilege: immutable vault insert only, after caller write/company
        # checks; no caller-selected company, filename, attachment or token.
        evidence = super(FoundationEvidence, vault.sudo()).create({'certificate_id': self.id, 'company_id': self.company_id.id, 'data': data, 'sha256': hashlib.sha256(raw).hexdigest()})
        self._decision_write({'evidence_id': evidence.id, 'submitter_id': self.env.uid, 'submitted_at': fields.Datetime.now(), 'state': 'pending'})

    def _review_check(self, state):
        if not self.env.user.has_group('gt_supplier_certificate_gate.group_reviewer'):
            raise AccessError('Certificate Reviewer permission is required.')
        self._lock()
        for record in self:
            if record.state != state or not record.evidence_id:
                raise UserError('The certificate is not in the required review state.')
            record.evidence_id.check_access('read')
            if state == 'pending' and record.submitter_id == self.env.user:
                raise AccessError('A different reviewer must review this submission.')

    def action_approve(self):
        self._review_check('pending')
        self._validate_metadata()
        self._check_company()
        self._decision_write({'state': 'verified', 'reviewer_id': self.env.uid, 'reviewed_at': fields.Datetime.now()})
        return True

    def action_reject(self, reason=None):
        self._review_check('pending')
        if not isinstance(reason, str) or len(reason.strip()) < 5:
            raise ValidationError('A meaningful rejection reason (at least five characters) is required.')
        self._decision_write({'state': 'rejected', 'reviewer_id': self.env.uid, 'reviewed_at': fields.Datetime.now(), 'rejection_reason': reason.strip()})
        return True

    def action_revoke(self, reason=None):
        self._review_check('verified')
        if not isinstance(reason, str) or len(reason.strip()) < 5:
            raise ValidationError('A meaningful revocation reason (at least five characters) is required.')
        self._decision_write({'state': 'revoked', 'revoked_by_id': self.env.uid, 'revoked_at': fields.Datetime.now(), 'revocation_reason': reason.strip()})
        return True

    def action_decision(self):
        self.ensure_one()
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': 'Review Decision', 'res_model': 'gt.certificate.decision', 'view_mode': 'form', 'target': 'new', 'context': {'default_certificate_id': self.id, 'default_operation': 'revoke' if self.state == 'verified' else 'reject'}}

    def action_evidence(self):
        self.ensure_one()
        if not self.env.user.has_group('gt_supplier_certificate_gate.group_reviewer'):
            raise AccessError('Certificate Reviewer permission is required.')
        self.check_access('read')
        self.evidence_id.check_access('read')
        return {'type': 'ir.actions.act_url', 'url': '/web/content/gt.certificate.evidence/%s/data?download=true' % self.evidence_id.id, 'target': 'new'}

    def action_history(self):
        self.ensure_one()
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': 'Certificate Versions', 'res_model': self._name, 'view_mode': 'list,form', 'domain': [('company_id', '=', self.company_id.id), ('supplier_id', '=', self.supplier_id.id), ('type_id', '=', self.type_id.id)]}

    def is_effective(self, evaluation_date, company_id, supplier_id, type_id):
        self.ensure_one()
        self.check_access('read')
        day = fields.Date.to_date(evaluation_date)
        return bool(self.company_id.id == company_id and self.supplier_id.id == supplier_id and self.type_id.id == type_id and (not self.supplier_id.company_id or self.supplier_id.company_id == self.company_id) and self.state == 'verified' and self.evidence_id and self.valid_from <= day <= self.valid_until)


class Evidence(models.Model):
    _inherit = 'gt.certificate.evidence'
    sha256 = fields.Char(required=True, readonly=True)
    _certificate_unique = models.Constraint('UNIQUE(certificate_id)', 'One immutable evidence version per certificate.')


class Upload(models.TransientModel):
    _name = 'gt.certificate.upload'
    _description = 'Write-only Certificate PDF Submission'
    certificate_id = fields.Many2one('gt.supplier.certificate', required=True)
    # Bytes are deliberately never persisted on the submitter-readable wizard.
    data = fields.Binary(attachment=False, store=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = self.browse()
        for original in vals_list:
            vals = dict(original)
            content = vals.pop('data', None)
            certificate = self.env['gt.supplier.certificate'].browse(vals.get('certificate_id') or self.env.context.get('default_certificate_id'))
            certificate.ensure_one()
            if not content:
                raise ValidationError('A PDF is required.')
            certificate._upload(content)
            record = super().create(vals)
            records |= record
        return records

    def write(self, vals):
        if 'data' in vals or 'certificate_id' in vals:
            raise UserError('Start a new submission instead.')
        return super().write(vals)

    def action_close(self):
        return {'type': 'ir.actions.act_window_close'}


class Decision(models.TransientModel):
    _name = 'gt.certificate.decision'
    _description = 'Certificate Review Reason'
    certificate_id = fields.Many2one('gt.supplier.certificate', required=True)
    operation = fields.Selection([('reject', 'Reject'), ('revoke', 'Revoke')], required=True)
    reason = fields.Text(required=True)

    def action_apply(self):
        self.ensure_one()
        self.check_access('read')
        if self.operation == 'reject':
            self.certificate_id.action_reject(self.reason)
        else:
            self.certificate_id.action_revoke(self.reason)
        return {'type': 'ir.actions.act_window_close'}
