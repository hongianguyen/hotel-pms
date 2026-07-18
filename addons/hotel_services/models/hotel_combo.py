# -*- coding: utf-8 -*-
from odoo import models, fields, api


class HotelCombo(models.Model):
    _name = 'hotel.combo'
    _description = 'Hotel Combo Package (Accommodation + Services)'
    _order = 'name'

    name = fields.Char('Combo Name', required=True, translate=True)
    active = fields.Boolean('Active', default=True)
    description = fields.Text('Description', translate=True)

    room_type_id = fields.Many2one(
        'hotel.room.type', string='Room Type', required=True,
        domain=[('is_roh', '=', False)],
        help='Accommodation included in this combo.',
    )
    nights = fields.Integer('Nights', default=1, required=True)
    nightly_rate = fields.Float(
        'Accommodation Rate / Night', digits=(16, 2), required=True,
        help='Accommodation portion of the combo price, charged per night '
             'instead of the room type base rate or any rate plan.',
    )
    line_ids = fields.One2many(
        'hotel.combo.line', 'combo_id', string='Included Services',
    )

    accommodation_total = fields.Float(
        'Accommodation Total', compute='_compute_totals', store=True,
        digits=(16, 2),
    )
    services_total = fields.Float(
        'Services Total', compute='_compute_totals', store=True, digits=(16, 2),
    )
    total_price = fields.Float(
        'Combo Price', compute='_compute_totals', store=True, digits=(16, 2),
    )

    @api.depends('nights', 'nightly_rate', 'line_ids.subtotal')
    def _compute_totals(self):
        for combo in self:
            combo.accommodation_total = combo.nights * combo.nightly_rate
            combo.services_total = sum(combo.line_ids.mapped('subtotal'))
            combo.total_price = combo.accommodation_total + combo.services_total

    @api.onchange('room_type_id')
    def _onchange_room_type_id(self):
        if self.room_type_id and not self.nightly_rate:
            self.nightly_rate = self.room_type_id.base_rate

    _nights_positive = models.Constraint(
        'CHECK(nights >= 1)', 'A combo must include at least one night!')
    _nightly_rate_positive = models.Constraint(
        'CHECK(nightly_rate >= 0)', 'Accommodation rate cannot be negative!')


class HotelComboLine(models.Model):
    _name = 'hotel.combo.line'
    _description = 'Hotel Combo Service Line'
    _order = 'id'

    combo_id = fields.Many2one(
        'hotel.combo', string='Combo', required=True, ondelete='cascade',
    )
    service_id = fields.Many2one(
        'hotel.service', string='Service', required=True,
    )
    quantity = fields.Float('Quantity', default=1.0, required=True)
    price_unit = fields.Float(
        'Unit Price', digits=(16, 2), required=True,
        help='Price inside the combo (may differ from the standalone '
             'service price).',
    )
    subtotal = fields.Float('Subtotal', compute='_compute_subtotal', store=True)

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit

    @api.onchange('service_id')
    def _onchange_service_id(self):
        if self.service_id:
            self.price_unit = self.service_id.price

    _quantity_positive = models.Constraint(
        'CHECK(quantity > 0)', 'Quantity must be positive!')
