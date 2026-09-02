# -*- coding: utf-8 -*-
import base64
import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import AiosellCase


class _Response:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body) if body is not None else 'not json'

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._body is None:
            raise ValueError('no json')
        return self._body


@tagged('post_install', '-at_install')
class TestClient(AiosellCase):
    """The body decides success, not the HTTP status."""

    def _patch(self, response):
        return patch(
            'odoo.addons.hotel_channel_aiosell.models.aiosell_config.requests.request',
            return_value=response,
        )

    def test_basic_auth_header_is_sent(self):
        expected = base64.b64encode(b'apiuser:apipass').decode()
        self.assertEqual(self.config._auth_header(), f'Basic {expected}')

    def test_successful_push_is_logged(self):
        with self._patch(_Response(200, {'success': True, 'message': 'ok'})):
            self.config.push_inventory([{'startDate': '2026-09-02',
                                         'endDate': '2026-09-02',
                                         'rooms': []}])
        log = self.env['aiosell.sync.log'].search(
            [('config_id', '=', self.config.id)], limit=1)
        self.assertEqual(log.state, 'success')
        self.assertEqual(log.operation, 'inventory_push')

    def test_http_400_with_auth_failure_is_an_error(self):
        """Aiosell answers 400, not 401, for a bad credential.

        Caught by hand rather than with assertRaises: Odoo runs assertRaises
        inside a savepoint it rolls back, which would also undo the log row
        this asserts on.
        """
        response = _Response(400, {'success': False,
                                   'message': 'Authentication Required!'})
        raised = None
        with self._patch(response):
            try:
                self.config.push_inventory([{'startDate': '2026-09-02',
                                             'endDate': '2026-09-02',
                                             'rooms': []}])
            except UserError as exc:
                raised = exc
        self.assertIsNotNone(raised, 'A rejected push must not pass silently.')
        self.assertIn('Authentication Required', str(raised))

        log = self.env['aiosell.sync.log'].search(
            [('config_id', '=', self.config.id)], limit=1)
        self.assertEqual(log.state, 'error')
        self.assertEqual(log.http_status, 400)
        self.assertIn('Authentication Required', log.note)

    def test_success_false_on_http_200_is_still_a_failure(self):
        response = _Response(200, {'success': False, 'message': 'bad room code'})
        with self._patch(response), self.assertRaises(UserError):
            self.config.push_rates([{'startDate': '2026-09-02',
                                     'endDate': '2026-09-02', 'rates': []}])

    def test_empty_update_list_makes_no_call(self):
        with self._patch(_Response(200, {'success': True})) as mocked:
            self.assertIsNone(self.config.push_inventory([]))
            mocked.assert_not_called()

    def test_missing_credentials_are_reported_before_any_call(self):
        self.config.api_password = False
        with self.assertRaises(UserError) as caught:
            self.config.push_inventory([{'startDate': '2026-09-02',
                                         'endDate': '2026-09-02', 'rooms': []}])
        self.assertIn('API Password', str(caught.exception))

    def test_restrictions_need_a_channel_list(self):
        self.config.restriction_channels = ''
        with self._patch(_Response(200, {'success': True})) as mocked:
            self.assertIsNone(self.config.push_restrictions([{'a': 1}]))
            mocked.assert_not_called()

    def test_import_mapping_refuses_a_currency_mismatch(self):
        """Rates travel as bare numbers, so the currencies must agree."""
        body = {
            'hotel_id': 'aio-test-hotel', 'hotel_name': 'Test',
            'currency': 'INR', 'rooms': [],
        }
        with self._patch(_Response(200, body)), \
                self.assertRaises(UserError) as caught:
            self.config.action_import_mapping()
        self.assertIn('INR', str(caught.exception))

    def test_import_mapping_creates_and_matches_codes(self):
        body = {
            'hotel_id': 'aio-test-hotel',
            'currency': self.env.company.currency_id.name,
            'rooms': [{
                'room_id': 'newcode',
                'room_name': 'AIO Tent',
                'count': 4,
                'rateplans': [{'rateplan_id': 'newcode-d-ep',
                               'rateplan_name': 'AIO Standard',
                               'occupancy': 2}],
            }],
        }
        with self._patch(_Response(200, body)):
            self.config.action_import_mapping()
        mapping = self.env['aiosell.room.mapping'].search([
            ('config_id', '=', self.config.id), ('room_code', '=', 'newcode'),
        ])
        self.assertEqual(mapping.room_type_id, self.type_tent,
                         'Matched to the PMS room type by name.')
        self.assertEqual(mapping.remote_count, 4)
        rate = self.env['aiosell.rateplan.mapping'].search([
            ('config_id', '=', self.config.id),
            ('rateplan_code', '=', 'newcode-d-ep'),
        ])
        self.assertEqual(rate.rate_plan_id, self.plan)
        self.assertEqual(rate.room_mapping_id, mapping)

    def test_fetch_reservations_uses_the_singular_selector(self):
        """The dataset selector is "reservation", not "reservations"."""
        with self._patch(_Response(200, [])) as mocked:
            self.config.fetch_data('reservation', self.today, self.today)
        payload = mocked.call_args.kwargs['json']
        self.assertEqual(payload['type'], 'reservation')
        self.assertEqual(payload['hotelCode'], 'aio-test-hotel')
