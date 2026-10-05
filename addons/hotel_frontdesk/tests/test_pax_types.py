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
            'name': 'ZZ Pax Tent', 'capacity': 2, 'base_rate': 1000000.0})
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
