# -*- coding: utf-8 -*-
import json
import time
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytz

from odoo.tests import tagged

from ..models import booking_quote
from ..models.booking_quote import BookingInputError
from .common import BookingEngineCase


@tagged('post_install', '-at_install')
class TestQuote(BookingEngineCase):

    def _offer(self, adults=2, children=0, nights=2):
        result = self.Quote.search_offers(
            self.start.isoformat(),
            (self.start + timedelta(days=nights)).isoformat(),
            adults, children)
        return next((o for o in result['offers']
                     if o['room_type_id'] == self.room_type.id), None)

    # ── pricing ───────────────────────────────────────────────────────
    def test_quote_equals_what_the_reservation_charges(self):
        """The whole point: the quoted total IS the reservation's total."""
        offer = self._offer()
        res = self._book(**self.Quote._reservation_vals(
            self.room_type, self.start, self.start + timedelta(days=2), 2, 0))
        self.assertEqual(offer['total'], res.total_amount)
        self.assertEqual(offer['total'], 3000000.0)
        self.assertEqual([n['price'] for n in offer['nightly']], [1500000.0] * 2)

    def test_zero_price_is_not_offered(self):
        self.room_type.base_rate = 0.0
        self.assertIsNone(self._offer())

    def test_party_over_capacity_needs_more_rooms(self):
        offer = self._offer(adults=3, children=1)
        self.assertEqual(offer['rooms_needed'], 2)
        self.assertEqual(offer['total'], 2 * offer['room_total'])

    def test_not_offered_when_too_few_rooms_left(self):
        self._book(state='confirmed')
        self._book(state='confirmed')
        self.assertIsNone(self._offer(adults=4))     # needs 2, 1 left
        self.assertIsNotNone(self._offer(adults=2))  # needs 1

    def test_only_left_shown_when_low(self):
        self.assertIsNone(self._offer()['only_left'])
        self._book(state='confirmed')
        self._book(state='confirmed')
        self.assertEqual(self._offer()['only_left'], 1)

    def test_hidden_types(self):
        self.room_type.website_bookable = False
        self.assertIsNone(self._offer())

    # ── input ─────────────────────────────────────────────────────────
    def _refuses(self, code, checkin, checkout, adults=2, children=0):
        with self.assertRaises(BookingInputError) as ctx:
            self.Quote.search_offers(checkin, checkout, adults, children)
        self.assertEqual(ctx.exception.code, code)

    def test_input_validation(self):
        today = self.Quote._hotel_today()
        d = lambda n: (today + timedelta(days=n)).isoformat()
        self._refuses('bad_dates', 'tomorrow', d(2))
        self._refuses('bad_dates', d(3), d(3))
        self._refuses('past_date', d(-1), d(1))
        self._refuses('too_far', d(600), d(601))
        self._refuses('too_long', d(1), d(40))
        self._refuses('bad_party', d(1), d(2), adults=0)
        self._refuses('bad_party', d(1), d(2), adults='x')
        self._refuses('bad_party', d(1), d(2), children=-1)

    def test_today_is_the_camps_today(self):
        """23:30 UTC is already tomorrow at the camp."""
        class LateUtc(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 10, 3, 23, 30, tzinfo=pytz.utc).astimezone(tz)

        with patch.object(booking_quote, 'datetime', LateUtc):
            self.assertEqual(self.Quote._hotel_today(), date(2026, 10, 4))

    # ── token ─────────────────────────────────────────────────────────
    def test_token_round_trip_and_tamper(self):
        offer = self._offer()
        payload = self.Quote.read_quote_token(offer['quote'])
        self.assertEqual(payload['total'], offer['total'])
        self.assertEqual(payload['room_type_id'], self.room_type.id)

        body, sig = offer['quote'].split('.', 1)
        forged = dict(payload, total=1)
        forged_body = json.dumps(forged, sort_keys=True, separators=(',', ':')).encode().hex()
        self.assertIsNone(self.Quote.read_quote_token('%s.%s' % (forged_body, sig)))
        self.assertIsNone(self.Quote.read_quote_token('garbage'))
        self.assertIsNone(self.Quote.read_quote_token(None))

    def test_token_expires(self):
        token = self.Quote.make_quote_token({'total': 1})
        with patch.object(booking_quote.time, 'time',
                          return_value=time.time() + booking_quote.QUOTE_TTL + 5):
            self.assertIsNone(self.Quote.read_quote_token(token))
