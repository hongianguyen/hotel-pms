# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HotelReservationService(models.Model):
    """Service booked together with a reservation.

    Lines can be entered from the moment the booking is created (draft).
    They are included in the reservation's quoted total and are posted to
    the folio at check-in; lines added while the guest is checked in are
    posted to the folio immediately.
    """
    _name = 'hotel.reservation.service'
    _description = 'Reservation Service Line'
    _order = 'id'

    reservation_id = fields.Many2one(
        'hotel.reservation', string='Reservation',
        required=True, ondelete='cascade', index=True,
    )
    service_id = fields.Many2one(
        'hotel.service', string='Service', required=True,
    )
    quantity = fields.Float('Quantity', default=1.0, required=True)
    price_unit = fields.Float(
        'Unit Price', digits=(16, 2), required=True,
        help='Defaults to the service list price; can be overridden.',
    )
    subtotal = fields.Float('Subtotal', compute='_compute_subtotal', store=True)
    date = fields.Date(
        'Service Date',
        help='Day the service is delivered. Defaults to the check-in date '
             'when posted to the folio.',
    )
    note = fields.Char('Note')
    combo_id = fields.Many2one(
        'hotel.combo', string='From Combo', readonly=True,
        ondelete='set null',
        help='Set when this line was added automatically by selecting a '
             'combo package on the reservation.',
    )
    folio_line_id = fields.Many2one(
        'hotel.folio.line', string='Folio Charge', readonly=True, copy=False,
        ondelete='set null',
        help='Set once this service has been charged to the folio.',
    )
    is_charged = fields.Boolean(
        'Charged', compute='_compute_is_charged',
        help='Whether this service has already been charged to the folio.',
    )

    _quantity_positive = models.Constraint(
        'CHECK(quantity > 0)', 'Service quantity must be positive!')

    @api.depends('folio_line_id')
    def _compute_is_charged(self):
        for line in self:
            line.is_charged = bool(line.folio_line_id)

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit

    @api.onchange('service_id')
    def _onchange_service_id(self):
        if self.service_id:
            self.price_unit = self.service_id.price

    # ── Folio posting ────────────────────────────────────────────────────

    def _post_to_folio(self):
        """Charge unposted lines to their reservation's folio."""
        for line in self:
            if line.folio_line_id or not line.reservation_id.folio_id:
                continue
            charge_type = 'fnb' if line.service_id.category == 'fnb' else 'service'
            # Routing instructions decide whether the company or the guest
            # picks this up; incidentals stay with the guest by default.
            folio = line.reservation_id._folio_for_charge_type(charge_type)
            name = line.service_id.name
            if line.combo_id:
                name = _('%(service)s — Combo %(combo)s',
                         service=name, combo=line.combo_id.name)
            if line.note:
                name = '%s — %s' % (name, line.note)
            # sudo mirrors folio creation at check-in: posting is an internal
            # side-effect fully derived from this reservation's own data.
            folio_line = self.env['hotel.folio.line'].sudo().create({
                'folio_id': folio.id,
                'name': name,
                'charge_type': charge_type,
                'quantity': line.quantity,
                'amount': line.price_unit,
                'date': line.date or line.reservation_id.checkin_date
                        or fields.Date.context_today(line),
                'account_id': line.service_id.account_id.id or False,
            })
            line.folio_line_id = folio_line.id

    # ── Guards: keep lines consistent with the folio once charged ────────

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            state = line.reservation_id.state
            if state in ('checked_out', 'cancelled'):
                raise UserError(_(
                    'Cannot add services to reservation %s (%s). '
                    'Add a charge on the folio instead.'
                ) % (line.reservation_id.reservation_number, state))
            if state == 'checked_in':
                line._post_to_folio()
        return lines

    def write(self, vals):
        protected = {'service_id', 'quantity', 'price_unit', 'date'}
        if protected & set(vals):
            posted = self.filtered('folio_line_id')
            if posted:
                raise UserError(_(
                    'Service line(s) %s are already charged to the folio and '
                    'can no longer be modified. Adjust the folio charge '
                    'instead.') % ', '.join(posted.mapped('service_id.name')))
        return super().write(vals)

    def unlink(self):
        posted = self.filtered('folio_line_id')
        if posted:
            raise UserError(_(
                'Service line(s) %s are already charged to the folio and '
                'cannot be deleted. Remove the folio charge instead.'
            ) % ', '.join(posted.mapped('service_id.name')))
        return super().unlink()
