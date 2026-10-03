# -*- coding: utf-8 -*-
from odoo import fields, models


class HotelReservation(models.Model):
    _inherit = 'hotel.reservation'

    lak_hold_id = fields.Many2one(
        'lak.booking.hold', string='Website Booking', readonly=True,
        copy=False, index=True, ondelete='set null',
        help='The website booking this reservation was created from.',
    )
