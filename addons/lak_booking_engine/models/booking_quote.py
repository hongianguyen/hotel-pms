# -*- coding: utf-8 -*-
"""What the website can sell for a stay, and at what price.

Prices are never computed here. Each offer is priced by building -- in memory,
never saved -- the very reservation the booking step will create, and reading
its ``total_amount``. That runs the PMS's own per-night rate logic, so the
price the guest is quoted is by construction the price the folio charges.

The signed quote token binds what was offered (type, dates, party, rooms,
total) with a short expiry. It is a convenience for the next step, never an
authority: the booking step must recompute availability and price itself and
refuse when they no longer match.
"""
import json
import math
import time
from datetime import date, datetime, timedelta

import pytz

from odoo import api, models
from odoo.tools.misc import consteq, hmac as odoo_hmac

HOTEL_TZ = 'Asia/Ho_Chi_Minh'
MAX_NIGHTS = 30
MAX_HORIZON_DAYS = 540           # how far ahead a stay may start
MAX_ADULTS = 20
MAX_CHILDREN = 10
MAX_ROOMS = 5                    # rooms of one type in one web booking
SHOW_LEFT_BELOW = 3              # "only N left" is shown under this, never the count
QUOTE_TTL = 30 * 60              # seconds a quote token stays valid
QUOTE_SCOPE = 'lak_booking_engine.quote'


