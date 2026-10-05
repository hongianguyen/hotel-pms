# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HotelRoomType(models.Model):
    """How many people a room of this type takes, and of which kind.

    The camp sets two numbers per type: max adults (13+) and max children,
    where children counts children 6-12 and infants 0-6 together. Max
    occupancy is not set separately: it is always the two added up.
    """
    _inherit = 'hotel.room.type'

    max_adults = fields.Integer(
        'Max Adults', default=2, required=True,
        help='Most adults (13 and over) a room of this type takes.')
    max_children = fields.Integer(
        'Max Children (0-12)', default=1, required=True,
        help='Most children a room of this type takes, counting children '
             '(6-12) and infants (0-6) together.')
    capacity = fields.Integer(
        'Max Occupancy', compute='_compute_capacity', inverse='_inverse_capacity',
        store=True, readonly=True, default=None,
        help='Max adults + max children: the most people a room of this '
             'type takes.')

    @api.depends('max_adults', 'max_children')
    def _compute_capacity(self):
        for rt in self:
            rt.capacity = rt.max_adults + rt.max_children

    def _inverse_capacity(self):
        # Code and data files written before the split still set `capacity`
        # alone. Read that as "this many adults" -- the only reading that
        # keeps the total they meant.
        for rt in self:
            if rt.max_adults + rt.max_children != rt.capacity:
                rt.write({'max_adults': rt.capacity, 'max_children': 0})

    @api.constrains('max_adults', 'max_children')
    def _check_occupancy_limits(self):
        for rt in self:
            if rt.max_adults < 1:
                raise ValidationError(_('%s: max adults must be at least 1.', rt.name))
            if rt.max_children < 0:
                raise ValidationError(_('%s: max children cannot be negative.', rt.name))

    def occupancy_problem(self, adults, children, infants):
        """Why this party cannot share one room of this type, or None.
        The occupancy follows from the two limits, so they are all there is
        to check."""
        self.ensure_one()
        kids = (children or 0) + (infants or 0)
        if adults > self.max_adults:
            return _('%(type)s takes at most %(n)s adult(s) per room.',
                     type=self.name, n=self.max_adults)
        if kids > self.max_children:
            return _('%(type)s takes at most %(n)s child(ren) per room, counting '
                     'children 6-12 and infants 0-6 together.',
                     type=self.name, n=self.max_children)
        return None
