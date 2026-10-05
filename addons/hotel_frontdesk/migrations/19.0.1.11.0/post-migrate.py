# -*- coding: utf-8 -*-
"""Seed the new per-type adult and children limits from the old capacity.

Until now a room type had one number, `capacity`. Keep it as the total and
start each type at: as many adults as the total, and children (6-12 plus
infants) up to the total minus one adult. That changes nothing a booking
could do before except refuse a room of children with no adult; the camp
then tightens each type on the room type form.
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE hotel_room_type
           SET max_adults = GREATEST(capacity, 1),
               max_children = GREATEST(capacity - 1, 0)
    """)
