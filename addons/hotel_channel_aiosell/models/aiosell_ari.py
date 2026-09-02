# -*- coding: utf-8 -*-
"""Building the ARI (availability / rates / inventory) payloads.

Two things drive the shape of this file.

**Cost.** The obvious implementation — call ``hotel.room.get_available_rooms``
once per day per room type — is one query per day per type, so a year's horizon
against 23 rooms and an 18,900-row reservation table is thousands of queries
per push. Instead everything is read once and the per-night counts are built in
memory.

**Payload size.** Aiosell caps updates at 30 per second and its payload is
range-shaped (``startDate``/``endDate``). Pushing 365 single-day blocks would
be both slow and wasteful, so consecutive nights whose numbers are identical
are collapsed into one block. A property that changes little sends a handful
of blocks instead of hundreds.
"""
import logging
from datetime import timedelta

from odoo import _, fields, models

_logger = logging.getLogger(__name__)

# Reservation states that take a room out of the sellable pool. 'draft' is
# added on top of these when the connection says draft holds inventory.
BLOCKING_STATES = ('confirmed', 'checked_in')


def _daterange(start, end):
    """Nights from start up to but not including end."""
    current = start
    while current < end:
        yield current
        current += timedelta(days=1)


def _collapse(per_date, key_fn):
    """Merge consecutive dates carrying identical values into blocks.

    ``per_date`` maps date -> payload fragment. Returns a list of
    ``(start_date, end_date, fragment)`` with both ends inclusive, which is
    the convention Aiosell uses.
    """
    blocks = []
    for day in sorted(per_date):
        fragment = per_date[day]
        if not fragment:
            continue
        signature = key_fn(fragment)
        if blocks and blocks[-1][3] == signature and blocks[-1][1] + timedelta(days=1) == day:
            blocks[-1][1] = day
        else:
            blocks.append([day, day, fragment, signature])
    return [(b[0], b[1], b[2]) for b in blocks]


