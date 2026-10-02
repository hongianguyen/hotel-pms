# -*- coding: utf-8 -*-
"""Public search API for the camp website's booking engine.

``type='http'`` returning bare JSON, as in ``lak_guest_order``: not
``type='jsonrpc'``, which would wrap every reply in Odoo's envelope.

These routes only READ, so they run on a read-only cursor and allow the
www origin in CORS. The booking routes that come next must NOT simply trust
the same origins: www.laktentedcamp.com is a WordPress site that had a
visitor-side JavaScript loader injected into it in 2026, so anything
it sends has to be checked server-side (re-priced, re-counted, bot-checked).

Every response is ``Cache-Control: no-store`` so Cloudflare never serves one
guest yesterday's availability.
"""
import json
import logging
import time
from collections import defaultdict, deque

from odoo import http
from odoo.http import request

from ..models.booking_quote import BookingInputError

_logger = logging.getLogger(__name__)

RATE_MAX = 60            # searches ...
RATE_WINDOW = 300        # ... per IP per 5 minutes

# Per-worker, so with N workers the real ceiling is N*RATE_MAX. It stops a
# runaway script on one connection; the real limit belongs in a Cloudflare
# rate-limiting rule on /api/book/*.
_RECENT = defaultdict(deque)

LANGS = {'en': 'en_US', 'vi': 'vi_VN'}


class LakBookingEngine(http.Controller):

    # ------------------------------------------------------------------ util
    def _param(self, key, default=''):
        return (request.env['ir.config_parameter'].sudo()
                .get_param('lak_booking_engine.%s' % key) or default).strip()

    def _enabled(self):
        # The off switch reads the table, not get_param's ormcache. A change
        # made outside a request (odoo shell, psql, another worker's cron)
        # never signals the other workers' caches, and a kill switch that
        # needs a restart to bite is not a kill switch.
        request.env.cr.execute(
            "SELECT value FROM ir_config_parameter WHERE key = %s",
            ('lak_booking_engine.enabled',))
        row = request.env.cr.fetchone()
        return bool(row) and (row[0] or '').strip() in ('1', 'true', 'True')

    def _headers(self):
        origin = request.httprequest.headers.get('Origin')
        allowed = [o.strip() for o in self._param('allowed_origins').split(',') if o.strip()]
        headers = [('Content-Type', 'application/json; charset=utf-8'),
                   ('Cache-Control', 'no-store'),
                   ('Vary', 'Origin')]
        if origin and origin in allowed:
            headers += [
                ('Access-Control-Allow-Origin', origin),
                ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type'),
                ('Access-Control-Max-Age', '86400'),
            ]
        return headers

    def _reply(self, payload, status=200):
        return request.make_response(
            json.dumps(payload, ensure_ascii=False),
            headers=self._headers(), status=status)

    def _error(self, code, message, status=400):
        return self._reply({'ok': False, 'error': code, 'message': message}, status=status)

    def _rate_limited(self):
        ip = request.httprequest.remote_addr or '?'
        now = time.time()
        hits = _RECENT[ip]
        while hits and hits[0] < now - RATE_WINDOW:
            hits.popleft()
        if len(hits) >= RATE_MAX:
            return True
        hits.append(now)
        return False

    def _lang(self, kwargs):
        code = LANGS.get((kwargs.get('lang') or 'en').lower()[:2], 'en_US')
        installed = dict(request.env['res.lang'].sudo().get_installed())
        return code if code in installed else 'en_US'

    # ---------------------------------------------------------------- routes
    @http.route('/api/book/search', type='http', auth='public', methods=['GET', 'OPTIONS'],
                csrf=False, readonly=True, save_session=False)
    def search(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._reply({})
        if not self._enabled():
            return self._error('disabled', 'Online booking is not open yet.', status=503)
        if self._rate_limited():
            return self._error('rate_limited', 'Too many searches, please wait a few minutes.', status=429)
        Quote = request.env['lak.booking.quote'].sudo().with_context(lang=self._lang(kwargs))
        try:
            result = Quote.search_offers(
                kwargs.get('checkin'), kwargs.get('checkout'),
                kwargs.get('adults', 2), kwargs.get('children', 0))
        except BookingInputError as e:
            return self._error(e.code, str(e))
        except Exception:
            _logger.exception('Booking engine search failed for %s', kwargs)
            return self._error('server_error', 'Search failed, please try again.', status=500)
        return self._reply(dict(result, ok=True))
