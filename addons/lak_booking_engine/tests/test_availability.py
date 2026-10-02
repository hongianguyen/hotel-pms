# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo.tests import tagged

from .common import BookingEngineCase


@tagged('post_install', '-at_install')
class TestAvailability(BookingEngineCase):

    def test_all_free(self):
        self.assertEqual(self._free(), 3)

    def test_assigned_room_is_taken(self):
        self._book(room_id=self.rooms[0].id, state='confirmed')
        self.assertEqual(self._free(), 2)

    def test_unassigned_booking_still_counts(self):
        """The case get_available_rooms misses: a promise with no room yet."""
        self._book(state='confirmed')
        self.assertEqual(self._free(), 2)

    def test_draft_holds_inventory(self):
        self._book()
        self.assertEqual(self._free(), 2)
        self.assertEqual(self._free(draft_holds=False), 3)

    def test_cancelled_releases(self):
        res = self._book(room_id=self.rooms[0].id, state='confirmed')
        res.state = 'cancelled'
        self.assertEqual(self._free(), 3)

    def test_partial_overlap_takes_the_whole_stay(self):
        """Free for the stay = free on EVERY night, so a booking on the
        second night alone still blocks a two-night search."""
        self._book(room_id=self.rooms[0].id, state='confirmed',
                   checkin_date=self.start + timedelta(days=1),
                   checkout_date=self.start + timedelta(days=3))
        self.assertEqual(self._free(nights=1), 3)
        self.assertEqual(self._free(nights=2), 2)

    def test_maintenance_window(self):
        self.rooms[1].write({
            'maintenance_date_from': self.start + timedelta(days=1),
            'maintenance_date_to': self.start + timedelta(days=1),
        })
        self.assertEqual(self._free(nights=1), 3)
        self.assertEqual(self._free(nights=2), 2)

    def test_bare_maintenance_status_is_out(self):
        self.rooms[2].status = 'maintenance'
        self.assertEqual(self._free(), 2)

    def test_roh_comes_out_of_the_roomiest_type(self):
        big = self.env['hotel.room.type'].create({
            'name': 'ZZ Engine Big', 'capacity': 2, 'base_rate': 1.0,
        })
        self.env['hotel.room'].create([{
            'name': 'ZZB-%02d' % i, 'room_type_id': big.id,
        } for i in range(40)])
        roh = self.env['hotel.room.type'].create({
            'name': 'ZZ Engine ROH', 'capacity': 2, 'base_rate': 1.0,
            'is_roh': True,
        })
        group = self.env['hotel.booking.group'].create({
            'guest_id': self.guest.id,
            'checkin_date': self.start,
            'checkout_date': self.start + timedelta(days=2),
        })
        self._book(room_type_id=roh.id, group_id=group.id, state='confirmed')
        free = self.Availability.free_for_stay(self.start, self.start + timedelta(days=2))
        self.assertEqual(free[big.id], 39)
        self.assertEqual(free[self.room_type.id], 3)
        self.assertNotIn(roh.id, free)

    def test_never_negative(self):
        for _i in range(5):
            self._book(state='confirmed')
        self.assertEqual(self._free(), 0)
