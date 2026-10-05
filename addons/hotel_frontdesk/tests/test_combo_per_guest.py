# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestComboPerGuest(TransactionCase):
    """Per-guest packages: room part by the 5 brackets a night, services part
    per adult by group size + per child + per infant once per stay, included
    services scheduled on their Day at 0; account type and validity dates."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Type = cls.env['hotel.account.type']
        cls.t_agent = Type.by_code('travel_agent')
        cls.room_type = cls.env['hotel.room.type'].create({
            'name': 'ZZ Pkg Tent', 'max_adults': 6, 'max_children': 4, 'base_rate': 1.0})
        cls.room = cls.env['hotel.room'].create({'name': 'ZZK-01', 'room_type_id': cls.room_type.id})
        cls.guest = cls.env['res.partner'].create({'name': 'ZZ Pkg Guest'})
        Service = cls.env['hotel.service']
        cls.dinner = Service.create({'name': 'ZZ Dinner Set', 'price': 150000.0, 'category': 'fnb'})
        cls.tour = Service.create({'name': 'ZZ Waterfall Tour', 'price': 350000.0, 'category': 'tour'})
        cls.breakfast = Service.create({'name': 'ZZ Breakfast', 'price': 80000.0, 'category': 'fnb'})
        cls.combo = cls.env['hotel.combo'].create({
            'name': 'ZZ Package 3D2N', 'pricing': 'per_guest', 'room_type_id': cls.room_type.id,
            'nights': 2, 'nightly_rate': 0.0,
            'room_first_pax': 1000000.0, 'room_second_pax': 600000.0,
            'room_extra_adult': 400000.0, 'room_extra_child': 300000.0, 'room_extra_infant': 0.0,
            'price_adult_1': 1500000.0, 'price_adult_2': 1200000.0, 'price_adult_3_5': 1000000.0,
            'price_adult_6_9': 900000.0, 'price_adult_10': 800000.0,
            'price_child': 600000.0, 'price_infant': 0.0,
            'line_ids': [(0, 0, {'service_id': cls.dinner.id, 'day': 1, 'price_unit': 1.0}),
                         (0, 0, {'service_id': cls.tour.id, 'day': 2, 'price_unit': 1.0}),
                         (0, 0, {'service_id': cls.breakfast.id, 'day': 3, 'price_unit': 1.0})],
        })
        cls.start = date.today() + timedelta(days=560)

    def _book(self, adults=2, children=0, infants=0, **extra):
        vals = {'guest_id': self.guest.id, 'room_type_id': self.room_type.id,
                'room_id': self.room.id, 'combo_id': self.combo.id,
                'checkin_date': self.start, 'checkout_date': self.start + timedelta(days=2),
                'adults': adults, 'children': children, 'infants': infants,
                'send_confirmation': False}
        vals.update(extra)
        return self.env['hotel.reservation'].create(vals)

    def test_owners_example(self):
        """2 adults + 1 child, 2 nights: 3,800,000 room + 3,000,000 services."""
        res = self._book(adults=2, children=1)
        self.assertEqual(res.nightly_rate, 1900000.0)
        price_line = res.service_line_ids.filtered('is_package_price')
        self.assertEqual(price_line.price_unit, 3000000.0)
        self.assertIn('2 adult(s) × 1,200,000', price_line.note)
        self.assertEqual(res.total_amount, 6800000.0)

    def test_schedule_on_package_days_at_zero(self):
        res = self._book()
        schedule = res.service_line_ids.filtered('combo_line_id')
        self.assertEqual(schedule.mapped('price_unit'), [0.0, 0.0, 0.0])
        self.assertEqual({l.service_id: l.date for l in schedule}, {
            self.dinner: self.start, self.tour: self.start + timedelta(days=1),
            self.breakfast: self.start + timedelta(days=2)})

    def test_adult_group_size_brackets(self):
        price = self.combo.adult_price_for
        self.assertEqual([price(n) for n in (1, 2, 3, 5, 6, 9, 10, 15)],
                         [1500000, 1200000, 1000000, 1000000, 900000, 900000, 800000, 800000])

    def test_changing_the_party_reprices_room_and_services(self):
        res = self._book(adults=2)
        self.assertEqual(res.total_amount, 2 * 1600000 + 2 * 1200000)
        res.write({'adults': 3, 'infants': 1})
        price_line = res.service_line_ids.filtered('is_package_price')
        self.assertEqual(price_line.price_unit, 3 * 1000000)       # 3-5 bracket
        self.assertEqual(res.nightly_rate, 2000000.0)
        self.assertEqual(res.total_amount, 2 * 2000000 + 3000000)

    def test_moving_check_in_moves_the_schedule(self):
        res = self._book()
        later = self.start + timedelta(days=7)
        res.write({'checkin_date': later, 'checkout_date': later + timedelta(days=2)})
        tour_line = res.service_line_ids.filtered(lambda l: l.service_id == self.tour)
        self.assertEqual(tour_line.date, later + timedelta(days=1))

    def test_folio_charges_what_was_quoted(self):
        res = self._book(adults=2, children=1, checkin_date=date.today(),
                         checkout_date=date.today() + timedelta(days=2))
        quoted = res.total_amount
        res.action_confirm()
        res.action_check_in()
        self.assertEqual(res.folio_id.total_amount, quoted)

    def test_account_type_and_validity(self):
        self.combo.account_type_id = self.t_agent
        with self.assertRaisesRegex(ValidationError, 'Travel Agent bookings only'):
            self._book()
        self.combo.write({'account_type_id': False,
                          'date_from': self.start + timedelta(days=1)})
        with self.assertRaisesRegex(ValidationError, 'only sold for check-ins'):
            self._book()

    def test_service_day_must_fit_the_package(self):
        with self.assertRaises(ValidationError):
            self.combo.line_ids[0].day = 4                  # 2 nights = days 1-3
        with self.assertRaises(ValidationError):
            self.combo.line_ids[0].day = 0

    def test_fixed_packages_price_as_before(self):
        fixed = self.env['hotel.combo'].create({
            'name': 'ZZ Fixed', 'pricing': 'fixed', 'room_type_id': self.room_type.id,
            'nights': 2, 'nightly_rate': 700000.0,
            'line_ids': [(0, 0, {'service_id': self.tour.id, 'price_unit': 350000.0})]})
        res = self._book(adults=3, children=1, combo_id=fixed.id)
        self.assertEqual(res.nightly_rate, 700000.0)
        self.assertFalse(res.service_line_ids.filtered('is_package_price'))
        self.assertEqual(res.total_amount, 2 * 700000 + 350000)
