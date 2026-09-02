# -*- coding: utf-8 -*-
"""Translation between this PMS's records and Aiosell's codes.

Aiosell's ``rateplanCode`` is finer-grained than ``hotel.rate.plan``: upstream
a code identifies a (room type, plan, occupancy) triple — ``executive-s-ep``
and ``executive-d-cp`` are separate codes on the same room. Locally a rate plan
may deliberately have no room type at all ("applies to all types"). So the
mapping is keyed on the pair, and one local rate plan may legitimately fan out
to several Aiosell codes.
"""
from odoo import _, api, fields, models


class AiosellRoomMapping(models.Model):
    _name = 'aiosell.room.mapping'
    _description = 'Aiosell Room Type Mapping'
    _order = 'config_id, remote_name'

    config_id = fields.Many2one(
        'aiosell.config', required=True, ondelete='cascade', index=True,
    )
    active = fields.Boolean(default=True)
    room_code = fields.Char(
        'Aiosell Room Code', required=True,
        help='The room_id value returned by property_details.',
    )
    remote_name = fields.Char('Aiosell Room Name', readonly=True)
    remote_count = fields.Integer('Aiosell Room Count', readonly=True)
    room_type_id = fields.Many2one(
        'hotel.room.type', string='PMS Room Type',
        domain=[('is_roh', '=', False)],
        help='Run-of-House types cannot be mapped: they are virtual and '
             'overlap the physical types, so publishing them would sell the '
             'same room twice.',
    )
    local_count = fields.Integer(
        'PMS Room Count', related='room_type_id.room_count', readonly=True,
    )

    _room_code_uniq = models.Constraint(
        'UNIQUE(config_id, room_code)',
        'A room code can only be mapped once per connection.',
    )

    @api.depends('remote_name', 'room_code')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.remote_name or rec.room_code


class AiosellRatePlanMapping(models.Model):
    _name = 'aiosell.rateplan.mapping'
    _description = 'Aiosell Rate Plan Mapping'
    _order = 'config_id, remote_name'

    config_id = fields.Many2one(
        'aiosell.config', required=True, ondelete='cascade', index=True,
    )
    active = fields.Boolean(default=True)
    rateplan_code = fields.Char(
        'Aiosell Rate Plan Code', required=True,
        help='The rateplan_id value returned by property_details.',
    )
    remote_name = fields.Char('Aiosell Rate Plan Name', readonly=True)
    occupancy = fields.Integer(
        'Occupancy', readonly=True,
        help='Occupancy this Aiosell code prices. Recorded for reference: '
             'the PMS rate plans are not occupancy-priced, so every code on a '
             'room currently receives the same nightly rate.',
    )
    room_mapping_id = fields.Many2one(
        'aiosell.room.mapping', string='Room Mapping', ondelete='cascade',
        required=True, index=True,
    )
    room_code = fields.Char(related='room_mapping_id.room_code', store=True)
    room_type_id = fields.Many2one(
        related='room_mapping_id.room_type_id', store=True, string='PMS Room Type',
    )
    rate_plan_id = fields.Many2one('hotel.rate.plan', string='PMS Rate Plan')

    _rateplan_code_uniq = models.Constraint(
        'UNIQUE(config_id, rateplan_code)',
        'A rate plan code can only be mapped once per connection.',
    )

    def _rate_for_date(self, day):
        """Nightly rate to publish for this code, or 0 when it is closed.

        ``get_rate_for_date`` returns ``False`` when the plan does not apply —
        stop-sell, out of season, excluded weekday. That must stay falsy all
        the way out: a 0 pushed to Aiosell is a free room on the OTA.
        """
        self.ensure_one()
        if not self.rate_plan_id or not self.room_type_id:
            return 0.0
        rate = self.rate_plan_id.get_rate_for_date(day)
        if rate is False:
            return 0.0
        # A plan with no rate of its own and no room type falls back to the
        # room type this code is mapped to.
        if not rate:
            rate = self.room_type_id.base_rate
        return round(rate, 2) if rate else 0.0

    @api.depends('remote_name', 'rateplan_code')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.remote_name or rec.rateplan_code
