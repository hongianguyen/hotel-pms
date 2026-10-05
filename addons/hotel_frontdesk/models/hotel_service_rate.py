# -*- coding: utf-8 -*-
"""Rates for services (tours, meals, transfers...), by account type and date.

A service keeps its single list price as the fallback. A service rate
overrides it for the bookings it matches:

* **Account Type** -- one type, or empty for all accounts;
* **Validity** -- an optional date range and the days of the week;
* **Pricing** (owner, 06 Oct 2026), one of:
    - *Per group*: one price for the whole group, whatever its size;
    - *Per pax*: a price per person that depends on the group's size, in
      the brackets 1, 2, 3-5, 6-9 and 10+. A group of 4 pays 4 x the 3-5
      price.

When several rates match, the one for the booking's own account type beats
an all-accounts one, then the one starting latest (the most specific
season), then the lowest sequence.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

WEEKDAY_FIELDS = ('day_monday', 'day_tuesday', 'day_wednesday', 'day_thursday',
                  'day_friday', 'day_saturday', 'day_sunday')

# (field, smallest group it applies to), largest first
PAX_BRACKETS = (('price_pax_10', 10), ('price_pax_6_9', 6), ('price_pax_3_5', 3),
                ('price_pax_2', 2), ('price_pax_1', 1))


class HotelServiceRate(models.Model):
    _name = 'hotel.service.rate'
    _description = 'Service Rate'
    _order = 'service_id, sequence, date_from desc, id'

    service_id = fields.Many2one(
        'hotel.service', string='Service', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    account_type_id = fields.Many2one(
        'hotel.account.type', string='Account Type',
        help='Bookings of this account type only. Empty = all accounts.')

    # Validity
    date_from = fields.Date('Valid From')
    date_to = fields.Date('Valid To')
    day_monday = fields.Boolean('Mon', default=True)
    day_tuesday = fields.Boolean('Tue', default=True)
    day_wednesday = fields.Boolean('Wed', default=True)
    day_thursday = fields.Boolean('Thu', default=True)
    day_friday = fields.Boolean('Fri', default=True)
    day_saturday = fields.Boolean('Sat', default=True)
    day_sunday = fields.Boolean('Sun', default=True)

    # Price
    pricing = fields.Selection([
        ('group', 'Per group'),
        ('pax', 'Per pax by group size'),
    ], string='Pricing', default='pax', required=True)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    price_group = fields.Monetary('Group Price', help='One price for the whole group.')
    price_pax_1 = fields.Monetary('1 Pax', help='Per person, group of 1.')
    price_pax_2 = fields.Monetary('2 Pax', help='Per person, group of 2.')
    price_pax_3_5 = fields.Monetary('3-5 Pax', help='Per person, group of 3 to 5.')
    price_pax_6_9 = fields.Monetary('6-9 Pax', help='Per person, group of 6 to 9.')
    price_pax_10 = fields.Monetary('10+ Pax', help='Per person, group of 10 or more.')

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rate in self:
            if rate.date_from and rate.date_to and rate.date_from > rate.date_to:
                raise ValidationError(_('Valid From must be before Valid To.'))

    @api.constrains('price_group', 'price_pax_1', 'price_pax_2', 'price_pax_3_5',
                    'price_pax_6_9', 'price_pax_10')
    def _check_not_negative(self):
        for rate in self:
            if min(rate.price_group, rate.price_pax_1, rate.price_pax_2, rate.price_pax_3_5,
                   rate.price_pax_6_9, rate.price_pax_10) < 0:
                raise ValidationError(_('Service rates cannot be negative.'))

    def applies(self, day, account_type):
        """Does this rate cover a service on `day` for a booking of
        `account_type` (a hotel.account.type)?"""
        self.ensure_one()
        if self.account_type_id and self.account_type_id != account_type:
            return False
        if not day:
            return True
        if (self.date_from and day < self.date_from) or (self.date_to and day > self.date_to):
            return False
        return bool(self[WEEKDAY_FIELDS[day.weekday()]])

    def price_per_pax(self, pax):
        """Per-person price for a group of `pax` (per-pax pricing)."""
        self.ensure_one()
        for field, smallest in PAX_BRACKETS:
            if pax >= smallest:
                return self[field]
        return 0.0

    def price_for(self, pax):
        """Price of one service for a group of `pax` people."""
        self.ensure_one()
        if self.pricing == 'group':
            return self.price_group
        pax = max(pax or 1, 1)
        return pax * self.price_per_pax(pax)


class HotelService(models.Model):
    _inherit = 'hotel.service'

    rate_ids = fields.One2many(
        'hotel.service.rate', 'service_id', string='Rates', context={'active_test': False})

    def rate_for(self, day, account_type):
        """The rate that prices this service on `day` for a booking of
        `account_type`, or an empty recordset (the list price applies)."""
        self.ensure_one()
        rates = self.rate_ids.filtered(lambda r: r.active and r.applies(day, account_type))
        if not rates:
            return rates
        return rates.sorted(lambda r: (
            not r.account_type_id,                      # own account type first
            -(r.date_from.toordinal() if r.date_from else 0),   # latest season
            r.sequence, r.id))[:1]

    def price_for(self, day, account_type, pax=1):
        """(unit price, rate) for one service for a group of `pax`."""
        self.ensure_one()
        rate = self.rate_for(day, account_type)
        if rate:
            return rate.price_for(pax), rate
        return self.price, rate
