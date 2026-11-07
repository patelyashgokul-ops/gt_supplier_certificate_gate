from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class CertificateType(models.Model):
    _name = 'gt.certificate.type'
    _description = 'Certificate Classification'
    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    description = fields.Text()
    _code_unique = models.Constraint('UNIQUE(code)', 'Certificate code must be unique.')


class Requirement(models.Model):
    _name = 'gt.certificate.requirement'
    _description = 'Category Certificate Requirement'
    _check_company_auto = True
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    category_id = fields.Many2one('product.category', required=True, check_company=True, ondelete='restrict', index=True)
    type_id = fields.Many2one('gt.certificate.type', required=True, ondelete='restrict')
    active = fields.Boolean(default=True)
    # Database-enforced partial uniqueness also covers concurrent configuration.
    _active_unique = models.UniqueIndex('(company_id, category_id, type_id) WHERE active')


class Certificate(models.Model):
    _name = 'gt.supplier.certificate'
    _description = 'Supplier Certificate Metadata'
    _check_company_auto = True
    _rec_name = 'reference'
    _order = 'valid_until desc, id desc'
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    supplier_id = fields.Many2one('res.partner', required=True, check_company=True, ondelete='restrict', index=True)
    type_id = fields.Many2one('gt.certificate.type', required=True, ondelete='restrict', index=True)
    reference = fields.Char(required=True)
    valid_from = fields.Date(required=True)
    valid_until = fields.Date(required=True, index=True)
    owner_id = fields.Many2one('res.users', string='Renewal Owner', check_company=True)
    state = fields.Selection([('draft', 'Draft'), ('pending', 'Pending Review'), ('verified', 'Verified'), ('rejected', 'Rejected'), ('revoked', 'Revoked')], default='draft', required=True, readonly=True, copy=False, index=True)
    reviewer_id = fields.Many2one('res.users', readonly=True, copy=False)
    reviewed_at = fields.Datetime(readonly=True, copy=False)

    @api.constrains('valid_from', 'valid_until', 'owner_id', 'company_id')
    def _validate_metadata(self):
        for record in self:
            if record.valid_until < record.valid_from:
                raise ValidationError('Validity end must not precede validity start.')
            if record.owner_id and (not record.owner_id.active or record.owner_id.share or record.company_id not in record.owner_id.company_ids):
                raise ValidationError('Renewal owner must be an active internal user authorized for this company.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if any(k in vals for k in ('reviewer_id', 'reviewed_at')) or vals.get('state', 'draft') != 'draft':
                raise AccessError('Review decisions cannot be supplied on creation.')
        return super().create(vals_list)

    def write(self, vals):
        if {'state', 'reviewer_id', 'reviewed_at'} & vals.keys():
            raise AccessError('Review decisions require a controlled review action.')
        return super().write(vals)


class Evidence(models.Model):
    _name = 'gt.certificate.evidence'
    _description = 'Restricted Certificate Evidence'
    _check_company_auto = True
    certificate_id = fields.Many2one('gt.supplier.certificate', required=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    # No attachment, token, chatter, or buyer-readable binary relationship.
    data = fields.Binary(attachment=False, groups='gt_supplier_certificate_gate.group_reviewer')

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError('Evidence upload is disabled until the secure submission workflow is verified.')

    def write(self, vals):
        raise AccessError('Evidence is immutable.')

    def unlink(self):
        raise AccessError('Evidence deletion is disabled.')
