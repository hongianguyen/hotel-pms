# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class EinvoiceFetchWizard(models.TransientModel):
    _name = 'hoadon30s.einvoice.fetch.wizard'
    _description = 'Fetch E-Invoices from hoadon30s.vn'

    date_from = fields.Date(
        'From', required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(
        'To', required=True,
        default=lambda self: fields.Date.context_today(self))

    def action_fetch(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('"From" must be before "To".'))
        summary = self.env['hoadon30s.einvoice'].fetch_invoices(
            self.date_from, self.date_to)
        return {
            'type': 'ir.actions.act_window',
            'name': _('E-Invoices (%(found)s found, %(created)s new, '
                      '%(partners_created)s partners created)', **summary),
            'res_model': 'hoadon30s.einvoice',
            'view_mode': 'list,form',
            'domain': [('date_export', '>=', self.date_from),
                       ('date_export', '<=', self.date_to)],
        }
