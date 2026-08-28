# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCheckoutBalance(TransactionCase):
    """Departure is barred while the folio still owes money, and the folio
    can be printed for the guest to sign."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env['hotel.folio'])

        cls.room_type = cls.env['hotel.room.type'].create({
            'name': 'ZZ Balance Type',
            'capacity': 2,
            'base_rate': 1000000.0,
        })
        cls.room = cls.env['hotel.room'].create({
            'name': 'ZZ-201',
            'room_type_id': cls.room_type.id,
            'status': 'available',
        })
        cls.room2 = cls.env['hotel.room'].create({
            'name': 'ZZ-202',
            'room_type_id': cls.room_type.id,
            'status': 'available',
        })
        cls.guest = cls.env['res.partner'].create({'name': 'ZZ Balance Guest'})
        cls.guest2 = cls.env['res.partner'].create({'name': 'ZZ Balance Guest 2'})
        cls.credit_agency = cls.env['res.partner'].create({
            'name': 'ZZ Credit Corp',
            'is_company': True,
            'is_hotel_agency': True,
            'hotel_agency_type': 'corporate',
            'hotel_credit_term': True,
            'hotel_routing': 'room',
        })
        cls.cash_agency = cls.env['res.partner'].create({
            'name': 'ZZ Cash Agency',
            'is_company': True,
            'is_hotel_agency': True,
            'hotel_agency_type': 'travel_agent',
            'hotel_credit_term': False,
            'hotel_routing': 'room',
        })
        cls.hotel_admin = cls.env['res.users'].create({
            'name': 'ZZ Hotel Admin',
            'login': 'zz_admin_balance',
            'group_ids': [(6, 0, [
                cls.env.ref('hotel_core.group_hotel_admin').id,
                cls.env.ref('hotel_core.group_hotel_reception').id,
                cls.env.ref('base.group_user').id,
            ])],
        })
        cls.reception = cls.env['res.users'].create({
            'name': 'ZZ Reception Balance',
            'login': 'zz_reception_balance',
            'group_ids': [(6, 0, [
                cls.env.ref('hotel_core.group_hotel_reception').id,
                cls.env.ref('base.group_user').id,
            ])],
        })

    def _make_reservation(self, **overrides):
        vals = {
            'guest_id': self.guest.id,
            'room_id': self.room.id,
            'room_type_id': self.room_type.id,
            'checkin_date': self.today,
            'checkout_date': self.today + timedelta(days=2),
            'nightly_rate': 1000000.0,
            'send_confirmation': False,
        }
        vals.update(overrides)
        return self.env['hotel.reservation'].create(vals)

    def _check_in(self, **overrides):
        res = self._make_reservation(**overrides)
        res.action_confirm()
        # Agencies without credit terms must prepay before arrival, and
        # create() now derives that rule for programmatic bookings too.
        # These tests are about the check-OUT guard, so satisfy the
        # arrival precondition and move on.
        if res.payment_required and not res.prepaid:
            res.prepaid = True
        res.action_check_in()
        return res

    def _register_payment(self, folio, amount):
        self.env['hotel.folio.payment.wizard'].create({
            'folio_id': folio.id,
            'amount': amount,
        }).action_register_payment()
        folio.invalidate_recordset()

    # ── The guard ────────────────────────────────────────────────────────

    def test_unbalanced_folio_blocks_checkout(self):
        res = self._check_in()
        self.assertEqual(res.folio_id.balance, 2000000.0)

        with self.assertRaises(UserError):
            res.action_check_out()
        self.assertEqual(res.state, 'checked_in',
                         'the guest must still be in house after a barred '
                         'check-out')

    def test_error_names_the_folio_and_the_amount(self):
        res = self._check_in()
        with self.assertRaises(UserError) as caught:
            res.action_check_out()
        message = str(caught.exception)
        self.assertIn(res.folio_id.name, message,
                      'reception must be told which folio is short')
        self.assertIn('2,000,000', message.replace('\N{NO-BREAK SPACE}', ' '),
                      'reception must be told how much to collect')

    def test_settled_folio_checks_out(self):
        res = self._check_in()
        self._register_payment(res.folio_id, 2000000.0)

        res.action_check_out()
        self.assertEqual(res.state, 'checked_out')
        self.assertTrue(res.folio_id.invoice_id)

    def test_part_payment_still_blocks(self):
        res = self._check_in()
        self._register_payment(res.folio_id, 1999000.0)

        with self.assertRaises(UserError):
            res.action_check_out()
        self.assertEqual(res.state, 'checked_in')

    def test_overpaid_folio_checks_out(self):
        """An overpayment is a refund the hotel owes — not a reason to hold
        the guest at the desk."""
        res = self._check_in()
        self._register_payment(res.folio_id, 2500000.0)

        res.action_check_out()
        self.assertEqual(res.state, 'checked_out')
        self.assertEqual(res.folio_id.balance, -500000.0)

    def test_reception_is_blocked_too(self):
        """The guard is on the model, not just the button."""
        res = self._check_in().with_user(self.reception)
        with self.assertRaises(UserError):
            res.action_check_out()

    # ── Late check-out is quoted before it is charged ────────────────────

    def test_late_checkout_amount_is_included_in_the_block(self):
        res = self._check_in(
            checkin_date=self.today - timedelta(days=3),
            checkout_date=self.today - timedelta(days=1),
        )
        folio = res.folio_id
        self._register_payment(folio, folio.balance)
        self.assertEqual(folio.balance, 0.0)

        # One night past departure is owed but not yet on the folio.
        with self.assertRaises(UserError) as caught:
            res.action_check_out()
        message = str(caught.exception).replace('\N{NO-BREAK SPACE}', ' ')
        self.assertIn('1,000,000', message,
                      'the late-checkout night must be quoted to reception')

        folio.invalidate_recordset()
        self.assertEqual(
            folio.total_amount, 2000000.0,
            'a barred check-out must not leave a late-checkout charge behind')

        self._register_payment(folio, 1000000.0)
        res.action_check_out()
        folio.invalidate_recordset()
        self.assertEqual(res.state, 'checked_out')
        self.assertEqual(folio.total_amount, 3000000.0,
                         'the late night is charged once the folio clears')
        self.assertEqual(folio.balance, 0.0)

    # ── Credit ledger is exempt ──────────────────────────────────────────

    def test_credit_company_folio_does_not_block(self):
        res = self._check_in(agency_id=self.credit_agency.id)
        company_folio = res.folio_id.linked_folio_id
        self.assertTrue(company_folio.is_credit_ledger())
        self.assertGreater(company_folio.balance, 0.0)

        res.action_check_out()
        self.assertEqual(res.state, 'checked_out',
                         'a company account on credit terms is collected '
                         'later, not at the desk')

    def test_agency_without_credit_terms_must_pay_at_the_desk(self):
        res = self._check_in(agency_id=self.cash_agency.id)
        company_folio = res.folio_id.linked_folio_id
        self.assertFalse(company_folio.is_credit_ledger())

        with self.assertRaises(UserError):
            res.action_check_out()

        self._register_payment(company_folio, company_folio.balance)
        res.action_check_out()
        self.assertEqual(res.state, 'checked_out')

    def test_guest_extras_block_even_on_a_credit_booking(self):
        """Credit terms cover the routed room charges, not the guest's bar tab."""
        res = self._check_in(agency_id=self.credit_agency.id)
        guest_folio = res.folio_id
        self.env['hotel.add.charge.wizard'].create({
            'folio_id': guest_folio.id,
            'name': 'Bar tab',
            'charge_type': 'fnb',
            'quantity': 1.0,
            'amount': 300000.0,
        }).action_add_charge()

        with self.assertRaises(UserError):
            res.action_check_out()

        self._register_payment(guest_folio, 300000.0)
        res.action_check_out()
        self.assertEqual(res.state, 'checked_out')

    # ── Groups ───────────────────────────────────────────────────────────

    def test_group_folio_judged_only_on_the_last_departure(self):
        group = self.env['hotel.booking.group'].create({
            'guest_id': self.guest.id,
            'checkin_date': self.today,
            'checkout_date': self.today + timedelta(days=2),
        })
        master = group.master_folio_id
        res_a = self._make_reservation(group_id=group.id)
        res_b = self._make_reservation(
            group_id=group.id, room_id=self.room2.id, guest_id=self.guest2.id)
        (res_a | res_b).action_confirm()
        (res_a | res_b).action_check_in()

        # First room leaves while the second can still charge the folio.
        res_a.action_check_out()
        self.assertEqual(res_a.state, 'checked_out')

        with self.assertRaises(UserError):
            res_b.action_check_out()

        self._register_payment(master, master.balance)
        res_b.action_check_out()
        self.assertEqual(res_b.state, 'checked_out')
        self.assertTrue(master.invoice_id)

    # ── Administrator override ───────────────────────────────────────────

    def test_admin_can_force_and_it_is_logged(self):
        res = self._check_in()
        folio = res.folio_id
        before = len(folio.message_ids)

        res.with_user(self.hotel_admin).action_force_check_out()
        self.assertEqual(res.state, 'checked_out')
        folio.invalidate_recordset()
        self.assertEqual(folio.balance, 2000000.0,
                         'forcing must not silently write the debt off')
        self.assertGreater(len(folio.message_ids), before,
                           'a forced check-out must leave a trace on the folio')

    def test_forced_log_records_the_debt_actually_left_behind(self):
        """Late-checkout nights raised by the departure must be in the trace."""
        res = self._check_in(
            checkin_date=self.today - timedelta(days=3),
            checkout_date=self.today - timedelta(days=1),
        )
        folio = res.folio_id
        self._register_payment(folio, folio.balance)

        res.with_user(self.hotel_admin).action_force_check_out()
        folio.invalidate_recordset()

        self.assertEqual(folio.balance, 1000000.0,
                         'the late-checkout night is still owed')
        logged = folio.message_ids[0].body.replace('\N{NO-BREAK SPACE}', ' ')
        self.assertIn('1,000,000', logged,
                      'the trace must show the late-checkout night, not the '
                      'zero balance that showed before departure')

    def test_reception_cannot_force(self):
        res = self._check_in().with_user(self.reception)
        with self.assertRaises(UserError):
            res.action_force_check_out()
        self.assertEqual(res.state, 'checked_in')

    # ── Printable folio ──────────────────────────────────────────────────

    def test_folio_report_renders(self):
        res = self._check_in()
        self._register_payment(res.folio_id, 500000.0)

        report = self.env.ref('hotel_frontdesk.action_report_hotel_folio')
        html = self.env['ir.actions.report']._render_qweb_html(
            report.report_name, res.folio_id.ids)[0].decode()

        self.assertIn(res.folio_id.name, html)
        self.assertIn('ZZ Balance Guest', html)
        self.assertIn('Guest signature', html)
        self.assertIn('Balance Due', html)

    def test_folio_report_shows_refund_when_overpaid(self):
        res = self._check_in()
        self._register_payment(res.folio_id, 2500000.0)

        report = self.env.ref('hotel_frontdesk.action_report_hotel_folio')
        html = self.env['ir.actions.report']._render_qweb_html(
            report.report_name, res.folio_id.ids)[0].decode()
        self.assertIn('Refund Due to Guest', html)

    def test_reception_can_print_the_folio(self):
        res = self._check_in().with_user(self.reception)
        action = res.action_print_folio()
        self.assertEqual(action['type'], 'ir.actions.report')

        report = self.env.ref('hotel_frontdesk.action_report_hotel_folio')
        html = self.env['ir.actions.report'].with_user(
            self.reception)._render_qweb_html(
                report.report_name, res.folio_id.ids)[0].decode()
        self.assertIn(res.folio_id.name, html)

    def test_printing_a_stay_covers_both_folios(self):
        res = self._check_in(agency_id=self.credit_agency.id)
        action = res.action_print_folio()
        self.assertEqual(
            sorted(action['context']['active_ids']),
            sorted((res.folio_id | res.folio_id.linked_folio_id).ids),
            'both sides of a split stay must print together')

    # ── Audit fixes (29 Aug 2026) ────────────────────────────────────────

    def test_extending_a_stay_in_house_reposts_room_charges(self):
        """Amending dates after check-in must resync the folio."""
        res = self._check_in()
        folio = res.folio_id
        self.assertEqual(folio.total_amount, 2000000.0, '2 nights at check-in')

        res.checkout_date = self.today + timedelta(days=4)
        folio.invalidate_recordset()

        room_lines = folio.line_ids.filtered(lambda l: l.charge_type == 'room')
        self.assertEqual(len(room_lines), 4, 'all four nights are charged')
        self.assertEqual(folio.total_amount, 4000000.0)

        # The guard must now see the real debt, not the stale total.
        with self.assertRaises(UserError):
            res.action_check_out()

    def test_shortening_a_stay_in_house_removes_the_dropped_nights(self):
        res = self._check_in()
        folio = res.folio_id
        res.checkout_date = self.today + timedelta(days=1)
        folio.invalidate_recordset()
        self.assertEqual(folio.total_amount, 1000000.0, 'one night only')

    def test_amending_does_not_touch_another_reservations_charges(self):
        """Group folios hold several reservations' lines — resync only ours."""
        group = self.env['hotel.booking.group'].create({
            'guest_id': self.guest.id,
            'checkin_date': self.today,
            'checkout_date': self.today + timedelta(days=2),
        })
        res_a = self._make_reservation(group_id=group.id)
        res_b = self._make_reservation(group_id=group.id,
                                       room_id=self.room2.id)
        for r in (res_a, res_b):
            r.action_confirm()
            if r.payment_required and not r.prepaid:
                r.prepaid = True
            r.action_check_in()
        master = group.master_folio_id
        before_b = sum(
            master.line_ids.filtered(lambda l: l.reservation_id == res_b)
            .mapped('subtotal'))

        res_a.checkout_date = self.today + timedelta(days=3)
        master.invalidate_recordset()
        after_b = sum(
            master.line_ids.filtered(lambda l: l.reservation_id == res_b)
            .mapped('subtotal'))
        self.assertEqual(before_b, after_b, "the other stay must be untouched")

    def test_negative_quantity_charge_is_refused(self):
        """A negative quantity would lower the balance and beat the guard."""
        res = self._check_in()
        wizard = self.env['hotel.add.charge.wizard'].create({
            'folio_id': res.folio_id.id,
            'name': 'Bogus credit',
            'charge_type': 'manual',
            'quantity': -1.0,
            'amount': 500000.0,
        })
        with self.assertRaises(UserError):
            wizard.action_add_charge()

    def test_charge_refused_once_the_folio_is_invoiced(self):
        """Post-invoice charges could never be billed — refuse them."""
        res = self._check_in()
        folio = res.folio_id
        self._register_payment(folio, folio.balance)
        res.action_check_out()
        self.assertTrue(folio.invoice_id, 'check-out raises the invoice')

        wizard = self.env['hotel.add.charge.wizard'].create({
            'folio_id': folio.id,
            'name': 'Late minibar',
            'charge_type': 'fnb',
            'quantity': 1.0,
            'amount': 100000.0,
        })
        with self.assertRaises(UserError):
            wizard.action_add_charge()

    def test_agency_prepayment_rule_applies_to_programmatic_bookings(self):
        """The rule lived only in an onchange, so wizards/imports skipped it."""
        res = self._make_reservation(agency_id=self.cash_agency.id)
        self.assertTrue(
            res.payment_required,
            'a non-credit agency booking must require prepayment')
        credit = self._make_reservation(agency_id=self.credit_agency.id)
        self.assertFalse(
            credit.payment_required,
            'credit terms mean no prepayment is demanded')

    def test_price_list_change_spares_in_house_guests(self):
        """New prices apply to future bookings, not to a guest already in."""
        booked = self._make_reservation(room_id=self.room2.id)
        booked.action_confirm()
        in_house = self._check_in()

        self.room_type.base_rate = 9999999.0
        (booked | in_house).invalidate_recordset()

        self.assertEqual(
            in_house.nightly_rate, 1000000.0,
            'an in-house stay keeps the rate it was quoted')
