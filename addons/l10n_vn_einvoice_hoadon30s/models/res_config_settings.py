# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    hoadon30s_base_url = fields.Char(
        'E-Invoice Server', config_parameter='hoadon30s.base_url',
        default='https://cphoadonuat.hoadon30s.vn',
        help='hoadon30s.vn API server. UAT: https://cphoadonuat.hoadon30s.vn '
             '— Production: https://cpanel.hoadon30s.vn')
    hoadon30s_client_id = fields.Char(
        'Client ID', config_parameter='hoadon30s.client_id')
    hoadon30s_client_secret = fields.Char(
        'Client Secret', config_parameter='hoadon30s.client_secret')
    hoadon30s_serial_vat = fields.Char(
        'VAT Invoice Serial', config_parameter='hoadon30s.serial_vat',
        help='Ký hiệu of the regular VAT invoice form (e.g. 1C26TPA), used '
             'for customer invoices issued from Accounting / Hotel PMS.')
    hoadon30s_serial_mtt = fields.Char(
        'Cash Register Serial', config_parameter='hoadon30s.serial_mtt',
        help='Ký hiệu of the cash-register VAT invoice form (e.g. 1C26MEE), '
             'used for POS orders.')
    hoadon30s_auto_sign = fields.Boolean(
        'Sign Automatically', config_parameter='hoadon30s.auto_sign',
        default=True,
        help='Sign e-invoices digitally as soon as they are created, so they '
             'are sent to the tax authority without a manual step on '
             'hoadon30s.vn.')
    hoadon30s_pos_auto_issue = fields.Boolean(
        'Auto-Issue from POS', config_parameter='hoadon30s.pos_auto_issue',
        default=True,
        help='Issue a cash-register e-invoice automatically every time a POS '
             'order is paid.')
