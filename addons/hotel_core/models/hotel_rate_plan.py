# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class HotelRatePlan(models.Model):
    _name = 'hotel.rate.plan'
    _description = 'Hotel Rate Plan'
    _order = 'name'

    name = fields.Char('Rate Plan Name', required=True)
    room_type_id = fields.Many2one(
        'hotel.room.type', string='Room Type',
        help='Leave empty to apply to all room types',
    )
    base_rate = fields.Float(
        'Override Rate / Night', digits=(16, 2),
        help='If set, overrides the room type base rate',
    )
    min_stay = fields.Integer('Minimum Stay (nights)', default=1)
    stop_sell = fields.Boolean(
        'Stop Sell', default=False,
        help='Block this rate plan from new reservations',
    )
    active = fields.Boolean('Active', default=True)

    # Season validity
    date_from = fields.Date('Valid From')
    date_to = fields.Date('Valid To')

    # Day-of-week rules
    day_monday = fields.Boolean('Mon', default=True)
    day_tuesday = fields.Boolean('Tue', default=True)
    day_wednesday = fields.Boolean('Wed', default=True)
    day_thursday = fields.Boolean('Thu', default=True)
    day_friday = fields.Boolean('Fri', default=True)
    day_saturday = fields.Boolean('Sat', default=True)
    day_sunday = fields.Boolean('Sun', default=True)

    notes = fields.Text('Notes')

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for plan in self:
            if plan.date_from and plan.date_to and plan.date_from > plan.date_to:
                raise ValidationError(_('Valid From must be before Valid To.'))

    def get_rate_for_date(self, check_date):
        """Return the nightly rate for a given date, or False if not applicable."""
        self.ensure_one()
        if self.stop_sell:
            return False
        if self.date_from and check_date < self.date_from:
            return False
        if self.date_to and check_date > self.date_to:
            return False
        weekday = check_date.weekday()
        day_fields = [
            'day_monday', 'day_tuesday', 'day_wednesday',
            'day_thursday', 'day_friday', 'day_saturday', 'day_sunday',
        ]
        if not getattr(self, day_fields[weekday]):
            return False
        return self.base_rate or (self.room_type_id.base_rate if self.room_type_id else 0.0)

    _name_uniq = models.Constraint('UNIQUE(name)', 'Rate plan name must be unique!')
    _min_stay_positive = models.Constraint('CHECK(min_stay >= 1)', 'Minimum stay must be at least 1!')
