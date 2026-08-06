# -*- coding: utf-8 -*-
from odoo import models, fields


class PosConfig(models.Model):
    _inherit = 'pos.config'

    limit_partners_to_in_house = fields.Boolean(
        'Only In-House Guests',
        default=True,
        help='Show only currently checked-in guests in the POS customer list. '
             'Turn this off if the restaurant also needs to invoice walk-in '
             'customers from the point of sale.',
    )
