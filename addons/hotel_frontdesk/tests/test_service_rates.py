# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestServiceRates(TransactionCase):
    """Service rates by account type and validity, priced per group or per
    pax by group size (1, 2, 3-5, 6-9, 10+)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Type = cls.env['hotel.account.type']
        cls.t_direct, cls.t_agent = Type.direct(), Type.by_code('travel_agent')
        cls.tour = cls.env['hotel.service'].create({
            'name': 'ZZ Waterfall Tour', 'price': 350000.0, 'category': 'tour'})
        cls.per_pax = cls.env['hotel.service.rate'].create({
            'service_id': cls.tour.id, 'pricing': 'pax',
            'price_pax_1': 1000.0, 'price_pax_2': 800.0, 'price_pax_3_5': 600.0,
            'price_pax_6_9': 500.0, 'price_pax_10': 400.0})
        room_type = cls.env['hotel.room.type'].create({
            'name': 'ZZ Svc Tent', 'max_adults': 6, 'max_children': 4, 'base_rate': 1.0})
        cls.room = cls.env['hotel.room'].create({'name': 'ZZS-01', 'room_type_id': room_type.id})
        cls.guest = cls.env['res.partner'].create({'name': 'ZZ Svc Guest'})
        cls.agent = cls.env['res.partner'].create({
            'name': 'ZZ Svc Agent', 'is_company': True, 'is_hotel_agency': True,
            'hotel_account_type_id': cls.t_agent.id, 'hotel_credit_term': True})
        start = date.today() + timedelta(days=540)
        cls.monday = start - timedelta(days=start.weekday())
        cls.room_type = room_type

    def _booking(self, **extra):
        vals = {'guest_id': self.guest.id, 'room_type_id': self.room_type.id,
                'room_id': self.room.id, 'checkin_date': self.monday,
                'checkout_date': self.monday + timedelta(days=2), 'adults': 2,
                'send_confirmation': False}
        vals.update(extra)
        return self.env['hotel.reservation'].create(vals)

    def _line(self, res, pax, **extra):
        return self.env['hotel.reservation.service'].create(dict(
            {'reservation_id': res.id, 'service_id': self.tour.id, 'pax': pax}, **extra))

    # ── pricing ─────────────────────────────────────────────────────────
    def test_per_pax_brackets(self):
        price = self.per_pax.price_for
        self.assertEqual([price(n) for n in (1, 2, 3, 5, 6, 9, 10, 12)],
                         [1000, 1600, 1800, 3000, 3000, 4500, 4000, 4800])

    def test_per_group(self):
        self.per_pax.write({'pricing': 'group', 'price_group': 2500.0})
        self.assertEqual(self.per_pax.price_for(1), 2500)
        self.assertEqual(self.per_pax.price_for(8), 2500)

    def test_booked_line_takes_the_rate(self):
        line = self._line(self._booking(), pax=4, quantity=2)
        self.assertEqual(line.rate_id, self.per_pax)
        self.assertEqual(line.price_unit, 2400.0)          # 4 x 600
        self.assertEqual(line.subtotal, 4800.0)            # twice

    def test_list_price_when_no_rate_matches(self):
        self.per_pax.date_to = self.monday - timedelta(days=1)
        line = self._line(self._booking(), pax=3)
        self.assertFalse(line.rate_id)
        self.assertEqual(line.price_unit, 350000.0)

    def test_a_given_price_is_kept(self):
        line = self._line(self._booking(), pax=3, price_unit=99.0)
        self.assertEqual(line.price_unit, 99.0)

    # ── account type ────────────────────────────────────────────────────
    def test_own_account_type_beats_all_accounts(self):
        agent_rate = self.env['hotel.service.rate'].create({
            'service_id': self.tour.id, 'account_type_id': self.t_agent.id,
            'pricing': 'group', 'price_group': 1500.0})
        agency_res = self._booking(agency_id=self.agent.id, booker_id=self.agent.id)
        line = self._line(agency_res, pax=4)
        self.assertEqual((line.rate_id, line.price_unit), (agent_rate, 1500.0))
        direct = self._line(self._booking(), pax=4)
        self.assertEqual(direct.rate_id, self.per_pax, 'the agent rate is not for direct guests')

    # ── validity ────────────────────────────────────────────────────────
    def test_dates_and_weekdays(self):
        weekend = self.env['hotel.service.rate'].create({
            'service_id': self.tour.id, 'pricing': 'group', 'price_group': 9000.0,
            'date_from': self.monday, 'date_to': self.monday + timedelta(days=30),
            'day_monday': False, 'day_tuesday': False, 'day_wednesday': False,
            'day_thursday': False, 'day_friday': False})
        res = self._booking()
        saturday = self.monday + timedelta(days=5)
        self.assertEqual(self._line(res, 2, date=saturday).rate_id, weekend,
                         'the dated rate is the more specific season')
        self.assertEqual(self._line(res, 2, date=self.monday).rate_id, self.per_pax)
        self.assertEqual(self._line(res, 2, date=self.monday + timedelta(days=40)).rate_id,
                         self.per_pax, 'past its Valid To')

    def test_archived_rates_are_ignored(self):
        self.per_pax.active = False
        self.assertFalse(self._line(self._booking(), pax=2).rate_id)

    def test_rules(self):
        with self.assertRaises(ValidationError):
            self.per_pax.price_pax_2 = -1
        with self.assertRaises(ValidationError):
            self.per_pax.write({'date_from': self.monday, 'date_to': self.monday - timedelta(days=1)})
