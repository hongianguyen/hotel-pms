# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HotelAddChargeWizard(models.TransientModel):
    _name = 'hotel.add.charge.wizard'
    _description = 'Add Charge to Folio'

    folio_id = fields.Many2one('hotel.folio', string='Folio', required=True)
    name = fields.Char('Description', required=True)
    charge_type = fields.Selection([
        ('fnb', 'Food & Beverage'),
        ('service', 'Service / Tour'),
        ('manual', 'Manual Charge'),
    ], string='Charge Type', default='manual', required=True)
    quantity = fields.Float('Quantity', default=1.0, required=True)
    amount = fields.Float('Unit Price', required=True, digits=(16, 2))
    service_id = fields.Many2one(
        'hotel.service', string='Service',
        help='Select a predefined service to auto-fill',
    )

    @api.onchange('service_id')
    def _onchange_service_id(self):
        if self.service_id:
            self.name = self.service_id.name
            self.amount = self.service_id.price
            if self.service_id.category == 'fnb':
                self.charge_type = 'fnb'
            else:
                self.charge_type = 'service'

    def action_add_charge(self):
        """Create a new folio line from wizard."""
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_('Unit price must be positive.'))

        account = False
        if self.service_id and self.service_id.account_id:
            account = self.service_id.account_id.id

        self.env['hotel.folio.line'].create({
            'folio_id': self.folio_id.id,
            'name': self.name,
            'charge_type': self.charge_type,
            'quantity': self.quantity,
            'amount': self.amount,
            'account_id': account,
        })
        return {'type': 'ir.actions.act_window_close'}
