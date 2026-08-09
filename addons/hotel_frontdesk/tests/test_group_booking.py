# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import HotelCommon


@tagged('post_install', '-at_install')
class TestGroupBooking(HotelCommon):
    """Group bookings cascade state to their children and share one folio."""

    def setUp(self):
        super().setUp()
        self.today = fields.Date.context_today(self.env['hotel.booking.group'])
        self.depart = self.today + timedelta(days=2)

        self.group = self.env['hotel.booking.group'].create({
            'guest_id': self.guest.id,
            'checkin_date': self.today,
            'checkout_date': self.depart,
            'send_confirmation': False,
        })
        self.child_a = self._make_reservation(
            self.today, self.depart, room=self.room, group_id=self.group.id)
        self.child_b = self._make_reservation(
            self.today, self.depart, room=self.room_2, group_id=self.group.id)

    def test_group_owns_a_master_folio_shared_by_children(self):
        self.assertTrue(self.group.master_folio_id,
                        'a group booking must open its master folio on create')
        self.assertEqual(self.child_a.folio_id, self.group.master_folio_id)
        self.assertEqual(self.child_b.folio_id, self.group.master_folio_id)
        self.assertEqual(self.group.room_count, 2)

    def test_state_cascades_to_children(self):
        self.group.action_confirm()
        self.assertEqual(self.child_a.state, 'confirmed')
        self.assertEqual(self.child_b.state, 'confirmed')

        self.group.action_check_in()
        self.assertEqual(self.child_a.state, 'checked_in')
        self.assertEqual(self.child_b.state, 'checked_in')

        self.group.action_check_out()
        self.assertEqual(self.child_a.state, 'checked_out')
        self.assertEqual(self.child_b.state, 'checked_out')

    def test_group_invoices_once_when_the_last_room_leaves(self):
        """Partial departure must not invoice the folio early."""
        self.group.action_confirm()
        self.group.action_check_in()
        folio = self.group.master_folio_id

        # Both rooms charged on the one folio: 2 rooms x 2 nights
        room_lines = folio.line_ids.filtered(lambda l: l.charge_type == 'room')
        self.assertEqual(len(room_lines), 4)

        self.child_a.action_check_out()
        self.assertFalse(folio.invoice_id,
                         'folio must stay open while a group room is in-house')

        self.child_b.action_check_out()
        self.assertTrue(folio.invoice_id,
                        'the last departure must settle the master folio')
        self.assertEqual(folio.payment_state, 'invoiced')

    def test_date_amendment_propagates_to_amendable_children_only(self):
        self.group.action_confirm()
        self.group.action_check_in()
        self.child_a.action_check_out()

        new_depart = self.depart + timedelta(days=1)
        # child_a has departed, child_b is in-house: neither is amendable
        self.group.write({'checkout_date': new_depart})
        self.assertEqual(self.child_a.checkout_date, self.depart)
        self.assertEqual(self.child_b.checkout_date, self.depart)

    def test_date_amendment_reaches_draft_children(self):
        new_depart = self.depart + timedelta(days=2)
        self.group.write({'checkout_date': new_depart})
        self.assertEqual(self.child_a.checkout_date, new_depart)
        self.assertEqual(self.child_b.checkout_date, new_depart)

    def test_cannot_cancel_a_group_with_rooms_in_house(self):
        self.group.action_confirm()
        self.group.action_check_in()
        with self.assertRaises(UserError):
            self.group.action_cancel()
