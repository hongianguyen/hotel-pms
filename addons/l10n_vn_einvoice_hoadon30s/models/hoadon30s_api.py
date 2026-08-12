# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TIMEOUT = 30

# Invoice status at the provider / tax authority (statusInv, invoice "status").
EINVOICE_STATUSES = [
    ('draft', 'Created'),
    ('signed', 'Signed'),
    ('sent', 'Sent to Tax Authority'),
    ('coded', 'Tax Code Granted'),
    ('replaced', 'Replaced'),
    ('adjusted', 'Adjusted'),
    ('cancelled', 'Cancelled'),
    ('rejected', 'Code Refused'),
    ('error', 'Error'),
]
STATUS_BY_CODE = {
    0: 'draft', 1: 'signed', 2: 'sent', 3: 'coded',
    4: 'replaced', 5: 'adjusted', 6: 'cancelled', 7: 'rejected',
}
# Once one of these is reached there is nothing left to poll for.
FINAL_STATUSES = ('coded', 'replaced', 'adjusted', 'cancelled', 'rejected')


def fmt_number(value):
    """Format a float as the API's string-typed money/qty fields expect."""
    s = f'{value:.2f}'.rstrip('0').rstrip('.')
    return s or '0'


class Hoadon30sApi(models.AbstractModel):
    _name = 'hoadon30s.api'
    _description = 'hoadon30s.vn E-Invoice API Client'

    @api.model
    def _get_param(self, key, default=''):
        return self.env['ir.config_parameter'].sudo().get_param(
            'hoadon30s.%s' % key, default)

    @api.model
    def _get_base_url(self):
        return self._get_param(
            'base_url', 'https://cphoadonuat.hoadon30s.vn').rstrip('/')

    @api.model
    def _is_configured(self):
        return bool(self._get_param('client_id')
                    and self._get_param('client_secret'))

    @api.model
    def _get_token(self, force=False):
        """Return a valid OAuth2 access token, requesting a new one if needed.

        Tokens live 15 days; refresh one day early so a token can never
        expire mid-flow.
        """
        icp = self.env['ir.config_parameter'].sudo()
        token = icp.get_param('hoadon30s.access_token')
        expiry = icp.get_param('hoadon30s.token_expiry')
        if token and expiry and not force:
            expiry_dt = fields.Datetime.from_string(expiry)
            if expiry_dt - timedelta(days=1) > fields.Datetime.now():
                return token

        client_id = self._get_param('client_id')
        client_secret = self._get_param('client_secret')
        if not client_id or not client_secret:
            raise UserError(_(
                'The hoadon30s e-invoice service is not configured. '
                'Set the Client ID and Client Secret in '
                'Accounting → Settings → Vietnam E-Invoice.'))

        url = '%s/oauth/token' % self._get_base_url()
        try:
            resp = requests.post(url, data={
                'grant_type': 'client_credentials',
                'client_id': client_id,
                'client_secret': client_secret,
                'scope': 'create-invoice',
            }, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise UserError(_(
                'Could not reach the e-invoice service at %(url)s: %(error)s',
                url=url, error=exc)) from exc
        if resp.status_code != 200:
            raise UserError(_(
                'E-invoice authentication failed (HTTP %(code)s). '
                'Check the Client ID / Client Secret.\n%(body)s',
                code=resp.status_code, body=resp.text[:500]))
        data = resp.json()
        token = data.get('access_token')
        if not token:
            raise UserError(_(
                'E-invoice authentication returned no token: %s',
                resp.text[:500]))
        expires_in = int(data.get('expires_in') or 1296000)
        icp.set_param('hoadon30s.access_token', token)
        icp.set_param('hoadon30s.token_expiry', fields.Datetime.to_string(
            fields.Datetime.now() + timedelta(seconds=expires_in)))
        return token

    @api.model
    def _call(self, endpoint, payload):
        """POST `payload` to `endpoint` and return the decoded JSON body.

        Retries once with a fresh token on HTTP 401. Raises UserError on
        transport errors; API-level errors (status != 200 in the body) are
        the caller's to interpret — use _call_checked() to raise on those.
        """
        url = '%s/%s' % (self._get_base_url(), endpoint.lstrip('/'))
        for attempt in (1, 2):
            token = self._get_token(force=(attempt == 2))
            try:
                resp = requests.post(url, json=payload, headers={
                    'Authorization': 'Bearer %s' % token,
                }, timeout=TIMEOUT)
            except requests.RequestException as exc:
                raise UserError(_(
                    'Could not reach the e-invoice service at '
                    '%(url)s: %(error)s', url=url, error=exc)) from exc
            if resp.status_code != 401:
                break
        try:
            return resp.json()
        except ValueError as exc:
            raise UserError(_(
                'The e-invoice service returned an unreadable response '
                '(HTTP %(code)s): %(body)s',
                code=resp.status_code, body=resp.text[:500])) from exc

    @api.model
    def _call_checked(self, endpoint, payload):
        """Like _call(), but raise a readable UserError unless status == 200."""
        data = self._call(endpoint, payload)
        if data.get('status') != 200:
            detail = data.get('error')
            detail_txt = ''
            if isinstance(detail, dict):
                detail_txt = '\n'.join(
                    '%s: %s' % (field, '; '.join(map(str, msgs))
                                if isinstance(msgs, list) else msgs)
                    for field, msgs in detail.items())
            raise UserError(_(
                'E-invoice service error: %(message)s\n%(detail)s',
                message=data.get('message') or data,
                detail=detail_txt).strip())
        return data

    @api.model
    def _map_vat_rate(self, percent, has_tax):
        """Map a tax percentage to the API's vatRate (+ vatRateOther) pair.

        Returns (vatRate, vatRateOther or None). No tax at all → -1
        (không chịu thuế); a rate outside the legal 0/5/8/10 set → -3 with
        the actual rate in vatRateOther.
        """
        if not has_tax:
            return -1, None
        rate = int(percent) if float(percent).is_integer() else percent
        if rate in (0, 5, 8, 10):
            return rate, None
        return -3, rate
