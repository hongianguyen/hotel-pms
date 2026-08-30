# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFolioLifecycle(TransactionCase):
    """The folio opens at confirmation, not at check-in, so money taken
    before arrival has somewhere to go — and a booking that never happens
    leaves no empty folio behind."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env['hotel.folio'])

        cls.room_type = cls.env['hotel.room.type'].create({
            'name': 'ZZ Lifecycle Type',
            'capacity': 2,
            'base_rate': 1000000.0,
        })
        cls.room = cls.env['hotel.room'].create({
            'name': 'ZZ-301',
            'room_type_id': cls.room_type.id,
            'status': 'available',
        })
        cls.room2 = cls.env['hotel.room'].create({
            'name': 'ZZ-302',
            'room_type_id': cls.room_type.id,
            'status': 'available',
        })
        cls.guest = cls.env['res.partner'].create({'name': 'ZZ Lifecycle Guest'})
        cls.reception = cls.env['res.users'].create({
            'name': 'ZZ Lifecycle Reception',
            'login': 'zz_reception_lifecycle',
            'group_ids': [(6, 0, [
                cls.env.ref('hotel_core.group_hotel_reception').id,
                cls.env.ref('base.group_user').id,
            ])],
        })
        cls.credit_agency = cls.env['res.partner'].create({
            'name': 'ZZ Lifecycle Credit Corp',
            'is_company': True,
            'is_hotel_agency': True,
            'hotel_agency_type': 'corporate',
            'hotel_credit_term': True,
            'hotel_routing': 'room',
        })
        cls.cash_agency = cls.env['res.partner'].create({
            'name': 'ZZ Lifecycle Cash Agency',
            'is_company': True,
            'is_hotel_agency': True,
            'hotel_agency_type': 'travel_agent',
            'hotel_credit_term': False,
            'hotel_routing': 'room',
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

    def _register_payment(self, folio, amount):
        self.env['hotel.folio.payment.wizard'].create({
            'folio_id': folio.id,
            'amount': amount,
        }).action_register_payment()
        folio.invalidate_recordset()

    # ── Folio opens at confirmation ──────────────────────────────────────

    def test_draft_booking_has_no_folio(self):
        res = self._make_reservation()
        self.assertFalse(res.folio_id,
                         'a booking nobody confirmed opens no account')

    def test_confirm_opens_an_empty_folio(self):
        res = self._make_reservation()
        res.action_confirm()

        self.assertTrue(res.folio_id, 'confirmation must open the folio')
        self.assertEqual(res.folio_id.folio_type, 'guest')
        self.assertFalse(
            res.folio_id.line_ids,
            'room charges still belong to check-in: a confirmed booking '
            'must not show revenue it has not earned')
        self.assertEqual(res.folio_id.balance, 0.0)

    def test_check_in_reuses_the_folio_opened_at_confirmation(self):
        res = self._make_reservation()
        res.action_confirm()
        folio = res.folio_id

        res.action_check_in()

        self.assertEqual(res.folio_id, folio,
                         '_ensure_folios must be idempotent, not open a '
                         'second folio at arrival')
        self.assertEqual(res.folio_id.balance, 2000000.0,
                         'the room charges land at check-in as before')

    def test_check_in_still_opens_a_folio_for_a_legacy_booking(self):
        """Bookings confirmed before this change arrive without a folio."""
        res = self._make_reservation()
        res.action_confirm()
        res.folio_id.sudo().unlink()
        self.assertFalse(res.folio_id)

        res.action_check_in()

        self.assertTrue(res.folio_id)
        self.assertEqual(res.folio_id.balance, 2000000.0)

    def test_corporate_booking_opens_both_folios_at_confirmation(self):
        res = self._make_reservation(
            agency_id=self.credit_agency.id,
            booker_id=self.guest.id,
        )
        res.action_confirm()

        company_folio = res.folio_id.linked_folio_id
        self.assertEqual(res.folio_id.folio_type, 'guest')
        self.assertEqual(company_folio.folio_type, 'company')
        self.assertEqual(company_folio.agency_id, self.credit_agency)

    # ── Deposits before arrival ──────────────────────────────────────────

    def test_deposit_can_be_taken_on_a_confirmed_booking(self):
        res = self._make_reservation()
        res.action_confirm()

        self._register_payment(res.folio_id, 500000.0)

        self.assertEqual(res.folio_id.amount_paid, 500000.0)
        self.assertEqual(res.folio_id.balance, -500000.0,
                         'a deposit before any charge leaves the folio in '
                         'credit')

    def test_deposit_survives_into_the_stay_and_settles_it(self):
        res = self._make_reservation()
        res.action_confirm()
        self._register_payment(res.folio_id, 2000000.0)

        res.action_check_in()
        res.folio_id.invalidate_recordset()
        self.assertEqual(res.folio_id.balance, 0.0,
                         'the pre-arrival deposit must cover the room '
                         'charges raised at check-in')

        res.action_check_out()
        self.assertEqual(res.state, 'checked_out',
                         'a stay paid in advance must not be barred by the '
                         'balance guard')

    def test_full_deposit_satisfies_the_prepayment_rule(self):
        res = self._make_reservation(
            agency_id=self.cash_agency.id,
            booker_id=self.guest.id,
        )
        res.action_confirm()
        self.assertTrue(res.payment_required)
        self.assertFalse(res.prepaid)

        # Routing sends the room to the company folio; the prepayment is
        # measured across both sides of the pair.
        self._register_payment(res.folio_id.linked_folio_id, res.total_amount)

        res.action_check_in()
        self.assertEqual(res.state, 'checked_in')

    def test_part_deposit_does_not_satisfy_the_prepayment_rule(self):
        res = self._make_reservation(
            agency_id=self.cash_agency.id,
            booker_id=self.guest.id,
        )
        res.action_confirm()
        self._register_payment(res.folio_id.linked_folio_id, 1000.0)

        with self.assertRaises(UserError):
            res.action_check_in()
        self.assertEqual(res.state, 'confirmed',
                         'a token deposit must not open the door on a '
                         'booking that has to be paid in full')

    def test_manual_prepaid_flag_still_works(self):
        res = self._make_reservation(
            agency_id=self.cash_agency.id,
            booker_id=self.guest.id,
        )
        res.action_confirm()
        res.prepaid = True

        res.action_check_in()
        self.assertEqual(res.state, 'checked_in')

    # ── Cancellation leaves no empty folio ───────────────────────────────

    def test_cancelling_a_confirmed_booking_removes_its_empty_folio(self):
        res = self._make_reservation()
        res.action_confirm()
        folio = res.folio_id

        res.action_cancel()

        self.assertFalse(folio.exists(),
                         'a booking that never happened must leave no open '
                         'folio in the ledger')
        self.assertFalse(res.folio_id)

    def test_cancelling_keeps_a_folio_that_holds_a_payment(self):
        res = self._make_reservation()
        res.action_confirm()
        folio = res.folio_id
        self._register_payment(folio, 500000.0)

        res.action_cancel()

        self.assertTrue(folio.exists(),
                        'a deposit already taken must survive the '
                        'cancellation — it is owed back or forfeited, '
                        'either way it is real money')
        self.assertEqual(folio.amount_paid, 500000.0)

    def test_cancelling_removes_both_sides_of_an_empty_pair(self):
        res = self._make_reservation(
            agency_id=self.credit_agency.id,
            booker_id=self.guest.id,
        )
        res.action_confirm()
        pair = res.folio_id | res.folio_id.linked_folio_id
        self.assertEqual(len(pair), 2)

        res.action_cancel()

        self.assertFalse(pair.exists())

    def test_reconfirming_a_cancelled_booking_opens_a_fresh_folio(self):
        res = self._make_reservation()
        res.action_confirm()
        res.action_cancel()
        res.action_reset_draft()

        res.action_confirm()

        self.assertTrue(res.folio_id,
                        'a revived booking must get its folio back')

    # ── Groups ───────────────────────────────────────────────────────────

    def _make_group(self, **overrides):
        vals = {
            'guest_id': self.guest.id,
            'checkin_date': self.today,
            'checkout_date': self.today + timedelta(days=2),
            'send_confirmation': False,
        }
        vals.update(overrides)
        group = self.env['hotel.booking.group'].create(vals)
        for room in (self.room, self.room2):
            self._make_reservation(room_id=room.id, group_id=group.id)
        return group

    def test_group_rooms_share_the_master_folio_at_confirmation(self):
        group = self._make_group()
        group.action_confirm()

        folios = group.reservation_ids.mapped('folio_id')
        self.assertEqual(len(folios), 1,
                         'the rooms of a group charge one master account')
        self.assertEqual(folios, group.master_folio_id)

    def test_master_folio_survives_cancelling_one_room(self):
        group = self._make_group()
        group.action_confirm()
        master = group.master_folio_id

        group.reservation_ids[0].action_cancel()

        self.assertTrue(master.exists(),
                        'the group is still arriving — its account must '
                        'stay open')

    def test_cancelling_a_whole_group_removes_its_empty_master_folio(self):
        group = self._make_group()
        group.action_confirm()
        master = group.master_folio_id

        group.action_cancel()

        self.assertFalse(master.exists())

    def test_reviving_a_cancelled_group_rebuilds_the_master_folio(self):
        group = self._make_group()
        group.action_confirm()
        group.action_cancel()
        group.reservation_ids.action_reset_draft()

        group.action_confirm()

        self.assertTrue(group.master_folio_id,
                        'a revived group must get a master folio again')
        folios = group.reservation_ids.mapped('folio_id')
        self.assertEqual(folios, group.master_folio_id,
                         'and its rooms must charge to it, not open '
                         'individual folios')

    def test_one_rooms_deposit_does_not_check_in_the_whole_group(self):
        """The master folio is shared, so the prepayment must be measured
        against every room charging it — not against the room at the desk."""
        group = self._make_group(
            agency_id=self.cash_agency.id,
            booker_id=self.guest.id,
        )
        group.action_confirm()
        first, second = group.reservation_ids[0], group.reservation_ids[1]
        self.assertTrue(first.payment_required)

        # Exactly one room's worth of money on the shared master folio.
        master = first.folio_id.linked_folio_id or first.folio_id
        self._register_payment(master, first.total_amount)

        first.action_check_in()
        self.assertEqual(first.state, 'checked_in',
                         'one room paid, one room may arrive')

        with self.assertRaises(UserError):
            second.action_check_in()
        self.assertEqual(second.state, 'confirmed',
                         'the second room is not paid for and must stay out')

    def test_group_fully_prepaid_checks_every_room_in(self):
        group = self._make_group(
            agency_id=self.cash_agency.id,
            booker_id=self.guest.id,
        )
        group.action_confirm()
        first = group.reservation_ids[0]
        master = first.folio_id.linked_folio_id or first.folio_id
        self._register_payment(
            master, sum(group.reservation_ids.mapped('total_amount')))

        group.action_check_in()

        self.assertEqual(set(group.reservation_ids.mapped('state')),
                         {'checked_in'})

    def test_group_room_inherits_the_prepayment_rule_from_the_group(self):
        """A room added to a corporate group bills through the group's
        agency, so it must prepay on the group's terms too."""
        cash = self._make_group(
            agency_id=self.cash_agency.id, booker_id=self.guest.id)
        credit = self._make_group(
            agency_id=self.credit_agency.id, booker_id=self.guest.id)

        self.assertTrue(all(cash.reservation_ids.mapped('payment_required')),
                        'no credit terms → the rooms prepay')
        self.assertFalse(any(credit.reservation_ids.mapped('payment_required')),
                         'credit terms → the rooms arrive and the company is '
                         'invoiced on account')

    def test_reception_can_confirm_and_cancel_a_booking(self):
        """Reception has no unlink right on hotel.folio and no read right on
        account.payment, so the cleanup must not run in their name."""
        res = self._make_reservation().with_user(self.reception)
        res.action_confirm()
        folio = res.folio_id
        self.assertTrue(folio)

        res.action_cancel()

        self.assertEqual(res.state, 'cancelled')
        self.assertFalse(folio.sudo().exists())

    def test_cancelling_every_room_closes_the_master_folio(self):
        """A group usually falls apart one room at a time from the
        reservation form, not via the group Cancel button."""
        group = self._make_group()
        group.action_confirm()
        master = group.master_folio_id

        for reservation in group.reservation_ids:
            reservation.action_cancel()

        self.assertFalse(master.exists(),
                         'the last room out closes the group account')