class BookingInputError(ValueError):
    """A request the engine refuses, with a stable code for the page."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class LakBookingQuote(models.AbstractModel):
    _name = 'lak.booking.quote'
    _description = 'Website Booking Engine Quotes'

    # ── Input ──────────────────────────────────────────────────────────
    @api.model
    def _hotel_today(self):
        """Today at the camp. The public user has no tz, and UTC is 7 hours
        behind: between midnight and 07:00 it would still be yesterday."""
        return datetime.now(pytz.timezone(HOTEL_TZ)).date()

    @api.model
    def _parse_stay(self, checkin, checkout, adults, children):
        try:
            checkin = date.fromisoformat(str(checkin))
            checkout = date.fromisoformat(str(checkout))
        except (TypeError, ValueError):
            raise BookingInputError('bad_dates', 'Dates must be YYYY-MM-DD.')
        try:
            adults = int(adults)
            children = int(children or 0)
        except (TypeError, ValueError):
            raise BookingInputError('bad_party', 'Adults and children must be whole numbers.')

        today = self._hotel_today()
        nights = (checkout - checkin).days
        if checkin < today:
            raise BookingInputError('past_date', 'Check-in cannot be in the past.')
        if checkin > today + timedelta(days=MAX_HORIZON_DAYS):
            raise BookingInputError('too_far', 'Check-in is too far ahead.')
        if nights < 1:
            raise BookingInputError('bad_dates', 'Check-out must be after check-in.')
        if nights > MAX_NIGHTS:
            raise BookingInputError('too_long', 'Stays longer than %d nights: please contact us.' % MAX_NIGHTS)
        if not 1 <= adults <= MAX_ADULTS:
            raise BookingInputError('bad_party', 'Between 1 and %d adults.' % MAX_ADULTS)
        if not 0 <= children <= MAX_CHILDREN:
            raise BookingInputError('bad_party', 'Between 0 and %d children.' % MAX_CHILDREN)
        return checkin, checkout, nights, adults, children

    # ── Pricing ────────────────────────────────────────────────────────
    @api.model
    def _reservation_vals(self, room_type, checkin, checkout, adults, children):
        """Exactly the values the booking step will create a reservation
        with. Keep the two in step: a field set there and not here (a rate
        plan, a combo) would make the quote and the folio disagree."""
        return {
            'room_type_id': room_type.id,
            'checkin_date': checkin,
            'checkout_date': checkout,
            'adults': adults,
            'children': children,
            'state': 'draft',
        }

    @api.model
    def _price_stay(self, room_type, checkin, checkout, adults, children):
        """(nightly breakdown, total) for ONE room, or None when any night
        would price at zero or less -- a zero price is a broken price list,
        never a free room."""
        Reservation = self.env['hotel.reservation']
        res = Reservation.new(self._reservation_vals(
            room_type, checkin, checkout, adults, children))
        total = res.total_amount
        nightly = []
        current = checkin
        while current < checkout:
            rate = res.nightly_rate
            if res.rate_plan_id and not res.combo_id:
                rate = res.rate_plan_id.get_rate_for_date(current) or rate
            nightly.append({'date': current.isoformat(), 'price': rate})
            current += timedelta(days=1)
        if total <= 0 or any(n['price'] <= 0 for n in nightly):
            return None
        return nightly, total

    @api.model
    def _party_split(self, adults, children, rooms):
        """[(adults, children)] per room, as evenly as possible, with at least
        one adult in every room. None when there are fewer adults than rooms
        (children are not booked into a room on their own)."""
        if adults < rooms:
            return None
        split = []
        for i in range(rooms):
            a = adults // rooms + (1 if i < adults % rooms else 0)
            c = children // rooms + (1 if i < children % rooms else 0)
            split.append((a, c))
        return split

    # ── Quote token ────────────────────────────────────────────────────
    @api.model
    def _sign(self, payload):
        message = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        return odoo_hmac(self.env(su=True), QUOTE_SCOPE, message)

    @api.model
    def make_quote_token(self, payload):
        payload = dict(payload, exp=int(time.time()) + QUOTE_TTL)
        body = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        return '%s.%s' % (body.encode().hex(), self._sign(payload))

    @api.model
    def read_quote_token(self, token):
        """The payload of a genuine, unexpired token, else None."""
        try:
            body_hex, signature = (token or '').split('.', 1)
            payload = json.loads(bytes.fromhex(body_hex).decode())
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        if not consteq(self._sign(payload), signature):
            return None
        if int(payload.get('exp', 0)) < time.time():
            return None
        return payload

    # ── Search ─────────────────────────────────────────────────────────
    @api.model
    def search_offers(self, checkin, checkout, adults, children=0):
        """Everything the website may offer for this stay.

        Returns a dict ready to serialise. Only aggregates leave this method:
        no guest, booking or exact occupancy figure is ever exposed -- the
        remaining count is shown only when it is low, as the page's
        "only N left".
        """
        checkin, checkout, nights, adults, children = self._parse_stay(
            checkin, checkout, adults, children)
        guests = adults + children

        types = self.env['hotel.room.type'].search([
            ('active', '=', True),
            ('is_roh', '=', False),
            ('website_bookable', '=', True),
        ])
        free = self.env['hotel.availability'].free_for_stay(
            checkin, checkout, draft_holds=True)

        offers = []
        for room_type in types:
            capacity = room_type.capacity or 1
            rooms_needed = math.ceil(guests / capacity)
            left = free.get(room_type.id, 0)
            if rooms_needed > MAX_ROOMS or left < rooms_needed:
                continue
            # Price every room with the party it will really carry: the hold
            # creates exactly these rooms, and refuses when its saved total
            # differs from this one.
            split = self._party_split(adults, children, rooms_needed)
            if not split:
                continue
            priced = [self._price_stay(room_type, checkin, checkout, a, c)
                      for a, c in split]
            if not all(priced):
                continue
            nightly, room_total = priced[0]
            total = sum(p[1] for p in priced)
            token = self.make_quote_token({
                'room_type_id': room_type.id,
                'checkin': checkin.isoformat(),
                'checkout': checkout.isoformat(),
                'adults': adults,
                'children': children,
                'rooms': rooms_needed,
                'total': total,
            })
            offers.append({
                'room_type_id': room_type.id,
                'name': room_type.name,
                'description': room_type.description or '',
                **room_type.web_content(),
                'capacity': capacity,
                'rooms_needed': rooms_needed,
                'only_left': left if left < SHOW_LEFT_BELOW else None,
                'nightly': nightly,
                'room_total': room_total,
                'total': total,
                'quote': token,
            })
        offers.sort(key=lambda o: (o['total'], o['name']))
        return {
            'checkin': checkin.isoformat(),
            'checkout': checkout.isoformat(),
            'nights': nights,
            'adults': adults,
            'children': children,
            'currency': 'VND',
            'offers': offers,
        }
