# -*- coding: utf-8 -*-
import logging
import re

import requests

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Accepted Vietnamese tax-code shapes, matching base_vat's own VN validator:
# 10 digits (enterprise), 10+3 with a branch suffix, or a 12-digit personal
# tax ID (CCCD, used as a tax ID since 01/07/2025). base_vat is NOT installed
# on our databases, so we carry the check ourselves rather than depend on it.
VN_TAX_CODE_RE = re.compile(r'^\d{10}(?:-?\d{3})?$|^\d{12}$')

# A Vietnamese national significant number is 9 digits: the subscriber part
# once the trunk '0' or the '+84' country code is stripped.
VN_NSN_LEN = 9

# Below this many digits a suffix match stops being a match and starts being
# a scan of half the address book.
MIN_PHONE_MATCH_DIGITS = 8

DEFAULT_TAXCODE_API_URL = 'https://api.vietqr.io/v2/business/'
# Generous on purpose. A tax code the service already knows comes back in
# ~0.3s, but one it does not is referred upstream to the GDT and has been
# measured at 1.3-9.3s. That slow path is exactly the "no such company"
# answer the user is waiting for, so a tight timeout would report every
# unknown tax code as a lookup failure.
DEFAULT_TAXCODE_API_TIMEOUT = 15.0


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_hotel_agency = fields.Boolean(
        'Travel Agency / Corporate Account',
        help='This company sends bookings to the hotel. Invoices for its '
             'bookings are issued to the company, not to the staying guests.',
    )
    hotel_account_type_id = fields.Many2one(
        'hotel.account.type', string='Account Type',
        domain="[('is_direct', '=', False)]",
        default=lambda self: self.env.ref(
            'hotel_frontdesk.account_type_travel_agent', raise_if_not_found=False),
        help='Which rate plans this account books on: a rate plan can be '
             'limited to one account type. Manage the list under Hotel > '
             'Configuration > Account Types.')
    hotel_credit_term = fields.Boolean(
        'Credit Terms',
        help='The hotel extends credit to this account: its bookings can '
             'check in without prepayment and the invoice is payable per the '
             'payment terms set on this partner. Without credit terms, '
             'prepayment is required before check-in.',
    )
    hotel_routing = fields.Selection([
        ('room', 'Room & Tax only'),
        ('all', 'All charges'),
        ('none', 'Nothing — guest settles everything'),
    ], string='Routing Instructions', default='room', required=True,
        help='Standing routing instructions for this account: which charges '
             'move to the company folio (city ledger) instead of the guest '
             'folio.\n'
             '- Room & Tax only: the company pays accommodation, the guest '
             'settles incidentals (F&B, tours) on departure.\n'
             '- All charges: everything routes to the company folio.\n'
             '- Nothing: no company folio is opened; the guest settles the '
             'whole bill.')

    hotel_total_stays = fields.Integer(
        'Total Stays', compute='_compute_hotel_stats',
        help='Number of completed (checked-out) stays.',
    )
    hotel_total_spent = fields.Float(
        'Total Spent', compute='_compute_hotel_stats', digits=(16, 2),
        help='Sum of all folio totals for this guest.',
    )

    def _compute_hotel_stats(self):
        Reservation = self.env['hotel.reservation']
        Folio = self.env['hotel.folio']
        stays = Reservation.read_group(
            [('guest_id', 'in', self.ids), ('state', '=', 'checked_out')],
            ['guest_id'], ['guest_id'],
        )
        stay_map = {g['guest_id'][0]: g['guest_id_count'] for g in stays}
        spent = Folio.read_group(
            [('guest_id', 'in', self.ids)],
            ['guest_id', 'total_amount'], ['guest_id'],
        )
        spent_map = {g['guest_id'][0]: g['total_amount'] for g in spent}
        for partner in self:
            partner.hotel_total_stays = stay_map.get(partner.id, 0)
            partner.hotel_total_spent = spent_map.get(partner.id, 0.0)

    # ── Lookup helpers: find a partner reception already has ─────────────
    #
    # Two entry points for the front desk, both "type what the caller told
    # you and get the customer back": a phone number for individuals, a tax
    # code for companies. The tax-code path additionally falls through to the
    # Vietnamese business registry when we have never seen the company.

    @api.model
    def _vn_phone_key(self, raw):
        """Comparable key for a phone number, or False if too short to match.

        Reduces a number to its national significant digits so that
        ``0912 345 678``, ``+84912345678`` and ``84.912.345.678`` all compare
        equal. Foreign numbers keep their own digits and simply compare by
        suffix, which is good enough for finding a returning guest.
        """
        digits = re.sub(r'[^0-9]', '', raw or '')
        if digits.startswith('84') and len(digits) == VN_NSN_LEN + 2:
            digits = digits[2:]
        elif digits.startswith('0'):
            digits = digits.lstrip('0')
        if len(digits) < MIN_PHONE_MATCH_DIGITS:
            return False
        return digits[-VN_NSN_LEN:]

    @api.model
    def _vn_find_by_phone(self, raw):
        """Individuals whose phone matches ``raw``, ignoring formatting.

        Stored numbers are free text — spaces, dots, country codes — so the
        comparison strips non-digits in SQL rather than trying to express it
        as a domain.
        """
        key = self._vn_phone_key(raw)
        if not key:
            return self.browse()
        self.env.cr.execute(
            """
            SELECT id FROM res_partner
             WHERE active
               AND COALESCE(is_company, FALSE) = FALSE
               AND phone IS NOT NULL
               AND RIGHT(REGEXP_REPLACE(phone, '[^0-9]', '', 'g'), %s) = %s
             ORDER BY id
             LIMIT 10
            """,
            (len(key), key),
        )
        return self.browse([r[0] for r in self.env.cr.fetchall()])

    @api.model
    def _vn_normalize_vat(self, raw):
        """Tax code stripped of whitespace.

        Matches how l10n_vn_einvoice_hoadon30s normalizes it, so the two
        modules agree on what counts as the same tax code.
        """
        return (raw or '').replace(' ', '').strip()

    @api.model
    def _vn_find_by_vat(self, raw):
        """Companies already on file under this tax code."""
        vat = self._vn_normalize_vat(raw)
        if not vat:
            return self.browse()
        return self.search([('vat', '=', vat)], limit=1)

    @api.model
    def _vn_lookup_tax_code(self, raw):
        """Fetch a company from the Vietnamese business registry.

        Returns the registry payload as a dict, or None when the tax code is
        simply not registered. Raises UserError when the registry could not
        be reached or answered with something unusable — the caller decides
        whether that surfaces as a dialog or an onchange warning.
        """
        vat = self._vn_normalize_vat(raw)
        if not VN_TAX_CODE_RE.match(vat):
            raise UserError(_(
                '%s is not a valid Vietnamese tax code. Expected 10 digits, '
                '10 digits with a 3-digit branch suffix, or a 12-digit '
                'personal tax ID.'
            ) % vat)

        params = self.env['ir.config_parameter'].sudo()
        url = params.get_param('hotel.vn_taxcode_api_url', DEFAULT_TAXCODE_API_URL)
        try:
            timeout = float(params.get_param(
                'hotel.vn_taxcode_api_timeout', DEFAULT_TAXCODE_API_TIMEOUT))
        except (TypeError, ValueError):
            timeout = DEFAULT_TAXCODE_API_TIMEOUT

        try:
            response = requests.get(
                url + vat, timeout=timeout,
                headers={'Accept': 'application/json'},
            )
        except requests.exceptions.Timeout:
            raise UserError(_(
                'The tax registry did not answer within %ss. Please try '
                'again, or enter the company details by hand.'
            ) % timeout)
        except requests.exceptions.RequestException as err:
            _logger.warning('VN tax code lookup failed for %s: %s', vat, err)
            raise UserError(_(
                'Could not reach the Vietnamese tax registry. Please try '
                'again, or enter the company details by hand.'
            ))

        if response.status_code == 429:
            raise UserError(_(
                'The tax registry is rate-limiting us. Please wait a moment '
                'and try again.'
            ))
        if response.status_code != 200:
            _logger.warning('VN tax code lookup for %s returned HTTP %s',
                            vat, response.status_code)
            raise UserError(_(
                'The Vietnamese tax registry returned an error (HTTP %s).'
            ) % response.status_code)

        try:
            payload = response.json()
        except ValueError:
            raise UserError(_(
                'The Vietnamese tax registry returned a response we could '
                'not read.'
            ))

        # A tax code that does not exist comes back as HTTP 200 with code
        # "51" and a null payload, so the body decides, not the status line.
        if payload.get('code') != '00' or not payload.get('data'):
            return None
        return payload['data']

    @api.model
    def _vn_registry_partner_vals(self, data):
        """Partner values for a company as the registry describes it."""
        vietnam = self.env.ref('base.vn', raise_if_not_found=False)
        notes = [
            label % value for label, value in (
                (_('International name: %s'), data.get('internationalName')),
                (_('Short name: %s'), data.get('shortName')),
                (_('Tax status: %s'), data.get('status')),
            ) if value
        ]
        return {
            'name': data.get('name') or data.get('id'),
            'vat': data.get('id'),
            'street': data.get('address') or False,
            'is_company': True,
            'country_id': vietnam.id if vietnam else False,
            'comment': '\n'.join(notes) or False,
        }

    @api.model
    def _vn_find_or_create_by_vat(self, raw, extra_vals=None):
        """The company for this tax code, from our books or the registry.

        Returns an empty recordset when the registry has never heard of the
        tax code either — the caller then knows to ask reception to key the
        company in by hand.
        """
        partner = self._vn_find_by_vat(raw)
        if partner:
            return partner
        data = self._vn_lookup_tax_code(raw)
        if not data:
            return self.browse()
        vals = self._vn_registry_partner_vals(data)
        vals.update(extra_vals or {})
        return self.create(vals)

    # ── Filling a new company in from its tax code ───────────────────────

    @api.onchange('vat')
    def _onchange_vat_fill_from_registry(self):
        """Fill a company in from the Vietnamese business registry.

        Typing a tax code on a company is the fastest way to create it:
        the registered name, address and country arrive from the registry
        rather than being keyed in by hand.

        Only blank fields are filled. A value already typed is never
        overwritten — if it disagrees with the registry the difference is
        reported instead, so reception decides which is right.
        """
        self.ensure_one()
        if not self.is_company:
            return
        vat = self._vn_normalize_vat(self.vat)
        if not vat or not VN_TAX_CODE_RE.match(vat):
            # Half-typed or non-Vietnamese: say nothing rather than nag on
            # every keystroke.
            return

        # A tax code identifies a company uniquely, so a second record under
        # the same one is a duplicate in the making.
        duplicate = self.search([
            ('vat', '=', vat), ('id', '!=', self._origin.id or 0),
        ], limit=1)
        if duplicate:
            return {'warning': {
                'title': _('This company is already on file'),
                'message': _(
                    '%(name)s already uses tax code %(vat)s. Use that record '
                    'rather than creating a second one.',
                    name=duplicate.display_name, vat=vat,
                ),
            }}

        try:
            data = self._vn_lookup_tax_code(vat)
        except UserError as err:
            # An unreachable registry must not stop anyone creating a company.
            return {'warning': {
                'title': _('Tax registry lookup failed'),
                'message': err.args[0] if err.args else _('Unknown error.'),
            }}

        if not data:
            return {'warning': {
                'title': _('Tax code not found'),
                'message': _(
                    'The Vietnamese business registry does not recognise tax '
                    'code %s. Please check the number, or fill the company in '
                    'by hand.'
                ) % vat,
            }}

        vals = self._vn_registry_partner_vals(data)
        kept = []
        for field, value in vals.items():
            if not value or field == 'vat':
                continue
            current = self[field]
            if not current:
                self[field] = value
            elif field == 'name' and current != value:
                # The name is the one field people type before the tax code.
                kept.append(value)

        if kept:
            return {'warning': {
                'title': _('Registered under a different name'),
                'message': _(
                    'The registry lists tax code %(vat)s as "%(official)s". '
                    'The name you entered has been kept.',
                    vat=vat, official=kept[0],
                ),
            }}
