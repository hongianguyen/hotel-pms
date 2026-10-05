# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HotelAccountType(models.Model):
    """Kinds of account that send bookings: OTA, Travel Agent, Corporate...

    Kept as records so the hotel can add its own. Every agency has one, and
    a booking takes its agency's; a booking without an agency is the one
    Direct Guest type. Rate plans can be limited to one account type.
    """
    _name = 'hotel.account.type'
    _description = 'Hotel Account Type'
    _order = 'sequence, name'

    name = fields.Char('Account Type', required=True, translate=True)
    code = fields.Char(
        'Code', help='Short technical name, e.g. ota. Integrations look account '
                     'types up by it, so change it with care.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    is_direct = fields.Boolean(
        'Direct Guest', readonly=True,
        help='The type of bookings made without an agency. There is exactly one.')
    description = fields.Text()

    _code_uniq = models.Constraint('UNIQUE(code)', 'Account type codes must be unique.')

    @api.model
    def direct(self):
        """The Direct Guest type."""
        return (self.env.ref('hotel_frontdesk.account_type_direct', raise_if_not_found=False)
                or self.with_context(active_test=False).search([('is_direct', '=', True)], limit=1))

    @api.model
    def by_code(self, code):
        return self.search([('code', '=', code)], limit=1)

    def write(self, vals):
        if 'active' in vals and not vals['active'] and self.filtered('is_direct'):
            raise UserError(_('The Direct Guest account type cannot be archived.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_direct(self):
        if self.filtered('is_direct'):
            raise UserError(_('The Direct Guest account type cannot be deleted.'))
