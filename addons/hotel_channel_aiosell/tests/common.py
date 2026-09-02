# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tests import TransactionCase


class AiosellCase(TransactionCase):
    """A small property wired to a fully mapped Aiosell connection."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env['hotel.room'])

        RoomType = cls.env['hotel.room.type']
        cls.type_bungalow = RoomType.create({
            'name': 'AIO Bungalow', 'capacity': 2, 'base_rate': 1200000.0,
        })
        cls.type_tent = RoomType.create({
            'name': 'AIO Tent', 'capacity': 2, 'base_rate': 800000.0,
        })
        cls.type_roh = RoomType.create({
            'name': 'AIO Run of House', 'capacity': 2,
            'base_rate': 900000.0, 'is_roh': True,
        })

        Room = cls.env['hotel.room']
        cls.bungalows = Room.create([
            {'name': 'AIO-B1', 'room_type_id': cls.type_bungalow.id,
             'status': 'available'},
            {'name': 'AIO-B2', 'room_type_id': cls.type_bungalow.id,
             'status': 'available'},
        ])
        cls.tents = Room.create([
            {'name': 'AIO-T1', 'room_type_id': cls.type_tent.id,
             'status': 'available'},
        ])

        cls.plan = cls.env['hotel.rate.plan'].create({
            'name': 'AIO Standard',
            'room_type_id': cls.type_bungalow.id,
            'base_rate': 1500000.0,
            'min_stay': 1,
        })

        cls.config = cls.env['aiosell.config'].create({
            'name': 'AIO Test',
            'hotel_code': 'aio-test-hotel',
            'pms_slug': 'aio-test-pms',
            'api_user': 'apiuser',
            'api_password': 'apipass',
            'inbound_user': 'hookuser',
            'inbound_password': 'hookpass',
            'horizon_days': 5,
        })
        cls.map_bungalow = cls.env['aiosell.room.mapping'].create({
            'config_id': cls.config.id,
            'room_code': 'bungalow',
            'remote_name': 'BUNGALOW',
            'room_type_id': cls.type_bungalow.id,
        })
        cls.map_tent = cls.env['aiosell.room.mapping'].create({
            'config_id': cls.config.id,
            'room_code': 'tent',
            'remote_name': 'TENT',
            'room_type_id': cls.type_tent.id,
        })
        cls.map_rate = cls.env['aiosell.rateplan.mapping'].create({
            'config_id': cls.config.id,
            'rateplan_code': 'bungalow-d-ep',
            'remote_name': 'Room Only',
            'room_mapping_id': cls.map_bungalow.id,
            'rate_plan_id': cls.plan.id,
            'occupancy': 2,
        })
        cls.guest = cls.env['res.partner'].create({'name': 'AIO Walk In'})

    def _avail(self, days=3):
        from datetime import timedelta
        return self.config._compute_availability(
            self.today, self.today + timedelta(days=days))
