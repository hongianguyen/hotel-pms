# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    hoadon30s_sync_base_url = fields.Char(
        'Input Invoice Server', config_parameter='hoadon30s.sync.base_url',
        default='https://cpanel.hoadon30s.vn',
        help='hoadon30s.vn invoice-sync server. Unlike the e-invoice '
             'issuance service, this one has a single host for both testing '
             'and production: https://cpanel.hoadon30s.vn. The issuance UAT '
             'host does not serve invoice-sync and answers invalid_client.')
    hoadon30s_sync_client_id = fields.Char(
        'Sync Client ID', config_parameter='hoadon30s.sync.client_id',
        help='Credentials for the input-invoice service. These are separate '
             'from the e-invoice issuance credentials.')
    hoadon30s_sync_client_secret = fields.Char(
        'Sync Client Secret', config_parameter='hoadon30s.sync.client_secret')
    hoadon30s_sync_gdt_username = fields.Char(
        'Tax Portal User Name',
        config_parameter='hoadon30s.sync.gdt_username',
        help='The hoadondientu.gdt.gov.vn login. Set by "Connect Tax Portal" '
             'and sent with every download request.')
    hoadon30s_sync_cron_enabled = fields.Boolean(
        'Download Automatically', config_parameter='hoadon30s.sync.cron_enabled',
        help='Let the daily scheduled action download new input invoices. '
             'Downloads are billed per invoice by the provider, so this is '
             'off until you enable it.')

    def action_hoadon30s_sync_check_quota(self):
        """Show the remaining download quota."""
        self.ensure_one()
        data = self.env['hoadon30s.sync.api'].get_used_amount()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Input Invoice Quota'),
                'message': _(
                    'Total: %(total)s — used: %(used)s — remaining: '
                    '%(remaining)s',
                    total=data.get('total', '?'),
                    used=data.get('total_used', data.get('used', '?')),
                    remaining=data.get('remaining', '?')),
                'type': 'info',
                'sticky': True,
            },
        }

    def action_hoadon30s_sync_connect(self):
        """Open the one-off tax-portal connection wizard."""
        self.ensure_one()
        if not self.env['hoadon30s.sync.api']._is_configured():
            raise UserError(_(
                'Save the Client ID and Client Secret first.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Connect Tax Portal'),
            'res_model': 'hoadon30s.gdt.connect.wizard',
            'view_mode': 'form',
            'target': 'new',
        }
