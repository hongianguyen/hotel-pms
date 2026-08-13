# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class GdtConnectWizard(models.TransientModel):
    """One-off linking of the company's hoadondientu.gdt.gov.vn account.

    The portal password is passed straight through to the provider and never
    stored: the link only has to be re-made when that password changes.
    """
    _name = 'hoadon30s.gdt.connect.wizard'
    _description = 'Connect GDT Tax Portal Account'

    username = fields.Char('Tax Portal User Name', required=True)
    password = fields.Char('Tax Portal Password', required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'username' in fields_list:
            res.setdefault('username', self.env[
                'hoadon30s.sync.api']._get_param('gdt_username'))
        return res

    def action_connect(self):
        self.ensure_one()
        self.env['hoadon30s.sync.api'].connect_gdt(
            self.username.strip(), self.password)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Tax Portal Connected'),
                'message': _(
                    'Input invoices can now be downloaded for %s.',
                    self.username),
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
