# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo.tests import tagged

from .common import AiosellCase


@tagged('post_install', '-at_install')
class TestAvailability(AiosellCase):
    """What we tell the OTAs is sellable has to match what can be slept in."""

    def test_counts_physical_rooms_per_type(self):
        avail = self._avail()
        self.assertEqual(avail[self.type_bungalow.id][self.today], 2)
        self.assertEqual(avail[self.type_tent.id][self.today], 1)

    def test_roh_type_is_never_published(self):
        """ROH overlaps the physical types; publishing it double-sells."""
        avail = self._avail()
        self.assertNotIn(
            self.type_roh.id, avail,
            'Run-of-House is virtual and must not carry its own inventory.')

    def test_draft_booking_holds_the_room(self):
        """A phone booking left unconfirmed must not be resold by an OTA."""
        self.env['hotel.reservation'].create({
            'guest_id': self.guest.id,
            'room_type_id': self.type_bungalow.id,
            'room_id': self.bungalows[0].id,
            'checkin_date': self.today,
            'checkout_date': self.today + timedelta(days=2),
        })
        avail = self._avail()
        self.assertEqual(avail[self.type_bungalow.id][self.today], 1)
        self.assertEqual(
            avail[self.type_bungalow.id][self.today + timedelta(days=2)], 2,
            'The night of departure is free again.')

    def test_draft_can_be_told_not_to_hold(self):
        self.config.draft_holds_inventory = False
        self.env['hotel.reservation'].create({
            'guest_id': self.guest.id,
            'room_type_id': self.type_bungalow.id,
            'room_id': self.bungalows[0].id,
            'checkin_date': self.today,
            'checkout_date': self.today + timedelta(days=2),
        })
        self.assertEqual(self._avail()[self.type_bungalow.id][self.today], 2)

    def test_unassigned_booking_still_holds_its_type(self):
        self.env['hotel.reservation'].create({
            'guest_id': self.guest.id,
            'room_type_id': self.type_bungalow.id,
            'checkin_date': self.today,
            'checkout_date': self.today + timedelta(days=1),
        })
        self.assertEqual(self._avail()[self.type_bungalow.id][self.today], 1)

    def test_unassigned_roh_takes_a_room_from_the_pool(self):
        """ROH could land on any physical type, so it must cost the house one
        sellable room somewhere — measured across every type, because this
        database also holds the real property's rooms."""
        before = sum(v[self.today] for v in self._avail().values())
        group = self.env['hotel.booking.group'].create({
            'guest_id': self.guest.id,
            'checkin_date': self.today,
            'checkout_date': self.today + timedelta(days=1),
        })
        self.env['hotel.reservation'].create({
            'guest_id': self.guest.id,
            'room_type_id': self.type_roh.id,
            'group_id': group.id,
            'checkin_date': self.today,
            'checkout_date': self.today + timedelta(days=1),
        })
        after = sum(v[self.today] for v in self._avail().values())
        self.assertEqual(after, before - 1)
        self.assertNotIn(self.type_roh.id, self._avail())

    def test_maintenance_window_removes_the_room(self):
        self.bungalows[0].write({
            'status': 'maintenance',
            'maintenance_date_from': self.today,
            'maintenance_date_to': self.today,
        })
        avail = self._avail()
        self.assertEqual(avail[self.type_bungalow.id][self.today], 1)
        self.assertEqual(
            avail[self.type_bungalow.id][self.today + timedelta(days=1)], 2,
            'The window is over, so the room is sellable again.')

    def test_availability_never_goes_negative(self):
        for room in self.bungalows:
            self.env['hotel.reservation'].create({
                'guest_id': self.guest.id,
                'room_type_id': self.type_bungalow.id,
                'room_id': room.id,
                'checkin_date': self.today,
                'checkout_date': self.today + timedelta(days=1),
            })
        self.env['hotel.reservation'].create({
            'guest_id': self.guest.id,
            'room_type_id': self.type_bungalow.id,
            'checkin_date': self.today,
            'checkout_date': self.today + timedelta(days=1),
        })
        self.assertEqual(self._avail()[self.type_bungalow.id][self.today], 0)

    def test_blocks_collapse_and_split_on_change(self):
        """Identical nights become one block; a booking splits the range."""
        start, end = self.today, self.today + timedelta(days=5)
        self.assertEqual(
            len(self.config._build_inventory_updates(start, end)), 1,
            'Five identical nights are one block, not five.')

        self.env['hotel.reservation'].create({
            'guest_id': self.guest.id,
            'room_type_id': self.type_bungalow.id,
            'room_id': self.bungalows[0].id,
            'checkin_date': self.today + timedelta(days=2),
            'checkout_date': self.today + timedelta(days=3),
        })
        blocks = self.config._build_inventory_updates(start, end)
        self.assertEqual(len(blocks), 3, 'before / during / after the stay')
        middle = blocks[1]
        self.assertEqual(middle['startDate'], str(self.today + timedelta(days=2)))
        self.assertEqual(middle['endDate'], str(self.today + timedelta(days=2)))
        self.assertEqual(
            sorted(middle['rooms'], key=lambda r: r['roomCode']),
            [{'roomCode': 'bungalow', 'available': 1},
             {'roomCode': 'tent', 'available': 1}],
        )

    def test_unmapped_room_types_are_not_pushed(self):
        self.map_tent.room_type_id = False
        blocks = self.config._build_inventory_updates(
            self.today, self.today + timedelta(days=1))
        codes = {r['roomCode'] for r in blocks[0]['rooms']}
        self.assertEqual(codes, {'bungalow'})
