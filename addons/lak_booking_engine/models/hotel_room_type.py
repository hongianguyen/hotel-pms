# -*- coding: utf-8 -*-
from odoo import fields, models


class HotelRoomType(models.Model):
    _inherit = 'hotel.room.type'

    # Opt-out rather than opt-in: every physical type the camp has today is
    # sold to the public, and the engine is behind its own enabled flag. ROH
    # types are never sold online regardless (see booking_quote).
    website_bookable = fields.Boolean(
        'Bookable on Website', default=True,
        help='Offer this room type on the camp website\'s booking engine. '
             'Run-of-House types are never offered.',
    )
