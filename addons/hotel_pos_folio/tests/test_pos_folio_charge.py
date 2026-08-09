# -*- coding: utf-8 -*-
"""End-to-end: a restaurant order paid with "Charge to Room" lands on the
guest's folio and clears to zero on the check-out invoice.

This is the money path. It needs a real POS session, so it is kept apart from
test_pos_api_surface.py — a setup failure here must not take the API canaries
down with it.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.hotel_frontdesk.tests.common import HotelCommon


@tagged('post_install', '-at_install')
class TestPosFolioCharge(HotelCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('point_of_sale.group_pos_manager')

        cls.clearing_account = cls.env['account.account'].create({
            'code': 'TEST101960',
            'name': 'Test Room Charge Clearing',
            'account_type': 'asset_current',
            'reconcile': True,
        })
        cls.room_charge_method = cls.env['pos.payment.method'].create({
            'name': 'Charge to Room',
            'is_hotel_folio': True,
            'receivable_account_id': cls.clearing_account.id,
        })
        cls.pos_config = cls.env['pos.config'].create({
            'name': 'Test Restaurant',
            'payment_method_ids': [(6, 0, [cls.room_charge_method.id])],
        })
        cls.food = cls.env['product.product'].create({
            'name': 'Test Grilled Fish',
            'available_in_pos': True,
            'list_price': 250000.0,
            'taxes_id': [(5, 0, 0)],
        })

    def setUp(self):
        super().setUp()
        self.today = fields.Date.context_today(self.env['hotel.reservation'])
        self.reservation = self._make_reservation(
            self.today, self.today + timedelta(days=2))
        self.reservation.action_confirm()
        self.reservation.action_check_in()
        self.folio = self.reservation.folio_id

        self.pos_config.open_ui()
        self.session = self.pos_config.current_session_id

    def _charge_to_room(self, amount, partner, mark_paid=True):
        """Build a POS order settled with the room-charge method.

        `mark_paid=False` leaves it in draft — POS refuses to move an order
        back out of `paid`, so an unpaid case has to be built that way.
        """
        order = self.env['pos.order'].create({
            'session_id': self.session.id,
            'partner_id': partner.id,
            'amount_tax': 0.0,
            'amount_total': amount,
            'amount_paid': amount,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': self.food.id,
                'qty': 1,
                'price_unit': amount,
                'price_subtotal': amount,
                'price_subtotal_incl': amount,
            })],
        })
        self.env['pos.payment'].create({
            'pos_order_id': order.id,
            'payment_method_id': self.room_charge_method.id,
            'amount': amount,
        })
        if mark_paid:
            order.write({'state': 'paid'})
        return order

    # ── The charge ───────────────────────────────────────────────────────────

    def test_room_charge_posts_to_the_guest_folio(self):
        order = self._charge_to_room(250000.0, self.guest)
        order._post_hotel_folio_charge()

        self.assertEqual(order.hotel_folio_id, self.folio)
        line = order.hotel_folio_line_id
        self.assertTrue(line, 'the order must produce a folio line')
        self.assertEqual(line.folio_id, self.folio)
        self.assertEqual(line.charge_type, 'fnb')
        self.assertAlmostEqual(line.amount, 250000.0, places=2)
        self.assertEqual(
            line.account_id, self.clearing_account,
            'the folio line must carry the account POS debited, or the '
            'check-out invoice will not clear it')
        self.assertIn(self.room.name, line.name,
                      'the charge description should name the room')

    def test_charging_is_idempotent(self):
        """A POS sync can replay the same order; it must not double-charge."""
        order = self._charge_to_room(250000.0, self.guest)
        order._post_hotel_folio_charge()
        order._post_hotel_folio_charge()

        charges = self.folio.line_ids.filtered(
            lambda line: line.pos_order_id == order)
        self.assertEqual(len(charges), 1)

    def test_charge_reaches_the_checkout_invoice(self):
        order = self._charge_to_room(250000.0, self.guest)
        order._post_hotel_folio_charge()

        total_before = self.folio.total_amount
        self.reservation.action_check_out()
        invoice = self.folio.invoice_id

        self.assertTrue(invoice)
        self.assertAlmostEqual(
            sum(invoice.invoice_line_ids.mapped('price_subtotal')),
            total_before, places=2,
            msg='every folio charge, F&B included, must reach the invoice')
        self.assertIn(
            self.clearing_account, invoice.invoice_line_ids.mapped('account_id'),
            'the clearing account must be credited back so POS nets to zero')

    # ── The refusals ─────────────────────────────────────────────────────────

    def test_charge_without_a_customer_is_refused(self):
        order = self._charge_to_room(250000.0, self.guest)
        order.partner_id = False
        with self.assertRaises(UserError):
            order._post_hotel_folio_charge()

    def test_charge_for_a_guest_not_in_house_is_refused(self):
        walk_in = self.env['res.partner'].create({'name': 'Walk-in Diner'})
        order = self._charge_to_room(250000.0, walk_in)
        with self.assertRaises(UserError):
            order._post_hotel_folio_charge()

    def test_unpaid_order_does_not_charge(self):
        order = self._charge_to_room(250000.0, self.guest, mark_paid=False)
        self.assertEqual(order.state, 'draft')
        order._post_hotel_folio_charge()
        self.assertFalse(order.hotel_folio_line_id,
                         'an unsettled order must not hit the folio')
