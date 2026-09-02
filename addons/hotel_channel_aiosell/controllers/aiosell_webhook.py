# -*- coding: utf-8 -*-
"""The endpoint Aiosell POSTs OTA reservations to.

This is a plain REST endpoint, deliberately **not** a JSON-RPC one. Odoo's
``type='jsonrpc'`` routes wrap whatever they return in
``{"jsonrpc": "2.0", "id": ..., "result": {...}}``; Aiosell expects the bare
``{"success": true, "message": "..."}`` object and nothing around it. So the
route is ``type='http'`` and the body is built by hand.

It is unauthenticated at the Odoo level (``auth='none'``) because Aiosell has
no Odoo user, so HTTP Basic against the connection record is the entire gate.
Comparisons are constant-time, and the route is meant to sit behind an nginx
location that rate-limits and, once Aiosell's egress addresses are known,
allowlists them.
"""
import base64
import binascii
import hmac
import json
import logging

from odoo import SUPERUSER_ID, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class AiosellWebhook(http.Controller):

    def _json(self, payload, status=200):
        return request.make_json_response(payload, status=status)

    def _env(self):
        """An environment with a real user behind it.

        ``auth='none'`` leaves ``request.env`` with no user and therefore no
        company, and ``ir.sequence.next_by_code`` filters sequences by
        company — so reservations created on the bare environment come out
        numbered "New". Everything here runs as the superuser instead.
        """
        return request.env(user=SUPERUSER_ID)

    def _authenticate(self):
        """True when the request carries valid Basic credentials.

        Checked against every connection that has inbound credentials set, so
        the caller does not have to identify itself before being trusted.
        """
        header = request.httprequest.headers.get('Authorization', '')
        if not header.startswith('Basic '):
            return False
        try:
            decoded = base64.b64decode(header[6:].strip()).decode('utf-8')
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return False
        user, _sep, password = decoded.partition(':')

        configs = self._env()['aiosell.config'].sudo().search([
            ('inbound_user', '!=', False),
            ('inbound_password', '!=', False),
        ])
        # compare_digest on every candidate, no early exit, so a wrong
        # username and a wrong password cost the same.
        matched = False
        for config in configs:
            if (hmac.compare_digest(user, config.inbound_user or '')
                    and hmac.compare_digest(password, config.inbound_password or '')):
                matched = True
        return matched

    # readonly=False is required, not decorative: Odoo defaults auth='none'
    # routes to a read-only cursor (http.py, `default_auth == 'none'`), and
    # this one writes reservations. It appears to work on a server with no
    # read replica — the read-only cursor quietly falls back to the primary —
    # and starts failing the day one is added.
    @http.route(
        '/aiosell/reservation', type='http', auth='none', readonly=False,
        methods=['POST'], csrf=False, save_session=False,
    )
    def reservation(self, **kwargs):
        if not self._authenticate():
            _logger.warning(
                'Aiosell webhook: rejected unauthenticated POST from %s',
                request.httprequest.remote_addr)
            return self._json(
                {'success': False, 'message': 'Authentication Required!'},
                status=401,
            )

        try:
            payload = request.get_json_data()
        except (ValueError, TypeError):
            return self._json(
                {'success': False, 'message': 'Malformed JSON body'}, status=400)
        if not isinstance(payload, dict):
            return self._json(
                {'success': False, 'message': 'Expected a JSON object'},
                status=400)

        try:
            status, body = self._env()['aiosell.config'].sudo(
                ).handle_reservation_push(payload)
        except Exception:  # noqa: BLE001
            # Unexpected: let Aiosell retry rather than lose the booking, and
            # keep the raw payload in the log for a replay by hand.
            request.env.cr.rollback()
            _logger.exception('Aiosell webhook failed on payload: %s',
                              json.dumps(payload)[:2000])
            return self._json(
                {'success': False, 'message': 'Internal error, please retry'},
                status=500,
            )
        return self._json(body, status=status)
