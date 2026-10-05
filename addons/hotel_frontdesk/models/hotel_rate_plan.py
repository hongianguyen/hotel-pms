# -*- coding: utf-8 -*-
"""Per-guest pricing on rate plans.

A rate plan prices a room one of two ways:

* **Per room** -- one flat price a night, as before. The rates agreed in the
  old PMS were imported this way, and keep pricing exactly as agreed.
* **Per guest** -- the price of a room-night is built from who sleeps in it,
  with one row of brackets per room type:

      First Pax      the 1st adult
      Second Pax     the 2nd adult
      Extra Adult    each adult after the 2nd
      Extra Child    each child 6-12 (sharing a bed)
      Extra Infant   each infant 0-6

  Only adults fill First and Second Pax (owner, 05 Oct 2026): 1 adult and
  1 child pay First Pax + Extra Child.

The validity rules of a plan (dates, weekdays, stop sell, its season) apply
to both modes alike.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

WEEKDAY_FIELDS = ('day_monday', 'day_tuesday', 'day_wednesday', 'day_thursday',
                  'day_friday', 'day_saturday', 'day_sunday')


class HotelRatePlan(models.Model):
    _inherit = 'hotel.rate.plan'

    pricing_mode = fields.Selection([
        ('room', 'Per room (flat)'),
        ('pax', 'Per guest'),
    ], string='Pricing', default='room', required=True,
        help='Per room: one price a night whoever stays. Per guest: the price '
             'is built from the guests in the room, using the rows below.')
    account_type_id = fields.Many2one(
        'hotel.account.type', string='Account Type',
        help='Which bookings may use this plan. Empty = all accounts. A booking '
             'takes its account type from its agency; without one it is a '
             'Direct Guest booking.')
    is_default = fields.Boolean(
        'Default Plan',
        help='New bookings of this account type made without a rate plan '
             'are priced with this one. One default per account type.')
    line_ids = fields.One2many(
        'hotel.rate.plan.line', 'rate_plan_id', string='Per-Guest Rates', copy=True)

    @api.constrains('is_default', 'account_type_id', 'active')
    def _check_single_default(self):
        for plan in self.filtered('is_default'):
            defaults = self.search([('is_default', '=', True),
                                    ('account_type_id', '=', plan.account_type_id.id)])
            if len(defaults) > 1:
                raise ValidationError(_(
                    'Only one default rate plan per account type; %(type)s has %(plans)s.',
                    type=plan.account_type_id.name or _('All Accounts'),
                    plans=', '.join(defaults.mapped('name'))))

    def allows_account_type(self, account_type):
        """May a booking of `account_type` (a hotel.account.type) use this plan?"""
        self.ensure_one()
        return not self.account_type_id or self.account_type_id == account_type

    def _can_price(self, room_type):
        self.ensure_one()
        if self.pricing_mode == 'pax':
            return room_type in self.line_ids.room_type_id
        return not self.room_type_id or self.room_type_id == room_type

    @api.model
    def default_plan_for(self, room_type, account_type=None):
        """The default plan for this account type (Direct Guest when none is
        given) that can price `room_type`: the type's own default first, then
        the all-accounts one. An empty set when neither fits."""
        if not room_type or room_type.is_roh:
            return self.browse()
        account_type = account_type or self.env['hotel.account.type'].direct()
        defaults = self.search([
            ('is_default', '=', True),
            ('account_type_id', 'in', [account_type.id, False]),
        ])
        for plan in defaults.sorted(lambda p: not p.account_type_id):
            if plan._can_price(room_type):
                return plan
        return self.browse()

    # ── Validity ────────────────────────────────────────────────────────
    def _applies_on(self, day):
        """The plan's own rules for `day`: stop sell, dates, weekdays and,
        when it is tied to one, its season window."""
        self.ensure_one()
        if self.stop_sell:
            return False
        if (self.date_from and day < self.date_from) or (self.date_to and day > self.date_to):
            return False
        if not self[WEEKDAY_FIELDS[day.weekday()]]:
            return False
        season = self['season_id'] if 'season_id' in self._fields else False
        if season and not (season.date_from <= day <= season.date_to):
            return False
        return True

    def _multiplier_on(self, day):
        """Season markup for `day`, as hotel_revenue_basic applies it to flat
        plans: the plan's own season if it has one, else whichever season is
        running. 1.0 without hotel_revenue_basic."""
        self.ensure_one()
        if 'season_id' not in self._fields:
            return 1.0
        if self.season_id:
            return self.season_id.rate_multiplier
        return self.env['hotel.season'].get_multiplier_for_date(day)

    # ── Price ───────────────────────────────────────────────────────────
    def party_rate_for(self, day, room_type, adults, children=0, infants=0):
        """Price of one room-night for this party, or False when this plan
        does not price it (not valid that day, or no row for the room type).
        """
        self.ensure_one()
        if self.pricing_mode != 'pax':
            return self.get_rate_for_date(day)
        line = self.line_ids.filtered(lambda l: l.room_type_id == room_type)[:1]
        if not line or not self._applies_on(day):
            return False
        price = line.price_for(adults, children, infants)
        return price * self._multiplier_on(day) if price else False


class HotelRatePlanLine(models.Model):
    _name = 'hotel.rate.plan.line'
    _description = 'Rate Plan Per-Guest Rates'
    _order = 'rate_plan_id, room_type_id'

    rate_plan_id = fields.Many2one(
        'hotel.rate.plan', required=True, ondelete='cascade', index=True)
    room_type_id = fields.Many2one(
        'hotel.room.type', string='Room Type', required=True, ondelete='cascade')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    first_pax = fields.Monetary('First Pax', help='The 1st adult, per night.')
    second_pax = fields.Monetary('Second Pax', help='The 2nd adult, per night.')
    extra_adult = fields.Monetary('Extra Adult', help='Each adult after the 2nd, per night.')
    extra_child = fields.Monetary(
        'Extra Child (6-12)', help='Each child aged 6-12 sharing a bed, per night.')
    extra_infant = fields.Monetary('Extra Infant (0-6)', help='Each infant under 6, per night.')

    _type_uniq = models.Constraint(
        'UNIQUE(rate_plan_id, room_type_id)',
        'A rate plan has one row per room type.')

    @api.constrains('first_pax', 'second_pax', 'extra_adult', 'extra_child', 'extra_infant')
    def _check_not_negative(self):
        for line in self:
            if min(line.first_pax, line.second_pax, line.extra_adult,
                   line.extra_child, line.extra_infant) < 0:
                raise ValidationError(_('Rates cannot be negative.'))

    def price_for(self, adults, children=0, infants=0):
        """One night for the party. Only adults fill First and Second Pax."""
        self.ensure_one()
        adults, children, infants = adults or 0, children or 0, infants or 0
        return ((self.first_pax if adults >= 1 else 0.0)
                + (self.second_pax if adults >= 2 else 0.0)
                + self.extra_adult * max(adults - 2, 0)
                + self.extra_child * children
                + self.extra_infant * infants)
