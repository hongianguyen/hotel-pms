# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HotelAddChargeWizard(models.TransientModel):
    _name = 'hotel.add.charge.wizard'
    _description = 'Add Charge to Folio'

    folio_id = fields.Many2one('hotel.folio', string='Folio', required=True)
    linked_folio_id = fields.Many2one(
        'hotel.folio', related='folio_id.linked_folio_id', readonly=True,
    )
    # Not required at DB level: the NOT NULL constraint fires before the
    # compute has run on create. The view marks it required instead, and
    # action_add_charge falls back to the folio it was opened from.
    post_to_folio_id = fields.Many2one(
        'hotel.folio', string='Post To',
        compute='_compute_post_to_folio_id', store=True, readonly=False,
        domain="['|', ('id', '=', folio_id), ('id', '=', linked_folio_id)]",
        help='Folio this charge lands on. Defaults to the routing '
             'instructions for the booking; override to move a single charge '
             'between the guest and company folio.',
    )
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

    @api.depends('folio_id', 'charge_type')
    def _compute_post_to_folio_id(self):
        for wizard in self:
            folio = wizard.folio_id
            reservation = folio.reservation_id
            if reservation and folio.linked_folio_id:
                wizard.post_to_folio_id = reservation._folio_for_charge_type(
                    wizard.charge_type)
            else:
                wizard.post_to_folio_id = folio

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
        if self.quantity <= 0:
            raise UserError(_('Quantity must be positive.'))

        target = self.post_to_folio_id or self.folio_id
        if target.invoice_id:
            # Nothing adds lines to an existing invoice, so a charge posted
            # now could never be billed: it would sit on the folio as a
            # permanent phantom balance and show up unpaid in every night
            # audit. Refuse instead of silently losing the revenue.
            raise UserError(_(
                'Folio %(folio)s is already invoiced (%(invoice)s), so this '
                'charge could never be billed.\n\n'
                'Raise a separate invoice for this amount in Accounting, or '
                'have an administrator reset the folio invoice first.',
                folio=target.name,
                invoice=target.invoice_id.name or _('draft'),
            ))

        account = False
        if self.service_id and self.service_id.account_id:
            account = self.service_id.account_id.id

        self.env['hotel.folio.line'].create({
            'folio_id': (self.post_to_folio_id or self.folio_id).id,
            'name': self.name,
            'charge_type': self.charge_type,
            'quantity': self.quantity,
            'amount': self.amount,
            'account_id': account,
        })
        return {'type': 'ir.actions.act_window_close'}
