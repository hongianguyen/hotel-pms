# -*- coding: utf-8 -*-
"""Sellable rooms per room type per night, counted once for every seller.

This is the counting rule ``hotel_channel_aiosell`` pushes to the OTAs,
lifted out of ``aiosell.config`` so the website engine sells exactly the
same rooms the channels are told about. Two copies of this rule would drift,
and a drift between them is an oversell -- ``hotel_channel_aiosell`` should be
switched to call this service once both modules ship together.

``hotel.room.get_available_rooms`` is deliberately NOT used: it ignores
drafts and bookings that have a room type but no room yet, so it reports
rooms as free that reception has already promised.
"""
from datetime import date, timedelta

from odoo import api, models

# Reservation states that take a room out of the sellable pool.
BLOCKING_STATES = ('confirmed', 'checked_in')


def daterange(start, end):
    """Nights from start up to but not including end."""
    current = start
    while current < end:
        yield current
        current += timedelta(days=1)


class HotelAvailability(models.AbstractModel):
    _name = 'hotel.availability'
    _description = 'Hotel Sellable Inventory'

    @api.model
    def _room_out_of_service(self, room, day):
        """True when `room` cannot be sold on `day`.

        Maintenance is held two ways in this PMS: a current status, and an
        optional date window. A window is authoritative when present; a bare
        'maintenance' status with no window is treated as out for the whole
        horizon, which is the safe reading.
        """
        start, stop = room.maintenance_date_from, room.maintenance_date_to
        if start or stop:
            return (start or date.min) <= day <= (stop or date.max)
        return room.status == 'maintenance'

    @api.model
    def compute(self, start, end, draft_holds=True):
        """Sellable rooms as {room_type_id: {date: n}} for nights [start, end).

        * a room is out on a night if it is under maintenance that night;
        * a reservation with a room assigned takes that specific room out;
        * a reservation without a room yet still has to be honoured, so it is
          subtracted from its room type's count;
        * a Run-of-House booking with no room yet could land on any physical
          type, so it is subtracted from whichever type has the most left that
          night -- the conservative reading.

        ROH types are virtual and never appear in the result.

        `draft_holds` counts drafts as taken. The website must always pass
        True: its own unpaid holds are drafts, and reception's unconfirmed
        bookings are promises too.
        """
        Room = self.env['hotel.room']
        rooms = Room.search([
            ('active', '=', True),
            ('room_type_id.is_roh', '=', False),
        ])
        nights = list(daterange(start, end))
        avail = {rt: {d: 0 for d in nights} for rt in rooms.mapped('room_type_id').ids}
        room_type_of = {}

        for room in rooms:
            room_type_of[room.id] = room.room_type_id.id
            for day in nights:
                if self._room_out_of_service(room, day):
                    continue
                avail[room.room_type_id.id][day] += 1

        states = list(BLOCKING_STATES) + (['draft'] if draft_holds else [])
        reservations = self.env['hotel.reservation'].search([
            ('state', 'in', states),
            ('checkin_date', '<', end),
            ('checkout_date', '>', start),
        ])
        roh_unassigned = {d: 0 for d in nights}
        for res in reservations:
            first = max(res.checkin_date, start)
            last = min(res.checkout_date, end)
            if res.room_id:
                type_id = room_type_of.get(res.room_id.id)
                if type_id is None:
                    continue
                for day in daterange(first, last):
                    avail[type_id][day] -= 1
            elif res.room_type_id and res.room_type_id.is_roh:
                for day in daterange(first, last):
                    roh_unassigned[day] += 1
            elif res.room_type_id and res.room_type_id.id in avail:
                for day in daterange(first, last):
                    avail[res.room_type_id.id][day] -= 1

        for day, count in roh_unassigned.items():
            for _i in range(count):
                candidates = [t for t in avail if avail[t][day] > 0]
                if not candidates:
                    break
                fullest = max(candidates, key=lambda t: avail[t][day])
                avail[fullest][day] -= 1

        for type_id in avail:
            for day in nights:
                avail[type_id][day] = max(0, avail[type_id][day])
        return avail

    @api.model
    def free_for_stay(self, start, end, draft_holds=True):
        """{room_type_id: rooms free on EVERY night of the stay}."""
        per_night = self.compute(start, end, draft_holds=draft_holds)
        return {
            type_id: min(counts.values()) if counts else 0
            for type_id, counts in per_night.items()
        }
