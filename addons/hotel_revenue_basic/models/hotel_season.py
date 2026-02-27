# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class HotelSeason(models.Model):
    _name = 'hotel.season'
    _description = 'Hotel Season'
    _order = 'date_from'

    name = fields.Char('Season Name', required=True)
    date_from = fields.Date('Start Date', required=True)
    date_to = fields.Date('End Date', required=True)
    rate_multiplier = fields.Float(
        'Rate Multiplier', default=1.0, digits=(5, 2),
        help='Multiplier applied to base rate. E.g. 1.5 = 50% markup for peak season.',
    )
    active = fields.Boolean('Active', default=True)
    notes = fields.Text('Notes')

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from > rec.date_to:
                raise ValidationError(_('Start date must be before end date.'))

    @api.model
    def get_multiplier_for_date(self, check_date):
        """Return the rate multiplier for a given date. Defaults to 1.0."""
        season = self.search([
            ('date_from', '<=', check_date),
            ('date_to', '>=', check_date),
            ('active', '=', True),
        ], limit=1, order='rate_multiplier desc')
        return season.rate_multiplier if season else 1.0

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Season name must be unique!'),
    ]


class HotelRatePlanSeason(models.Model):
    """Extend rate plan with season link."""
    _inherit = 'hotel.rate.plan'

    season_id = fields.Many2one(
        'hotel.season', string='Season',
        help='If linked, this rate plan is only active during this season.',
    )

    def get_rate_for_date(self, check_date):
        """Override to apply season multiplier."""
        rate = super().get_rate_for_date(check_date)
        if rate and self.season_id:
            if check_date < self.season_id.date_from or check_date > self.season_id.date_to:
                return False
            rate *= self.season_id.rate_multiplier
        elif rate and not self.season_id:
            # Apply global season multiplier if any
            multiplier = self.env['hotel.season'].get_multiplier_for_date(check_date)
            rate *= multiplier
        return rate
