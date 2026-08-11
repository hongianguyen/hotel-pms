# -*- coding: utf-8 -*-
from odoo import models, fields


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    hotel_folio_id = fields.Many2one(
        'hotel.folio', string='Folio', readonly=True, copy=False,
        index=True, ondelete='set null',
        help='Folio this payment settles. Set when reception registers a '
             'deposit or a settlement from the folio.',
    )
