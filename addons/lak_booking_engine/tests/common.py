# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo.tests import TransactionCase


class BookingEngineCase(TransactionCase):
    """A room type of our own, far enough ahead that the real bookings on
    the database cannot touch it. Every assertion reads our type only."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quote = cls.env['lak.booking.quote']
        cls.Availability = cls.env['hotel.availability']
        # 400 days out: past every imported booking, inside the horizon.
        cls.start = cls.Quote._hotel_today() + timedelta(days=400)
        cls.room_type = cls.env['hotel.room.type'].create({
            'name': 'ZZ Engine Tent',
            'capacity': 2,
            'base_rate': 1500000.0,
        })
        cls.rooms = cls.env['hotel.room'].create([{
            'name': 'ZZE-%02d' % i,
            'room_type_id': cls.room_type.id,
            'status': 'available',
        } for i in range(3)])
        cls.guest = cls.env['res.partner'].create({'name': 'ZZ Engine Guest'})

    def _book(self, **overrides):
        vals = {
            'guest_id': self.guest.id,
            'room_type_id': self.room_type.id,
            'checkin_date': self.start,
            'checkout_date': self.start + timedelta(days=2),
            'send_confirmation': False,
        }
        vals.update(overrides)
        return self.env['hotel.reservation'].create(vals)

    def _free(self, nights=2, draft_holds=True):
        return self.Availability.free_for_stay(
            self.start, self.start + timedelta(days=nights),
            draft_holds=draft_holds)[self.room_type.id]
