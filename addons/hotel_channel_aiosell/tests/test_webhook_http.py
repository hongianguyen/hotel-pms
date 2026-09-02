# -*- coding: utf-8 -*-
"""The webhook over real HTTP.

These go through the router rather than calling the model, because the two
things most likely to break are invisible at model level: the exact shape of
the response body, and the fact that an ``auth='none'`` request arrives with no
user and therefore no company.
"""
import base64
import json
from datetime import timedelta

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestWebhookHttp(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from odoo import fields
        cls.today = fields.Date.context_today(cls.env['hotel.room'])
        cls.room_type = cls.env['hotel.room.type'].create({
            'name': 'AIO HTTP Type', 'capacity': 2, 'base_rate': 500000.0,
        })
        cls.env['hotel.room'].create({
            'name': 'AIO-HTTP-1', 'room_type_id': cls.room_type.id,
            'status': 'available',
        })
        cls.config = cls.env['aiosell.config'].create({
            'name': 'AIO HTTP', 'hotel_code': 'aio-http-hotel',
            'pms_slug': 'aio-http-pms', 'api_user': 'u', 'api_password': 'p',
            'inbound_user': 'hook', 'inbound_password': 's3cr3t',
        })
        cls.env['aiosell.room.mapping'].create({
            'config_id': cls.config.id, 'room_code': 'httproom',
            'room_type_id': cls.room_type.id,
        })
        cls.env.cr.flush()

    def _post(self, payload, auth='hook:s3cr3t'):
        headers = {'Content-Type': 'application/json'}
        if auth:
            token = base64.b64encode(auth.encode()).decode()
            headers['Authorization'] = f'Basic {token}'
        return self.url_open(
            '/aiosell/reservation', data=json.dumps(payload).encode(),
            headers=headers, timeout=30)

    def _booking(self):
        checkin = self.today + timedelta(days=4)
        return {
            'action': 'book', 'hotelCode': 'aio-http-hotel',
            'channel': 'Agoda', 'bookingId': 'HTTP-1', 'pah': False,
            'checkin': str(checkin), 'checkout': str(checkin + timedelta(days=1)),
            'guest': {'firstName': 'Http', 'lastName': 'Tester'},
            'rooms': [{
                'roomCode': 'httproom', 'rateplanCode': 'httproom-d-ep',
                'occupancy': {'adults': 1, 'children': 0},
                'prices': [{'date': str(checkin), 'sellRate': 700000.0}],
            }],
        }

    def test_response_is_a_bare_json_object(self):
        """Aiosell reads success/message at the top level.

        A jsonrpc route would wrap this in {"jsonrpc": ..., "result": {...}}
        and every delivery would look malformed to them.
        """
        response = self._post(self._booking())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body) & {'jsonrpc', 'result', 'id'}, set(),
                         'The reply must not be JSON-RPC wrapped.')
        self.assertIs(body['success'], True)
        self.assertIn('message', body)

    def test_reservation_gets_a_real_number(self):
        """auth='none' carries no company, and ir.sequence filters by company:
        get this wrong and every OTA booking is numbered 'New'."""
        self._post(self._booking())
        reservation = self.env['hotel.reservation'].search(
            [('aiosell_booking_id', '=', 'HTTP-1')])
        self.assertEqual(len(reservation), 1)
        self.assertNotEqual(reservation.reservation_number, 'New')
        self.assertTrue(reservation.reservation_number)

    def test_unauthenticated_is_rejected(self):
        response = self._post(self._booking(), auth=None)
        self.assertEqual(response.status_code, 401)
        self.assertIs(response.json()['success'], False)
        self.assertFalse(self.env['hotel.reservation'].search(
            [('aiosell_booking_id', '=', 'HTTP-1')]))

    def test_wrong_password_is_rejected(self):
        response = self._post(self._booking(), auth='hook:wrong')
        self.assertEqual(response.status_code, 401)

    def test_malformed_json_is_rejected(self):
        token = base64.b64encode(b'hook:s3cr3t').decode()
        response = self.url_open(
            '/aiosell/reservation', data=b'{not json',
            headers={'Content-Type': 'application/json',
                     'Authorization': f'Basic {token}'}, timeout=30)
        self.assertEqual(response.status_code, 400)
