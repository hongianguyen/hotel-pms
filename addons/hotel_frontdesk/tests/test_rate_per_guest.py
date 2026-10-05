# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRatePerGuest(TransactionCase):
    """Rates per pax per room-night: First Pax, Second Pax, Extra Adult,
    Extra Child (6-12), Extra Infant (0-6). Only adults fill the first two."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Start from a clean slate: no default plan from the database.
        cls.env['hotel.rate.plan'].search([('is_default', '=', True)]).write({'is_default': False})
        cls.room_type = cls.env['hotel.room.type'].create({
            'name': 'ZZ Rate Tent', 'max_adults': 3, 'max_children': 2, 'base_rate': 999.0})
        cls.room = cls.env['hotel.room'].create({'name': 'ZZR-01', 'room_type_id': cls.room_type.id})
        cls.plan = cls.env['hotel.rate.plan'].create({
            'name': 'ZZ Per Guest', 'pricing_mode': 'pax',
            'line_ids': [(0, 0, {
                'room_type_id': cls.room_type.id, 'first_pax': 1000.0, 'second_pax': 600.0,
                'extra_adult': 400.0, 'extra_child': 250.0, 'extra_infant': 50.0})],
        })
        cls.line = cls.plan.line_ids
        cls.guest = cls.env['res.partner'].create({'name': 'ZZ Rate Guest'})
        # A Monday, far from any real booking.
        start = date.today() + timedelta(days=500)
        cls.start = start - timedelta(days=start.weekday())

    def _book(self, adults=1, children=0, infants=0, nights=2, **extra):
        vals = {
            'guest_id': self.guest.id, 'room_type_id': self.room_type.id, 'room_id': self.room.id,
            'checkin_date': self.start, 'checkout_date': self.start + timedelta(days=nights),
            'adults': adults, 'children': children, 'infants': infants,
            'rate_plan_id': self.plan.id, 'send_confirmation': False,
        }
        vals.update(extra)
        return self.env['hotel.reservation'].create(vals)

    # ── the brackets ───────────────────────────────────────────────────
    def test_brackets(self):
        price = self.line.price_for
        self.assertEqual(price(1), 1000)
        self.assertEqual(price(2), 1600)
        self.assertEqual(price(3), 2000)                 # + extra adult
        self.assertEqual(price(2, 1), 1850)              # + extra child
        self.assertEqual(price(2, 0, 1), 1650)           # + extra infant
        self.assertEqual(price(3, 2, 1), 2550)

    def test_only_adults_fill_first_and_second_pax(self):
        """1 adult + 1 child pays First Pax + Extra Child, not Second Pax."""
        self.assertEqual(self.line.price_for(1, 1), 1250)
        self.assertEqual(self.line.price_for(1, 0, 1), 1050)

    # ── on a booking ───────────────────────────────────────────────────
    def test_booking_total_and_nightly_rate(self):
        res = self._book(adults=2, children=1, nights=3)
        self.assertEqual(res.nightly_rate, 1850)
        self.assertEqual(res.total_amount, 3 * 1850)

    def test_changing_the_party_reprices(self):
        res = self._book(adults=2)
        self.assertEqual(res.total_amount, 3200)
        res.write({'children': 1, 'infants': 1})
        self.assertEqual(res.total_amount, 2 * 1900)
        self.line.extra_infant = 100.0
        self.assertEqual(res.total_amount, 2 * 1950)

    def test_folio_charges_what_was_quoted(self):
        res = self._book(adults=2, children=1)
        res.action_confirm()
        res.folio_id._generate_room_charges(res)
        room_lines = res.folio_id.line_ids.filtered(lambda l: l.charge_type == 'room')
        self.assertEqual(room_lines.mapped('amount'), [1850.0, 1850.0])
        self.assertEqual(sum(room_lines.mapped('subtotal')), res.total_amount)

    def test_plan_rules_still_apply(self):
        """Weekdays the plan does not run fall back to the nightly rate."""
        self.plan.day_tuesday = False                  # night 2 of a Monday stay
        res = self._book(adults=1)
        self.assertEqual(res._rate_on(self.start), 1000)
        self.assertEqual(res._rate_on(self.start + timedelta(days=1)), res.nightly_rate)

    def test_room_type_without_a_row_falls_back(self):
        other = self.env['hotel.room.type'].create({
            'name': 'ZZ Rate Other', 'max_adults': 2, 'max_children': 0, 'base_rate': 777.0})
        room = self.env['hotel.room'].create({'name': 'ZZR-02', 'room_type_id': other.id})
        res = self._book(room_type_id=other.id, room_id=room.id)
        self.assertEqual(res.total_amount, 2 * 777)

    def test_flat_plans_are_unchanged(self):
        flat = self.env['hotel.rate.plan'].create({
            'name': 'ZZ Old PMS agreed', 'base_rate': 1720000.0})
        self.assertEqual(flat.pricing_mode, 'room')
        res = self._book(adults=2, children=1, rate_plan_id=flat.id)
        self.assertEqual(res.total_amount, 2 * 1720000)

    # ── default plan ───────────────────────────────────────────────────
    def test_default_plan_prices_new_bookings(self):
        self.plan.is_default = True
        res = self._book(adults=2, rate_plan_id=False)
        self.assertEqual(res.rate_plan_id, self.plan)
        self.assertEqual(res.total_amount, 3200)

    def test_default_plan_skipped_on_request(self):
        self.plan.is_default = True
        res = self.env['hotel.reservation'].with_context(hotel_no_default_rate_plan=True).create({
            'guest_id': self.guest.id, 'room_type_id': self.room_type.id, 'room_id': self.room.id,
            'checkin_date': self.start, 'checkout_date': self.start + timedelta(days=1),
            'send_confirmation': False})
        self.assertFalse(res.rate_plan_id)

    def test_only_one_default(self):
        self.plan.is_default = True
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.plan'].create({'name': 'ZZ Second Default', 'is_default': True})

    def test_rates_cannot_be_negative(self):
        with self.assertRaises(ValidationError):
            self.line.extra_child = -1
