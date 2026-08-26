# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSplitFolio(TransactionCase):
    """Corporate / travel-agent split folios, routing and folio payments."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env['hotel.folio'])

        cls.room_type = cls.env['hotel.room.type'].create({
            'name': 'ZZ Test Type',
            'capacity': 2,
            'base_rate': 1000000.0,
        })
        cls.room = cls.env['hotel.room'].create({
            'name': 'ZZ-101',
            'room_type_id': cls.room_type.id,
            'status': 'available',
        })
        cls.room2 = cls.env['hotel.room'].create({
            'name': 'ZZ-102',
            'room_type_id': cls.room_type.id,
            'status': 'available',
        })
        cls.guest = cls.env['res.partner'].create({'name': 'ZZ Guest'})
        cls.guest2 = cls.env['res.partner'].create({'name': 'ZZ Guest Two'})
        cls.agency = cls.env['res.partner'].create({
            'name': 'ZZ Corp',
            'is_company': True,
            'is_hotel_agency': True,
            'hotel_agency_type': 'corporate',
            'hotel_credit_term': True,
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

    # ── Split folios ─────────────────────────────────────────────────────

    def test_direct_booking_keeps_single_folio(self):
        """No agency: one guest folio, exactly as before."""
        res = self._make_reservation()
        res.action_confirm()
        res.action_check_in()

        self.assertEqual(res.folio_id.folio_type, 'guest')
        self.assertFalse(res.folio_id.linked_folio_id,
                         'direct bookings must not open a company folio')
        self.assertEqual(res.folio_id.total_amount, 2000000.0,
                         'room charges belong on the guest folio')

    def test_agency_booking_opens_two_folios(self):
        """Agency booking: room to the company folio, guest folio for extras."""
        res = self._make_reservation(agency_id=self.agency.id)
        res.action_confirm()
        res.action_check_in()

        guest_folio = res.folio_id
        company_folio = guest_folio.linked_folio_id

        self.assertTrue(company_folio, 'company folio was not opened')
        self.assertEqual(guest_folio.folio_type, 'guest')
        self.assertEqual(company_folio.folio_type, 'company')
        self.assertEqual(company_folio.agency_id, self.agency)
        self.assertEqual(company_folio.bill_to_id, self.agency,
                         'company folio bills the company')
        self.assertEqual(guest_folio.bill_to_id, self.guest,
                         'guest folio bills the guest, not the agency')
        # Routing = room & tax only
        self.assertEqual(company_folio.total_amount, 2000000.0)
        self.assertEqual(guest_folio.total_amount, 0.0)
        # The pair points both ways
        self.assertEqual(company_folio.linked_folio_id, guest_folio)

    def test_routing_all_sends_incidentals_to_company(self):
        self.agency.hotel_routing = 'all'
        res = self._make_reservation(agency_id=self.agency.id)
        res.action_confirm()
        res.action_check_in()

        company_folio = res.folio_id.linked_folio_id
        self.assertEqual(
            res._folio_for_charge_type('fnb'), company_folio,
            'routing=all must send incidentals to the company folio')

    def test_routing_none_keeps_single_folio(self):
        self.agency.hotel_routing = 'none'
        res = self._make_reservation(agency_id=self.agency.id)
        res.action_confirm()
        res.action_check_in()

        self.assertFalse(res.folio_id.linked_folio_id,
                         'routing=none must not open a company folio')
        self.assertEqual(res.folio_id.total_amount, 2000000.0)

    def test_check_in_is_idempotent_on_folios(self):
        """_ensure_folios must not duplicate folios if called again."""
        res = self._make_reservation(agency_id=self.agency.id)
        res.action_confirm()
        res.action_check_in()
        guest_folio, company_folio = res.folio_id, res.folio_id.linked_folio_id

        res._ensure_folios()
        self.assertEqual(res.folio_id, guest_folio)
        self.assertEqual(res.folio_id.linked_folio_id, company_folio)
        self.assertEqual(
            self.env['hotel.folio'].search_count(
                [('reservation_id', '=', res.id)]), 2,
            'a second _ensure_folios opened extra folios')

    # ── Charges ──────────────────────────────────────────────────────────

    def test_add_charge_wizard_routes_incidental_to_guest(self):
        res = self._make_reservation(agency_id=self.agency.id)
        res.action_confirm()
        res.action_check_in()
        guest_folio = res.folio_id

        wizard = self.env['hotel.add.charge.wizard'].create({
            'folio_id': guest_folio.id,
            'name': 'Minibar',
            'charge_type': 'fnb',
            'quantity': 2.0,
            'amount': 50000.0,
        })
        self.assertEqual(wizard.post_to_folio_id, guest_folio,
                         'incidentals default to the guest folio')
        wizard.action_add_charge()
        self.assertEqual(guest_folio.total_amount, 100000.0)

    def test_add_charge_wizard_override_moves_charge(self):
        """Reception can push a single charge onto the company folio."""
        res = self._make_reservation(agency_id=self.agency.id)
        res.action_confirm()
        res.action_check_in()
        guest_folio = res.folio_id
        company_folio = guest_folio.linked_folio_id
        before = company_folio.total_amount

        wizard = self.env['hotel.add.charge.wizard'].create({
            'folio_id': guest_folio.id,
            'name': 'Meeting room',
            'charge_type': 'service',
            'quantity': 1.0,
            'amount': 300000.0,
        })
        wizard.post_to_folio_id = company_folio
        wizard.action_add_charge()

        self.assertEqual(company_folio.total_amount, before + 300000.0)
        self.assertEqual(guest_folio.total_amount, 0.0)

    # ── Payments ─────────────────────────────────────────────────────────

    def _register_payment(self, folio, amount):
        wizard = self.env['hotel.folio.payment.wizard'].create({
            'folio_id': folio.id,
            'amount': amount,
        })
        wizard.action_register_payment()
        folio.invalidate_recordset()
        return wizard

    def test_payment_updates_balance_and_state(self):
        res = self._make_reservation()
        res.action_confirm()
        res.action_check_in()
        folio = res.folio_id

        self.assertEqual(folio.balance, 2000000.0)
        self.assertEqual(folio.payment_state, 'open')

        self._register_payment(folio, 500000.0)
        self.assertEqual(folio.amount_paid, 500000.0)
        self.assertEqual(folio.balance, 1500000.0)
        self.assertEqual(folio.payment_state, 'open',
                         'a partial deposit must not mark the folio paid')

        self._register_payment(folio, 1500000.0)
        self.assertEqual(folio.balance, 0.0)
        self.assertEqual(folio.payment_state, 'paid')

    def test_payment_defaults_to_bill_to_party(self):
        res = self._make_reservation(agency_id=self.agency.id)
        res.action_confirm()
        res.action_check_in()

        wizard = self.env['hotel.folio.payment.wizard'].create({
            'folio_id': res.folio_id.linked_folio_id.id,
            'amount': 100000.0,
        })
        self.assertEqual(wizard.partner_id, self.agency,
                         'company folio payment comes from the company')

        guest_wizard = self.env['hotel.folio.payment.wizard'].create({
            'folio_id': res.folio_id.id,
            'amount': 100000.0,
        })
        self.assertEqual(guest_wizard.partner_id, self.guest)

    def test_manual_folio_can_take_charges_and_payment(self):
        """A folio opened by hand works standalone (walk-in / function account)."""
        folio = self.env['hotel.folio'].create({'guest_id': self.guest.id})
        self.assertTrue(folio.name and folio.name != 'New',
                        'manual folio must get a sequence number')

        self.env['hotel.add.charge.wizard'].create({
            'folio_id': folio.id,
            'name': 'Function room hire',
            'charge_type': 'manual',
            'quantity': 1.0,
            'amount': 750000.0,
        }).action_add_charge()
        self.assertEqual(folio.total_amount, 750000.0)

        self._register_payment(folio, 750000.0)
        self.assertEqual(folio.payment_state, 'paid')

    # ── Check-out & invoicing ────────────────────────────────────────────

    def test_checkout_invoices_both_folios_to_right_parties(self):
        res = self._make_reservation(agency_id=self.agency.id)
        res.action_confirm()
        res.action_check_in()
        guest_folio = res.folio_id
        company_folio = guest_folio.linked_folio_id

        self.env['hotel.add.charge.wizard'].create({
            'folio_id': guest_folio.id,
            'name': 'Bar tab',
            'charge_type': 'fnb',
            'quantity': 1.0,
            'amount': 200000.0,
        }).action_add_charge()

        # The bar tab is the guest's to settle at the desk; the routed room
        # charges ride the company folio's credit terms.
        self._register_payment(guest_folio, 200000.0)
        res.action_check_out()

        self.assertTrue(company_folio.invoice_id, 'company folio not invoiced')
        self.assertEqual(company_folio.invoice_id.partner_id, self.agency)
        self.assertTrue(guest_folio.invoice_id, 'guest folio not invoiced')
        self.assertEqual(guest_folio.invoice_id.partner_id, self.guest)
        self.assertNotEqual(guest_folio.invoice_id, company_folio.invoice_id,
                            'the two folios must produce separate invoices')

    def test_credit_term_applied_to_company_invoice(self):
        term = self.env['account.payment.term'].search([], limit=1)
        self.agency.property_payment_term_id = term
        res = self._make_reservation(agency_id=self.agency.id)
        res.action_confirm()
        res.action_check_in()
        company_folio = res.folio_id.linked_folio_id

        res.action_check_out()
        self.assertEqual(company_folio.invoice_id.invoice_payment_term_id, term,
                         'agency credit terms must carry onto the invoice')

    def test_deposit_reduces_invoice_residual(self):
        """A deposit taken before check-out must reconcile against the invoice."""
        res = self._make_reservation()
        res.action_confirm()
        res.action_check_in()
        folio = res.folio_id

        self._register_payment(folio, 800000.0)
        # Only a deposit was taken, so an ordinary check-out is barred; the
        # point here is the residual, so force the departure through.
        res.action_force_check_out()
        folio.invalidate_recordset()

        invoice = folio.invoice_id
        self.assertTrue(invoice, 'folio was not invoiced at check-out')
        self.assertEqual(invoice.amount_total, 2000000.0)
        self.assertEqual(
            invoice.amount_residual, 1200000.0,
            'the deposit did not reconcile against the invoice — residual '
            'should be the total less the deposit')

    def test_canceled_payment_does_not_count_as_paid(self):
        res = self._make_reservation()
        res.action_confirm()
        res.action_check_in()
        folio = res.folio_id

        self._register_payment(folio, 2000000.0)
        self.assertEqual(folio.payment_state, 'paid')

        folio.payment_ids.action_cancel()
        folio.invalidate_recordset()
        self.assertEqual(folio.amount_paid, 0.0,
                         'a canceled payment still counted toward amount_paid')
        self.assertEqual(folio.payment_state, 'open')

    def test_reception_can_run_the_whole_desk_flow(self):
        """Reception has no accounting rights but drives every folio step."""
        reception = self.env['res.users'].create({
            'name': 'ZZ Reception',
            'login': 'zz_reception_split_folio',
            'group_ids': [(6, 0, [
                self.env.ref('hotel_core.group_hotel_reception').id,
                self.env.ref('base.group_user').id,
            ])],
        })
        res = self._make_reservation(agency_id=self.agency.id).with_user(reception)
        res.action_confirm()
        res.action_check_in()

        guest_folio = res.folio_id
        self.env['hotel.add.charge.wizard'].with_user(reception).create({
            'folio_id': guest_folio.id,
            'name': 'Laundry',
            'charge_type': 'service',
            'quantity': 1.0,
            'amount': 120000.0,
        }).action_add_charge()

        self.env['hotel.folio.payment.wizard'].with_user(reception).create({
            'folio_id': guest_folio.id,
            'amount': 120000.0,
        }).action_register_payment()

        # Reading the folio's payment figures must not raise for reception.
        guest_folio.invalidate_recordset()
        self.assertEqual(guest_folio.with_user(reception).amount_paid, 120000.0)

        res.action_check_out()
        self.assertTrue(guest_folio.invoice_id)

    def test_non_agency_group_still_shares_one_folio(self):
        """Plain group bookings keep the pre-existing single-folio behaviour."""
        group = self.env['hotel.booking.group'].create({
            'guest_id': self.guest.id,
            'checkin_date': self.today,
            'checkout_date': self.today + timedelta(days=2),
        })
        master = group.master_folio_id
        self.assertEqual(master.folio_type, 'guest')

        res_a = self._make_reservation(group_id=group.id)
        res_b = self._make_reservation(
            group_id=group.id, room_id=self.room2.id, guest_id=self.guest2.id)
        (res_a | res_b).action_confirm()
        (res_a | res_b).action_check_in()

        self.assertEqual(res_a.folio_id, master)
        self.assertEqual(res_b.folio_id, master)
        self.assertFalse(master.linked_folio_id)
        self.assertEqual(master.total_amount, 4000000.0)

        res_a.action_check_out()
        self.assertFalse(master.invoice_id,
                         'invoiced while a room was still in house')
        self._register_payment(master, 4000000.0)
        res_b.action_check_out()
        self.assertTrue(master.invoice_id)
        self.assertEqual(master.invoice_id.partner_id, self.guest)

    def test_group_company_folio_waits_for_last_departure(self):
        """The shared company folio invoices only once every room has left."""
        group = self.env['hotel.booking.group'].create({
            'guest_id': self.guest.id,
            'checkin_date': self.today,
            'checkout_date': self.today + timedelta(days=2),
            'agency_id': self.agency.id,
        })
        master = group.master_folio_id
        self.assertEqual(master.folio_type, 'company',
                         'an agency group master folio is the company folio')

        res_a = self._make_reservation(group_id=group.id)
        res_b = self._make_reservation(
            group_id=group.id, room_id=self.room2.id, guest_id=self.guest2.id)
        (res_a | res_b).action_confirm()
        (res_a | res_b).action_check_in()

        # Each room has its own guest folio, both routed to the one master.
        self.assertNotEqual(res_a.folio_id, res_b.folio_id)
        self.assertEqual(res_a.folio_id.linked_folio_id, master)
        self.assertEqual(res_b.folio_id.linked_folio_id, master)
        self.assertEqual(master.total_amount, 4000000.0,
                         'both rooms charge the shared company folio')

        res_a.action_check_out()
        self.assertFalse(
            master.invoice_id,
            'company folio invoiced while a room was still in house')

        res_b.action_check_out()
        self.assertTrue(master.invoice_id,
                        'company folio not invoiced after the last departure')
        self.assertEqual(master.invoice_id.partner_id, self.agency)
