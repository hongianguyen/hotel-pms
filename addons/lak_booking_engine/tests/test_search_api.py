# -*- coding: utf-8 -*-
import json
from datetime import timedelta

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestSearchApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Param = cls.env['ir.config_parameter'].sudo()
        cls.start = cls.env['lak.booking.quote']._hotel_today() + timedelta(days=400)
        cls.room_type = cls.env['hotel.room.type'].create({
            'name': 'ZZ Api Tent', 'capacity': 2, 'base_rate': 1200000.0,
        })
        cls.env['hotel.room'].create({'name': 'ZZA-01', 'room_type_id': cls.room_type.id})

    def _get(self, origin=None, **params):
        params.setdefault('checkin', self.start.isoformat())
        params.setdefault('checkout', (self.start + timedelta(days=3)).isoformat())
        params.setdefault('adults', 2)
        query = '&'.join('%s=%s' % kv for kv in params.items())
        headers = {'Origin': origin} if origin else {}
        return self.url_open('/api/book/search?' + query, headers=headers)

    def test_inert_until_enabled(self):
        self.Param.set_param('lak_booking_engine.enabled', '0')
        resp = self._get()
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()['error'], 'disabled')

    def test_off_switch_bites_without_cache_signal(self):
        """Switched off behind the ORM's back (psql, odoo shell): the next
        request must already refuse."""
        self.Param.set_param('lak_booking_engine.enabled', '1')
        self.assertEqual(self._get().status_code, 200)
        self.env.cr.execute(
            "UPDATE ir_config_parameter SET value = '0' "
            "WHERE key = 'lak_booking_engine.enabled'")
        self.assertEqual(self._get().status_code, 503)

    def test_search(self):
        self.Param.set_param('lak_booking_engine.enabled', '1')
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers['Cache-Control'], 'no-store')
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['nights'], 3)
        self.assertEqual(data['currency'], 'VND')
        offer = next(o for o in data['offers'] if o['room_type_id'] == self.room_type.id)
        self.assertEqual(offer['total'], 3600000.0)
        self.assertEqual(offer['only_left'], 1)
        # Nothing about who is staying ever leaves the API.
        self.assertNotIn('guest', json.dumps(data).lower())

    def test_bad_input_is_400(self):
        self.Param.set_param('lak_booking_engine.enabled', '1')
        resp = self._get(checkin='2020-01-01')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'past_date')

    def test_cors_allowlist(self):
        self.Param.set_param('lak_booking_engine.enabled', '1')
        self.Param.set_param('lak_booking_engine.allowed_origins',
                             'https://www.laktentedcamp.com')
        ok = self._get(origin='https://www.laktentedcamp.com')
        self.assertEqual(ok.headers.get('Access-Control-Allow-Origin'),
                         'https://www.laktentedcamp.com')
        evil = self._get(origin='https://evil.example')
        self.assertNotIn('Access-Control-Allow-Origin', evil.headers)
