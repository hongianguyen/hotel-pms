# -*- coding: utf-8 -*-
from odoo import models, fields, api


class HotelService(models.Model):
    _name = 'hotel.service'
    _description = 'Hotel Service'
    _order = 'category, name'

    name = fields.Char('Service Name', required=True)
    price = fields.Float('Price', digits=(16, 2), required=True)
    category = fields.Selection([
        ('tour', 'Tour / Activity'),
        ('fnb', 'Food & Beverage'),
        ('misc', 'Miscellaneous'),
    ], string='Category', default='misc', required=True)

    account_id = fields.Many2one(
        'account.account', string='Revenue Account',
        help='GL account for service revenue (e.g. 4020)',
    )
    active = fields.Boolean('Active', default=True)
    description = fields.Text('Description')

    _sql_constraints = [
        ('price_positive', 'CHECK(price >= 0)', 'Price cannot be negative!'),
    ]
