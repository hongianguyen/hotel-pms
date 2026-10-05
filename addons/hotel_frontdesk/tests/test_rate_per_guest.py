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

    # ── manual rate ────────────────────────────────────────────────────
    def test_manual_rate_overrides_everything(self):
        res = self._book(adults=2, children=1, nights=3)
        self.assertEqual(res.total_amount, 3 * 1850)
        res.write({'manual_rate': True, 'manual_nightly_rate': 1234.0})
        self.assertEqual(res.nightly_rate, 1234.0)
        self.assertEqual(res.total_amount, 3 * 1234.0)
        self.assertEqual(res._rate_on(self.start + timedelta(days=1)), 1234.0)
        res.manual_rate = False
        self.assertEqual(res.total_amount, 3 * 1850, 'unticking restores the plan price')

    def test_manual_rate_can_be_complimentary_but_not_negative(self):
        res = self._book(adults=1, manual_rate=True, manual_nightly_rate=0.0)
        self.assertEqual(res.total_amount, 0.0)
        with self.assertRaises(ValidationError):
            res.manual_nightly_rate = -5

    def test_amending_an_in_house_stay_reposts_room_charges(self):
        res = self._book(adults=2, checkin_date=date.today(),
                         checkout_date=date.today() + timedelta(days=2))
        res.action_confirm()
        res.action_check_in()
        room_lines = lambda: res.folio_id.line_ids.filtered(lambda l: l.charge_type == 'room')
        self.assertEqual(sum(room_lines().mapped('subtotal')), 2 * 1600)
        res.write({'manual_rate': True, 'manual_nightly_rate': 900.0})
        self.assertEqual(room_lines().mapped('amount'), [900.0, 900.0])
        res.write({'manual_rate': False})
        res.children = 1                    # the party changes in house
        self.assertEqual(sum(room_lines().mapped('subtotal')), 2 * 1850)


