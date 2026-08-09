# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from psycopg2 import IntegrityError
from odoo.tools import mute_logger

from .common import HotelCommon


@tagged('post_install', '-at_install')
class TestReservationLifecycle(HotelCommon):

    def setUp(self):
        super().setUp()
        self.today = fields.Date.context_today(self.env['hotel.reservation'])
        self.tomorrow = self.today + timedelta(days=1)

    # ── The happy path ───────────────────────────────────────────────────────

    def test_full_lifecycle_draft_to_invoice(self):
        """draft → confirmed → checked_in → checked_out, folio and invoice."""
        res = self._make_reservation(self.today, self.today + timedelta(days=3))

        # New bookings are unconfirmed (confirmed with the user, 11 Jul 2026)
        self.assertEqual(res.state, 'draft')
        self.assertEqual(res.nights, 3)
        self.assertTrue(res.reservation_number.startswith('RES'))

        res.action_confirm()
        self.assertEqual(res.state, 'confirmed')

        res.action_check_in()
        self.assertEqual(res.state, 'checked_in')
        self.assertEqual(res.room_id.status, 'occupied')
        self.assertTrue(res.folio_id, 'check-in must open a folio')

        # One room charge per night, at the room's rate
        room_lines = res.folio_id.line_ids.filtered(
            lambda line: line.charge_type == 'room')
        self.assertEqual(len(room_lines), 3)
        self.assertAlmostEqual(res.folio_id.total_amount, 3 * 1000000.0, places=2)

        res.action_check_out()
        self.assertEqual(res.state, 'checked_out')
        self.assertEqual(res.room_id.status, 'dirty',
                         'check-out must hand the room to housekeeping')
        self.assertTrue(res.folio_id.invoice_id, 'check-out must raise an invoice')
        self.assertEqual(res.folio_id.payment_state, 'invoiced')
        self.assertEqual(res.folio_id.invoice_id.partner_id, self.guest)

    # ── The guards ───────────────────────────────────────────────────────────

    def test_no_check_in_before_arrival_date(self):
        """Guarding against early check-in (added 12 Jul 2026)."""
        res = self._make_reservation(self.tomorrow, self.tomorrow + timedelta(days=2))
        res.action_confirm()
        with self.assertRaises(UserError):
            res.action_check_in()

    def test_confirm_requires_a_room(self):
        res = self._make_reservation(self.today, self.tomorrow)
        res.room_id = False
        with self.assertRaises(UserError):
            res.action_confirm()

    def test_cannot_check_in_from_draft(self):
        res = self._make_reservation(self.today, self.tomorrow)
        with self.assertRaises(UserError):
            res.action_check_in()

    def test_cannot_cancel_a_checked_in_stay(self):
        """Cancelling in-house would leave folio charges dangling."""
        res = self._make_reservation(self.today, self.today + timedelta(days=2))
        res.action_confirm()
        res.action_check_in()
        with self.assertRaises(UserError):
            res.action_cancel()

    def test_double_booking_is_refused(self):
        """Two confirmed reservations cannot overlap on one room."""
        first = self._make_reservation(self.today, self.today + timedelta(days=4))
        first.action_confirm()

        second = self._make_reservation(
            self.today + timedelta(days=1), self.today + timedelta(days=2))
        with self.assertRaises(Exception):
            second.action_confirm()

    @mute_logger('odoo.sql_db')
    def test_checkout_must_follow_checkin(self):
        """DB-level CHECK constraint, not just a Python guard."""
        with self.assertRaises(IntegrityError):
            with self.cr.savepoint():
                self._make_reservation(self.today + timedelta(days=3), self.today)

    # ── Money ────────────────────────────────────────────────────────────────

    def test_late_checkout_is_charged(self):
        """A stay checked out after its scheduled date accrues extra nights."""
        res = self._make_reservation(
            self.today - timedelta(days=3), self.today - timedelta(days=1))
        res.action_confirm()
        res.action_check_in()

        nights_before = len(res.folio_id.line_ids.filtered(
            lambda line: line.charge_type == 'room'))
        res.action_check_out()
        nights_after = len(res.folio_id.line_ids.filtered(
            lambda line: line.charge_type == 'room'))

        self.assertEqual(nights_after, nights_before + 1,
                         'one late-checkout night should have been charged')

    def test_partner_stay_statistics(self):
        """Covers the _read_group aggregation on res.partner.

        This is the call that read_group deprecation would break, and it runs
        on every guest form open.
        """
        res = self._make_reservation(
            self.today - timedelta(days=2), self.today - timedelta(days=1))
        res.action_confirm()
        res.action_check_in()
        res.action_check_out()

        self.guest.invalidate_recordset(['hotel_total_stays', 'hotel_total_spent'])
        self.assertEqual(self.guest.hotel_total_stays, 1)
        self.assertGreater(self.guest.hotel_total_spent, 0.0)
