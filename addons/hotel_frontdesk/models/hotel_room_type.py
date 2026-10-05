# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HotelRoomType(models.Model):
    """How many people a room of this type takes, and of which kind.

    The camp counts every person in the room: adults (13+), children (6-12)
    and infants (0-6). Children and infants share one "children" allowance,
    and everyone together must stay within the maximum occupancy.
    """
    _inherit = 'hotel.room.type'

    capacity = fields.Integer(
        'Max Occupancy',
        help='Most people a room of this type takes in total: adults + '
             'children (6-12) + infants (0-6).')
    max_adults = fields.Integer(
        'Max Adults', default=2, required=True,
        help='Most adults (13 and over) a room of this type takes.')
    max_children = fields.Integer(
        'Max Children', default=1, required=True,
        help='Most children a room of this type takes, counting children '
             '(6-12) and infants (0-6) together.')

    @api.constrains('capacity', 'max_adults', 'max_children')
    def _check_occupancy_limits(self):
        for rt in self:
            if rt.capacity < 1:
                raise ValidationError(_('%s: max occupancy must be at least 1.', rt.name))
            if not 1 <= rt.max_adults <= rt.capacity:
                raise ValidationError(_(
                    '%(type)s: max adults must be between 1 and the max occupancy (%(cap)s).',
                    type=rt.name, cap=rt.capacity))
            if not 0 <= rt.max_children <= rt.capacity:
                raise ValidationError(_(
                    '%(type)s: max children must be between 0 and the max occupancy (%(cap)s).',
                    type=rt.name, cap=rt.capacity))

    def occupancy_problem(self, adults, children, infants):
        """Why this party cannot share one room of this type, or None."""
        self.ensure_one()
        kids = (children or 0) + (infants or 0)
        total = (adults or 0) + kids
        if adults > self.max_adults:
            return _('%(type)s takes at most %(n)s adult(s) per room.',
                     type=self.name, n=self.max_adults)
        if kids > self.max_children:
            return _('%(type)s takes at most %(n)s child(ren) per room, counting '
                     'children 6-12 and infants 0-6 together.',
                     type=self.name, n=self.max_children)
        if total > self.capacity:
            return _('%(type)s takes at most %(n)s people per room '
                     '(adults + children + infants).', type=self.name, n=self.capacity)
        return None