@tagged('post_install', '-at_install')
class TestRatePlanAccountType(TransactionCase):
    """A rate plan can be limited to one account type: Direct Guest, OTA,
    Travel Agent or Corporate. A booking's type comes from its agency."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Plan = cls.env['hotel.rate.plan']
        Plan.search([('is_default', '=', True)]).write({'is_default': False})
        cls.room_type = cls.env['hotel.room.type'].create({
            'name': 'ZZ Acct Tent', 'max_adults': 2, 'max_children': 1, 'base_rate': 500.0})
        cls.room = cls.env['hotel.room'].create({'name': 'ZZA-01', 'room_type_id': cls.room_type.id})
        cls.guest = cls.env['res.partner'].create({'name': 'ZZ Acct Guest'})
        Type = cls.env['hotel.account.type']
        cls.t_direct, cls.t_ota = Type.direct(), Type.by_code('ota')
        cls.t_agent, cls.t_corp = Type.by_code('travel_agent'), Type.by_code('corporate')
        Partner = cls.env['res.partner']
        cls.ota = Partner.create({'name': 'ZZ OTA', 'is_company': True, 'is_hotel_agency': True,
                                  'hotel_account_type_id': cls.t_ota.id, 'hotel_credit_term': True})
        cls.agent = Partner.create({'name': 'ZZ Agent', 'is_company': True, 'is_hotel_agency': True,
                                    'hotel_account_type_id': cls.t_agent.id, 'hotel_credit_term': True})

        def plan(name, account_type, first, default=False):
            return Plan.create({
                'name': name, 'pricing_mode': 'pax',
                'account_type_id': account_type.id if account_type else False,
                'is_default': default,
                'line_ids': [(0, 0, {'room_type_id': cls.room_type.id, 'first_pax': first})]})
        cls.plan_direct = plan('ZZ Direct', cls.t_direct, 1000.0, True)
        cls.plan_ota = plan('ZZ OTA Rate', cls.t_ota, 1100.0, True)
        cls.plan_agent = plan('ZZ Agent Rate', cls.t_agent, 800.0, True)
        cls.plan_any = plan('ZZ Any', None, 900.0)
        start = date.today() + timedelta(days=520)
        cls.vals = {
            'guest_id': cls.guest.id, 'room_type_id': cls.room_type.id, 'room_id': cls.room.id,
            'checkin_date': start, 'checkout_date': start + timedelta(days=1),
            'send_confirmation': False,
        }

    def _book(self, **extra):
        return self.env['hotel.reservation'].create(dict(self.vals, **extra))

    def test_account_type_comes_from_the_agency(self):
        self.assertEqual(self._book().account_type_id, self.t_direct)
        self.assertEqual(self._book(agency_id=self.ota.id, booker_id=self.ota.id).account_type_id,
                         self.t_ota)
        self.assertEqual(self._book(agency_id=self.agent.id, booker_id=self.agent.id).account_type_id,
                         self.t_agent)

    def test_each_account_type_gets_its_own_default(self):
        self.assertEqual(self._book().rate_plan_id, self.plan_direct)
        self.assertEqual(self._book(agency_id=self.agent.id, booker_id=self.agent.id).rate_plan_id,
                         self.plan_agent)
        res = self._book(agency_id=self.ota.id, booker_id=self.ota.id)
        self.assertEqual(res.rate_plan_id, self.plan_ota)
        self.assertEqual(res.total_amount, 1100.0)

    def test_falls_back_to_the_all_accounts_default(self):
        corporate = self.env['res.partner'].create({
            'name': 'ZZ Corp', 'is_company': True, 'is_hotel_agency': True,
            'hotel_account_type_id': self.t_corp.id, 'hotel_credit_term': True})
        self.assertFalse(self._book(agency_id=corporate.id, booker_id=corporate.id).rate_plan_id)
        self.plan_any.is_default = True
        self.assertEqual(self._book(agency_id=corporate.id, booker_id=corporate.id).rate_plan_id,
                         self.plan_any)

    def test_plan_for_another_account_type_is_refused(self):
        with self.assertRaisesRegex(ValidationError, 'OTA bookings only'):
            self._book(rate_plan_id=self.plan_ota.id)
        self._book(rate_plan_id=self.plan_any.id)        # all accounts: fine

    def test_changing_the_agency_is_checked(self):
        res = self._book(rate_plan_id=self.plan_agent.id, agency_id=self.agent.id,
                         booker_id=self.agent.id)
        with self.assertRaises(ValidationError):
            res.write({'agency_id': False, 'booker_id': False})

    def test_one_default_per_account_type(self):
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.plan'].create({
                'name': 'ZZ Second OTA Default', 'account_type_id': self.t_ota.id,
                'is_default': True})

    def test_a_new_account_type_works_like_the_others(self):
        """Account types are records the hotel adds itself."""
        school = self.env['hotel.account.type'].create({'name': 'ZZ School Groups', 'code': 'zz_school'})
        agency = self.env['res.partner'].create({
            'name': 'ZZ School', 'is_company': True, 'is_hotel_agency': True,
            'hotel_account_type_id': school.id, 'hotel_credit_term': True})
        plan = self.env['hotel.rate.plan'].create({
            'name': 'ZZ School Rate', 'pricing_mode': 'pax', 'account_type_id': school.id,
            'is_default': True,
            'line_ids': [(0, 0, {'room_type_id': self.room_type.id, 'first_pax': 700.0})]})
        res = self._book(agency_id=agency.id, booker_id=agency.id)
        self.assertEqual((res.account_type_id, res.rate_plan_id, res.total_amount), (school, plan, 700.0))
        with self.assertRaises(ValidationError):
            self._book(rate_plan_id=plan.id)          # a direct booking

    def test_direct_guest_type_is_protected(self):
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            self.t_direct.active = False
        with self.assertRaises(UserError):
            self.t_direct.unlink()
