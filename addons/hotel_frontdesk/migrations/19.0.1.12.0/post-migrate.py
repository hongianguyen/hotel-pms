# -*- coding: utf-8 -*-
"""Split each room type's capacity into max adults and max children.

Max occupancy is now max adults + max children. Start every type as
adults-only at its old capacity, so the total is unchanged; the camp's real
adult/children split per type is then entered on the room type form (or
loaded with the deploy). Until it is, a booking with children is refused.
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE hotel_room_type
           SET max_adults = GREATEST(capacity, 1),
               max_children = 0
    """)
