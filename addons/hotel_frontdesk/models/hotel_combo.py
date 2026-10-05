# -*- coding: utf-8 -*-
"""Combo packages priced by who comes (owner, 06 Oct 2026).

A package prices one of two ways:

* **Fixed** -- as packages always have: a flat accommodation rate a night,
  plus each included service at the price listed on it. Packages that
  existed before this change are Fixed and price exactly as they did.
* **Per guest**:
    - Room part, a night: the 5 per-guest brackets of a rate plan (First
      Pax, Second Pax, Extra Adult, Extra Child 6-12, Extra Infant 0-6);
    - Services part, once per stay: each adult pays the adult price for the
      number of adults (1, 2, 3-5, 6-9, 10+), each child 6-12 the child
      price, each infant the infant price;
    - the included services form the schedule, each on its Day (1 = the
      package's first day) at 0, since the services part already pays for
      them.

A package can be limited to one Account Type and to check-in dates.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

ADULT_BRACKETS = (('price_adult_10', 10), ('price_adult_6_9', 6), ('price_adult_3_5', 3),
                  ('price_adult_2', 2), ('price_adult_1', 1))


class HotelCombo(models.Model):
    _inherit = 'hotel.combo'

    pricing = fields.Selection([
        ('fixed', 'Fixed (room rate + listed service prices)'),
        ('per_guest', 'Per guest'),
    ], string='Pricing', default='per_guest', required=True)
    account_type_id = fields.Many2one(
        'hotel.account.type', string='Account Type',
        help='Bookings of this account type only. Empty = all accounts.')
    date_from = fields.Date('Valid From', help='First check-in date this package is sold for.')
    date_to = fields.Date('Valid To', help='Last check-in date this package is sold for.')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)

    # Room part, a night
    room_first_pax = fields.Monetary('First Pax')
    room_second_pax = fields.Monetary('Second Pax')
    room_extra_adult = fields.Monetary('Extra Adult')
    room_extra_child = fields.Monetary('Extra Child (6-12)')
    room_extra_infant = fields.Monetary('Extra Infant (0-6)')

    # Services part, once per stay
    price_adult_1 = fields.Monetary('Adult, 1 Adult', help='Per adult when 1 adult comes.')
    price_adult_2 = fields.Monetary('Adult, 2 Adults', help='Per adult when 2 adults come.')
    price_adult_3_5 = fields.Monetary('Adult, 3-5 Adults', help='Per adult when 3 to 5 adults come.')
    price_adult_6_9 = fields.Monetary('Adult, 6-9 Adults', help='Per adult when 6 to 9 adults come.')
    price_adult_10 = fields.Monetary('Adult, 10+ Adults', help='Per adult when 10 or more adults come.')
    price_child = fields.Monetary('Per Child (6-12)')
    price_infant = fields.Monetary('Per Infant (0-6)')

    @api.constrains('date_from', 'date_to')
    def _check_validity_dates(self):
        for combo in self:
            if combo.date_from and combo.date_to and combo.date_from > combo.date_to:
                raise ValidationError(_('Valid From must be before Valid To.'))

    @api.constrains('room_first_pax', 'room_second_pax', 'room_extra_adult', 'room_extra_child',
                    'room_extra_infant', 'price_adult_1', 'price_adult_2', 'price_adult_3_5',
                    'price_adult_6_9', 'price_adult_10', 'price_child', 'price_infant')
    def _check_prices_not_negative(self):
        for combo in self:
            prices = [combo[f] for f in (
                'room_first_pax', 'room_second_pax', 'room_extra_adult', 'room_extra_child',
                'room_extra_infant', 'price_adult_1', 'price_adult_2', 'price_adult_3_5',
                'price_adult_6_9', 'price_adult_10', 'price_child', 'price_infant')]
            if min(prices) < 0:
                raise ValidationError(_('Package prices cannot be negative.'))

    # ── Who may book it ─────────────────────────────────────────────────
    def available_for(self, account_type, checkin):
        """Why this package cannot be sold to a booking of `account_type`
        checking in on `checkin`, or None."""
        self.ensure_one()
        if self.account_type_id and self.account_type_id != account_type:
            return _('Package "%(combo)s" is for %(type)s bookings only.',
                     combo=self.name, type=self.account_type_id.name)
        if checkin and ((self.date_from and checkin < self.date_from)
                        or (self.date_to and checkin > self.date_to)):
            return _('Package "%(combo)s" is only sold for check-ins from %(start)s to %(end)s.',
                     combo=self.name, start=self.date_from or '…', end=self.date_to or '…')
        return None

    # ── Prices ──────────────────────────────────────────────────────────
    def room_rate_for(self, adults, children=0, infants=0):
        """One night of the room part for this party."""
        self.ensure_one()
        if self.pricing != 'per_guest':
            return self.nightly_rate
        adults, children, infants = adults or 0, children or 0, infants or 0
        return ((self.room_first_pax if adults >= 1 else 0.0)
                + (self.room_second_pax if adults >= 2 else 0.0)
                + self.room_extra_adult * max(adults - 2, 0)
                + self.room_extra_child * children
                + self.room_extra_infant * infants)

    def adult_price_for(self, adults):
        """Per-adult price of the services part for `adults` adults."""
        self.ensure_one()
        for field, smallest in ADULT_BRACKETS:
            if adults >= smallest:
                return self[field]
        return 0.0

    def services_price_for(self, adults, children=0, infants=0):
        """(total, breakdown text) of the services part, once per stay."""
        self.ensure_one()
        adults, children, infants = adults or 0, children or 0, infants or 0
        adult_price = self.adult_price_for(adults)
        total = adults * adult_price + children * self.price_child + infants * self.price_infant
        parts = []
        for count, price, label in ((adults, adult_price, _('adult(s)')),
                                    (children, self.price_child, _('child(ren)')),
                                    (infants, self.price_infant, _('infant(s)'))):
            if count:
                parts.append('%s %s × %s' % (count, label, '{:,.0f}'.format(price)))
        return total, ' + '.join(parts)

    @api.depends('nights', 'nightly_rate', 'line_ids.subtotal', 'pricing',
                 'room_first_pax', 'room_second_pax', 'price_adult_2')
    def _compute_totals(self):
        """Fixed packages: their real price. Per-guest packages depend on the
        party, so the form shows the price for 2 adults as a reference."""
        super()._compute_totals()
        for combo in self.filtered(lambda c: c.pricing == 'per_guest'):
            combo.accommodation_total = combo.nights * combo.room_rate_for(2)
            combo.services_total = combo.services_price_for(2)[0]
            combo.total_price = combo.accommodation_total + combo.services_total


class HotelComboLine(models.Model):
    _inherit = 'hotel.combo.line'

    day = fields.Integer(
        'Day', default=1, required=True,
        help='Day of the package the service is given: 1 = the first day '
             '(check-in), 2 = the next day, and so on.')

    @api.constrains('day')
    def _check_day(self):
        for line in self:
            if line.day < 1:
                raise ValidationError(_('A service day starts at 1 (the first day of the package).'))
            if line.combo_id and line.day > line.combo_id.nights + 1:
                raise ValidationError(_(
                    '%(service)s is on day %(day)s, but package "%(combo)s" has %(nights)s '
                    'night(s), so its last day is %(last)s.',
                    service=line.service_id.name, day=line.day, combo=line.combo_id.name,
                    nights=line.combo_id.nights, last=line.combo_id.nights + 1))

    def date_for(self, checkin):
        self.ensure_one()
        return checkin + timedelta(days=self.day - 1) if checkin else False
