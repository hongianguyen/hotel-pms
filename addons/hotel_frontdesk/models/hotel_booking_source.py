# -*- coding: utf-8 -*-
from odoo import models, fields


class HotelBookingSource(models.Model):
    _name = 'hotel.booking.source'
    _description = 'Hotel Booking Source'
    _order = 'name'

    name = fields.Char('Source Name', required=True, translate=True)
    active = fields.Boolean(default=True)
