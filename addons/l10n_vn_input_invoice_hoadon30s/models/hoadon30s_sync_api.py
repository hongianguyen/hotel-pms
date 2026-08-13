# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TIMEOUT = 60

# Hard limits imposed by the provider — see the "API Download hóa đơn Đầu vào"
# spec. Exceeding them is an error, not a silent truncation, so clamp here.
MAX_PAGE_SIZE = 25
DEFAULT_PAGE_SIZE = 25
MAX_RANGE_DAYS = 31

# Guard against a runaway cursor loop if the provider keeps handing back a
# non-empty `state`. 25 * 200 = 5000 invoices is far beyond any real month.
MAX_PAGES = 200


class Hoadon30sSyncApi(models.AbstractModel):
    """Client for the hoadon30s.vn *invoice-sync* service (input invoices).

    Deliberately independent of ``hoadon30s.api`` in
    ``l10n_vn_einvoice_hoadon30s``: this is a different service with its own
    credentials, its own token endpoint (``/api/invoice-sync/token`` rather
    than ``/oauth/token``), no OAuth scope, and a metered per-invoice quota.
    Sharing either the credentials or the cached token would make the two
    clobber each other, so every config parameter here is namespaced
    ``hoadon30s.sync.*``.
    """
    _name = 'hoadon30s.sync.api'
    _description = 'hoadon30s.vn Input-Invoice Sync API Client'

    # ── Configuration ────────────────────────────────────────────────────

    @api.model
    def _get_param(self, key, default=''):
        return self.env['ir.config_parameter'].sudo().get_param(
            'hoadon30s.sync.%s' % key, default)

    @api.model
    def _get_base_url(self):
        return self._get_param(
            'base_url', 'https://cpanel.hoadon30s.vn').rstrip('/')

    @api.model
    def _is_configured(self):
        return bool(self._get_param('client_id')
                    and self._get_param('client_secret'))

    @api.model
    def _get_gdt_username(self):
        """The hoadondientu.gdt.gov.vn login, required on every download."""
        username = self._get_param('gdt_username')
        if not username:
            raise UserError(_(
                'The tax-portal user name is not set. Enter the '
                'hoadondientu.gdt.gov.vn login in Accounting → Settings → '
                'Vietnam Input Invoices, then run "Connect Tax Portal" once.'))
        return username

    # ── Authentication ───────────────────────────────────────────────────

    @api.model
    def _get_token(self, force=False):
        """Return a valid access token, requesting a new one when needed.

        Tokens live ~15 days; refresh a day early so one can never expire
        mid-download.
        """
        icp = self.env['ir.config_parameter'].sudo()
        token = icp.get_param('hoadon30s.sync.access_token')
        expiry = icp.get_param('hoadon30s.sync.token_expiry')
        if token and expiry and not force:
            if (fields.Datetime.from_string(expiry) - timedelta(days=1)
                    > fields.Datetime.now()):
                return token

        client_id = self._get_param('client_id')
        client_secret = self._get_param('client_secret')
        if not client_id or not client_secret:
            raise UserError(_(
                'The input-invoice sync service is not configured. Set the '
                'Client ID and Client Secret in Accounting → Settings → '
                'Vietnam Input Invoices.'))

        url = '%s/api/invoice-sync/token' % self._get_base_url()
        try:
            # This endpoint takes form-encoded credentials, not JSON.
            resp = requests.post(url, data={
                'grant_type': 'client_credentials',
                'client_id': client_id,
                'client_secret': client_secret,
            }, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise UserError(_(
                'Could not reach the input-invoice service at %(url)s: '
                '%(error)s', url=url, error=exc)) from exc
        if resp.status_code != 200:
            raise UserError(_(
                'Input-invoice authentication failed (HTTP %(code)s). Check '
                'the Client ID / Client Secret.\n%(body)s',
                code=resp.status_code, body=resp.text[:500]))
        data = resp.json()
        token = data.get('access_token')
        if not token:
            raise UserError(_(
                'Input-invoice authentication returned no token: %s',
                resp.text[:500]))
        expires_in = int(data.get('expires_in') or 1296000)
        icp.set_param('hoadon30s.sync.access_token', token)
        icp.set_param('hoadon30s.sync.token_expiry', fields.Datetime.to_string(
            fields.Datetime.now() + timedelta(seconds=expires_in)))
        return token

    # ── Transport ────────────────────────────────────────────────────────

    @api.model
    def _call(self, endpoint, payload):
        """POST `payload` to `endpoint`, retrying once on HTTP 401."""
        url = '%s/%s' % (self._get_base_url(), endpoint.lstrip('/'))
        for attempt in (1, 2):
            token = self._get_token(force=(attempt == 2))
            try:
                resp = requests.post(url, json=payload, headers={
                    'Authorization': 'Bearer %s' % token,
                }, timeout=TIMEOUT)
            except requests.RequestException as exc:
                raise UserError(_(
                    'Could not reach the input-invoice service at %(url)s: '
                    '%(error)s', url=url, error=exc)) from exc
            if resp.status_code != 401:
                break
        try:
            return resp.json()
        except ValueError as exc:
            raise UserError(_(
                'The input-invoice service returned an unreadable response '
                '(HTTP %(code)s): %(body)s',
                code=resp.status_code, body=resp.text[:500])) from exc

    @api.model
    def _call_checked(self, endpoint, payload):
        """Like _call(), but raise a readable UserError unless status == 200."""
        data = self._call(endpoint, payload)
        if data.get('status') != 200:
            raise UserError(_(
                'Input-invoice service error: %s',
                data.get('message') or data))
        return data

    # ── Endpoints ────────────────────────────────────────────────────────

    @api.model
    def connect_gdt(self, username, password):
        """Link the company's tax-portal account. Needed once, and again
        whenever the portal password changes."""
        data = self._call_checked('api/invoice-sync/v1/connect', {
            'userName': username,
            'passWord': password,
        })
        # Only the user name is stored — the portal password is used for this
        # one call and deliberately never persisted.
        self.env['ir.config_parameter'].sudo().set_param(
            'hoadon30s.sync.gdt_username', username)
        return data

    @api.model
    def get_used_amount(self, date_from=None, date_to=None):
        """Return the download quota (total / used / remaining)."""
        payload = {}
        if date_from:
            payload['from_date'] = fields.Date.to_string(date_from)
        if date_to:
            payload['to_date'] = fields.Date.to_string(date_to)
        data = self._call_checked(
            'api/invoice-sync/v1/log-download-details/used-amount', payload)
        return data.get('data') or {}

    @api.model
    def add_ip_whitelist(self, ips):
        """Restrict API access to `ips`; an empty list disables the check."""
        return self._call_checked('api/invoice-sync/v1/add-ip', {
            'ips': ips or [],
        })

    @api.model
    def download_purchase(self, date_from, date_to, mtt=False,
                          page_size=DEFAULT_PAGE_SIZE, want_pdf=False,
                          max_pages=MAX_PAGES):
        """Download input invoices issued to the company in a date range.

        Yields one page dict at a time so the caller can commit as it goes:
        downloads are billed per invoice, and a crash on page 9 must not
        throw away the eight pages already paid for.

        `mtt` selects the cash-register endpoint. The provider caps the
        range at one month and `pageSize` at 25; both are enforced here so a
        caller's over-wide request fails loudly rather than being silently
        truncated by the server.
        """
        if (date_to - date_from).days > MAX_RANGE_DAYS:
            raise UserError(_(
                'The input-invoice service accepts a date range of at most '
                'one month per download. Requested: %(from)s → %(to)s.',
                **{'from': date_from, 'to': date_to}))
        if date_to < date_from:
            raise UserError(_('The end date must not precede the start date.'))

        endpoint = 'api/invoice-sync/v1/download-purchase'
        if mtt:
            endpoint += '-mtt'
        payload = {
            'userName': self._get_gdt_username(),
            'filter': {
                'createFrom': fields.Date.to_string(date_from),
                'createTo': fields.Date.to_string(date_to),
                'isJson': 1,
                'isPdf': 1 if want_pdf else 0,
            },
            'pageSize': max(1, min(int(page_size), MAX_PAGE_SIZE)),
        }
        state = None
        for _page in range(max_pages):
            if state:
                payload['state'] = state
            data = self._call_checked(endpoint, payload)
            body = data.get('data') or {}
            yield body
            state = body.get('state')
            if not state:
                break
        else:
            _logger.warning(
                'hoadon30s input-invoice download stopped at the %s-page '
                'safety limit; some invoices may not have been fetched.',
                max_pages)