class AiosellConfig(models.Model):
    _inherit = 'aiosell.config'

    # ── Availability ────────────────────────────────────────────────────
    def _blocking_states(self):
        self.ensure_one()
        states = list(BLOCKING_STATES)
        if self.draft_holds_inventory:
            states.append('draft')
        return states

    def _compute_availability(self, start, end):
        """Sellable rooms per room type per night, as {room_type_id: {date: n}}.

        Counted from the physical rooms, because that is what can actually be
        slept in:

        * a room is out on a night if it is flagged for maintenance covering
          that night;
        * a reservation with a room assigned takes that specific room out;
        * a reservation without a room yet still has to be honoured, so it is
          subtracted from its room type's count;
        * a Run-of-House booking with no room yet could land on any physical
          type, so it is subtracted from whichever type has the most left that
          night — the conservative reading.

        ROH types are virtual: they overlap the physical types rather than
        adding to them, so they never appear in the result and are never
        pushed. Publishing both would sell the same bed twice.
        """
        self.ensure_one()
        Room = self.env['hotel.room']
        rooms = Room.search([
            ('active', '=', True),
            ('room_type_id.is_roh', '=', False),
        ])
        nights = list(_daterange(start, end))
        avail = {rt: {d: 0 for d in nights} for rt in rooms.mapped('room_type_id').ids}
        room_type_of = {}

        for room in rooms:
            room_type_of[room.id] = room.room_type_id.id
            for day in nights:
                if room._aiosell_out_of_service(day):
                    continue
                avail[room.room_type_id.id][day] += 1

        reservations = self.env['hotel.reservation'].search([
            ('state', 'in', self._blocking_states()),
            ('checkin_date', '<', end),
            ('checkout_date', '>', start),
        ])
        roh_unassigned = {d: 0 for d in nights}
        for res in reservations:
            first = max(res.checkin_date, start)
            last = min(res.checkout_date, end)
            if res.room_id:
                # A specific room is held; it was already counted as free above.
                type_id = room_type_of.get(res.room_id.id)
                if type_id is None:
                    continue
                for day in _daterange(first, last):
                    avail[type_id][day] -= 1
            elif res.room_type_id and res.room_type_id.is_roh:
                for day in _daterange(first, last):
                    roh_unassigned[day] += 1
            elif res.room_type_id and res.room_type_id.id in avail:
                for day in _daterange(first, last):
                    avail[res.room_type_id.id][day] -= 1

        # Unassigned ROH rooms have to come out of somewhere. Take them from
        # the roomiest type each night so no single type is driven negative
        # while another sits full.
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

    def _build_inventory_updates(self, start, end):
        """Aiosell inventory blocks for the mapped room types."""
        self.ensure_one()
        mappings = self.room_mapping_ids.filtered(
            lambda m: m.active and m.room_code and m.room_type_id
        )
        if not mappings:
            return []
        avail = self._compute_availability(start, end)
        per_date = {}
        for day in _daterange(start, end):
            rooms = []
            for mapping in mappings:
                # A mapped type with no sellable rooms must be pushed as 0,
                # not omitted: these updates are upserts, so leaving the code
                # out of the payload leaves Aiosell selling whatever it last
                # heard, forever.
                counts = avail.get(mapping.room_type_id.id) or {}
                rooms.append({
                    'roomCode': mapping.room_code,
                    'available': counts.get(day, 0),
                })
            if rooms:
                per_date[day] = rooms

        return [
            {
                'startDate': fields.Date.to_string(block_start),
                'endDate': fields.Date.to_string(block_end),
                'rooms': rooms,
            }
            for block_start, block_end, rooms in _collapse(
                per_date,
                lambda rooms: tuple(sorted((r['roomCode'], r['available']) for r in rooms)),
            )
        ]

    # ── Rates ───────────────────────────────────────────────────────────
    def _build_rate_updates(self, start, end):
        """Aiosell rate blocks at the (room, rateplan, date) grain.

        A rate plan that does not apply on a date — out of season, wrong
        weekday, stop-sell — yields no entry for that date. It must never be
        pushed as 0, which reads on the OTA as a free room.
        """
        self.ensure_one()
        mappings = self.rate_mapping_ids.filtered(
            lambda m: m.active and m.rateplan_code and m.rate_plan_id and m.room_type_id
        )
        if not mappings:
            return []

        per_date = {}
        for day in _daterange(start, end):
            rates = []
            for mapping in mappings:
                rate = mapping._rate_for_date(day)
                if not rate:
                    continue
                rates.append({
                    'roomCode': mapping.room_code,
                    'rateplanCode': mapping.rateplan_code,
                    'rate': rate,
                })
            if rates:
                per_date[day] = rates

        return [
            {
                'startDate': fields.Date.to_string(block_start),
                'endDate': fields.Date.to_string(block_end),
                'rates': rates,
            }
            for block_start, block_end, rates in _collapse(
                per_date,
                lambda rates: tuple(sorted(
                    (r['roomCode'], r['rateplanCode'], r['rate']) for r in rates
                )),
            )
        ]

    # ── Restrictions ────────────────────────────────────────────────────
    def _build_restriction_updates(self, start, end):
        """Room-level stop-sell / minimum stay, derived from the rate plans.

        A room type is stop-sold on a night when every rate plan mapped to it
        is closed that night; the minimum stay is the loosest one still open.
        """
        self.ensure_one()
        mappings = self.rate_mapping_ids.filtered(
            lambda m: m.active and m.rate_plan_id and m.room_type_id
        )
        if not mappings:
            return []

        by_room_code = {}
        for mapping in mappings:
            by_room_code.setdefault(mapping.room_code, self.env['aiosell.rateplan.mapping'])
            by_room_code[mapping.room_code] |= mapping

        per_date = {}
        for day in _daterange(start, end):
            rooms = []
            for room_code, group in by_room_code.items():
                open_plans = [m for m in group if m._rate_for_date(day)]
                min_stay = min(
                    (m.rate_plan_id.min_stay or 1 for m in open_plans), default=1,
                )
                rooms.append({
                    'roomCode': room_code,
                    'restrictions': {
                        'stopSell': not open_plans,
                        'minimumStay': min_stay,
                        'closeOnArrival': False,
                        'closeOnDeparture': False,
                        'maximumStay': None,
                        'minimumStayArrival': None,
                        'maximumStayArrival': None,
                        'exactStayArrival': None,
                        'minimumAdvanceReservation': None,
                        'maximumAdvanceReservation': None,
                    },
                })
            if rooms:
                per_date[day] = rooms

        return [
            {
                'startDate': fields.Date.to_string(block_start),
                'endDate': fields.Date.to_string(block_end),
                'rooms': rooms,
            }
            for block_start, block_end, rooms in _collapse(
                per_date,
                lambda rooms: tuple(sorted(
                    (r['roomCode'], r['restrictions']['stopSell'],
                     r['restrictions']['minimumStay']) for r in rooms
                )),
            )
        ]

    # ── Orchestration ───────────────────────────────────────────────────
    def _warn_nothing_to_push(self, operation, message):
        """Leave a visible trace when a push that was asked for sends nothing."""
        self.ensure_one()
        _logger.warning('Aiosell %s: %s', self.display_name, message)
        self._write_sync_log({
            'direction': 'outbound',
            'operation': operation,
            'state': 'refused',
            'note': message[:500],
        })

    def _push_ari(self):
        """Push everything this connection is configured to send."""
        self.ensure_one()
        start, end = self._horizon()
        parts = []

        if self.sync_availability:
            updates = self._build_inventory_updates(start, end)
            self.push_inventory(updates)
            parts.append(_('%s availability block(s)') % len(updates))
        if self.sync_rates:
            updates = self._build_rate_updates(start, end)
            if not updates:
                # Silence here is dangerous: availability keeps flowing while
                # the OTAs sell at whatever price they last heard. The usual
                # cause is that "Import Mapping" could not match Aiosell's
                # plan names to the local ones and nobody paired them up.
                self._warn_nothing_to_push('rate_push', _(
                    'Rates are switched on but no rate plan mapping produced '
                    'a price, so nothing was sent and the channels are still '
                    'selling at the last price they were given. Pair the '
                    'Aiosell rate plan codes with PMS rate plans under '
                    'Aiosell → Rate Plan Mapping.'))
            self.push_rates(updates)
            parts.append(_('%s rate block(s)') % len(updates))
        if self.sync_restrictions:
            updates = self._build_restriction_updates(start, end)
            self.push_restrictions(updates)
            parts.append(_('%s restriction block(s)') % len(updates))

        self.last_push_date = fields.Datetime.now()
        return _('Sent %s.') % ', '.join(parts) if parts else _('Nothing to sync.')
