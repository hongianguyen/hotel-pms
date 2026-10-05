# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPaxTypes(TransactionCase):
    """Adult (13+), Child (6-12) and Infant (0-6), on the booking and on the
    per-guest lines."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        room_type = cls.env['hotel.room.type'].create({
            'name': 'ZZ Pax Tent', 'capacity': 4, 'max_adults': 2, 'max_children': 2,
            'base_rate': 1000000.0})
        cls.room_type = room_type
        cls.room = cls.env['hotel.room'].create({'name': 'ZZP-01', 'room_type_id': room_type.id})
        cls.guest = cls.env['res.partner'].create({'name': 'ZZ Pax Guest'})
        start = date.today() + timedelta(days=500)
        cls.vals = {
            'guest_id': cls.guest.id, 'room_type_id': room_type.id, 'room_id': cls.room.id,
            'checkin_date': start, 'checkout_date': start + timedelta(days=2),
            'send_confirmation': False,
        }

    def test_selection_and_labels(self):
        Pax = self.env['hotel.reservation.pax']
        labels = dict(Pax._fields['pax_type']._description_selection(self.env))
        self.assertEqual(labels, {'adult': 'Adult', 'child': 'Child (6-12)', 'infant': 'Infant (0-6)'})
        Res = self.env['hotel.reservation']
        self.assertEqual(Res._fields['children'].string, 'Children (6-12)')
        self.assertEqual(Res._fields['infants'].string, 'Infants (0-6)')

    def test_booking_records_all_three(self):
        res = self.env['hotel.reservation'].create(dict(
            self.vals, adults=2, children=1, infants=1,
            pax_ids=[(0, 0, {'name': 'Mum', 'pax_type': 'adult'}),
                     (0, 0, {'name': 'Kid', 'pax_type': 'child'}),
                     (0, 0, {'name': 'Baby', 'pax_type': 'infant'})]))
        self.assertEqual((res.adults, res.children, res.infants), (2, 1, 1))
        self.assertEqual(res.pax_ids.mapped('pax_type'), ['adult', 'child', 'infant'])
        self.assertEqual(res.pax_count, 3)

    def test_infants_default_to_zero_and_never_negative(self):
        res = self.env['hotel.reservation'].create(self.vals)
        self.assertEqual(res.infants, 0)
        with self.assertRaises(ValidationError):
            res.infants = -1

    # ── occupancy limits ───────────────────────────────────────────────
    def _book(self, adults, children=0, infants=0):
        return self.env['hotel.reservation'].create(dict(
            self.vals, adults=adults, children=children, infants=infants))

    def test_party_within_limits(self):
        self._book(2, 1, 1).unlink()     # 2 adults + 2 kids = 4 = max occupancy
        self._book(1, 0, 2).unlink()
        self._book(2)

    def test_too_many_adults(self):
        with self.assertRaisesRegex(ValidationError, 'at most 2 adult'):
            self._book(3)

    def test_children_and_infants_share_one_allowance(self):
        with self.assertRaisesRegex(ValidationError, 'at most 2 child'):
            self._book(1, 1, 2)
        with self.assertRaisesRegex(ValidationError, 'at most 2 child'):
            self._book(1, 0, 3)

    def test_total_counts_everyone(self):
        self.room_type.write({'capacity': 3})
        with self.assertRaisesRegex(ValidationError, 'at most 3 people'):
            self._book(2, 1, 1)
        self._book(2, 0, 1)

    def test_editing_the_party_is_checked(self):
        res = self._book(2)
        with self.assertRaises(ValidationError):
            res.infants = 3

    def test_old_booking_can_still_check_in(self):
        """A booking made before the limits existed is not judged again
        just because its state moves on."""
        res = self._book(2)
        self.env.cr.execute('UPDATE hotel_reservation SET adults = 5 WHERE id = %s', (res.id,))
        res.invalidate_recordset(['adults'])
        res.write({'state': 'confirmed'})
        self.assertEqual(res.adults, 5)

    def test_roh_is_not_judged_until_it_has_a_room(self):
        roh = self.env['hotel.room.type'].create({
            'name': 'ZZ Pax ROH', 'capacity': 2, 'max_adults': 2, 'max_children': 1,
            'base_rate': 900000.0, 'is_roh': True})
        res = self.env['hotel.reservation'].new(dict(
            self.vals, room_type_id=roh.id, room_id=False, adults=6))
        res._check_room_occupancy()      # no room yet: nothing to judge
        res.room_id = self.room          # given a room: that room's limits apply
        with self.assertRaises(ValidationError):
            res._check_room_occupancy()

    def test_room_type_limits_are_consistent(self):
        with self.assertRaises(ValidationError):
            self.room_type.write({'max_adults': 5})
        with self.assertRaises(ValidationError):
            self.room_type.write({'max_adults': 0})
        with self.assertRaises(ValidationError):
            self.room_type.write({'max_children': 5})

    def test_exemption_hook(self):
        res = self.env['hotel.reservation'].with_context(
            hotel_skip_occupancy_check=True).create(dict(self.vals, adults=9))
        self.assertEqual(res.adults, 9)
