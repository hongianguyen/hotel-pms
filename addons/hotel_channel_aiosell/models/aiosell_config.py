# -*- coding: utf-8 -*-
"""Connection to the Aiosell channel manager.

Aiosell is a channel manager, not an OTA: the PMS talks only to Aiosell, and
Aiosell fans the data out to Booking.com, Agoda, Expedia, Goibibo/MMT and the
rest. That is what makes this route workable for a single property — the direct
Booking.com Connectivity API is open to connectivity *partners* only.

Transport facts that the code below depends on:

* Every outbound call is ``POST`` with HTTP Basic auth, except the property
  lookup which is ``GET``. The credentials are issued by Aiosell.
* ``{pms}`` in the path is the partner slug Aiosell assigns to this PMS; it is
  NOT the hotel code. Both are needed.
* **The API answers HTTP 400 — not 401 — for a bad credential**, and reports
  failure in the body as ``{"success": false, "message": "..."}``. So the
  status code alone is never enough: the body is the source of truth.
"""
import base64
import json
import logging
from datetime import timedelta

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.modules import module as odoo_module

_logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = 'https://live.aiosell.com/api/v2/cm'
TIMEOUT = 30


class AiosellConfig(models.Model):
    _name = 'aiosell.config'
    _description = 'Aiosell Channel Manager Connection'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(required=True, tracking=True, default='Aiosell')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )

    # ── Outbound credentials (PMS → Aiosell) ────────────────────────────
    base_url = fields.Char(
        'API Base URL', required=True, default=DEFAULT_BASE_URL,
        help='Leave at the default unless Aiosell gave you a different host.',
    )
    pms_slug = fields.Char(
        'Partner ID (PMS slug)', tracking=True,
        help='The {pms} path segment Aiosell assigned to this PMS, e.g. '
             '"sample-pms". Not the hotel code.',
    )
    hotel_code = fields.Char(
        'Hotel Code', tracking=True,
        help='Property identifier issued by Aiosell. Sent as hotelCode in '
             'every payload and used to route inbound reservations.',
    )
    api_user = fields.Char('API Username')
    api_password = fields.Char('API Password')

    # ── Inbound credentials (Aiosell → this PMS webhook) ────────────────
    inbound_user = fields.Char(
        'Webhook Username',
        help='Basic-auth username Aiosell must present when it POSTs a '
             'reservation to this PMS. Give these to Aiosell together with '
             'the webhook URL below.',
    )
    inbound_password = fields.Char('Webhook Password')
    webhook_url = fields.Char(
        'Webhook URL', compute='_compute_webhook_url',
        help='Hand this URL to Aiosell as the reservation push endpoint.',
    )

    # ── What to sync ────────────────────────────────────────────────────
    sync_availability = fields.Boolean('Sync Availability', default=True)
    sync_rates = fields.Boolean('Sync Rates', default=True)
    sync_restrictions = fields.Boolean('Sync Restrictions', default=False)
    restriction_channels = fields.Char(
        'Restriction Channels', default='booking.com,agoda',
        help='Comma-separated channel names the restriction push targets. '
             'Aiosell rejects an empty list.',
    )
    horizon_days = fields.Integer(
        'Sync Horizon (days)', default=365,
        help='How far ahead availability and rates are pushed.',
    )
    draft_holds_inventory = fields.Boolean(
        'Draft Bookings Hold Inventory', default=True,
        help='New bookings start as draft in this PMS. With this ticked a '
             'draft booking still removes the room from what is offered to '
             'the OTAs — leave it on, or a phone booking left unconfirmed '
             'will be sold again by a channel.',
    )

    # ── Inbound behaviour ───────────────────────────────────────────────
    auto_assign_room = fields.Boolean(
        'Auto-assign Room', default=True,
        help='Pick a free room of the booked type when an OTA booking '
             'arrives. Without a room the booking cannot be confirmed and '
             'reception has to assign one by hand.',
    )
    auto_confirm_bookings = fields.Boolean(
        'Auto-Confirm OTA Bookings', default=True,
        help='Confirm inbound bookings automatically (which also opens the '
             'folio). Only possible once a room is assigned.',
    )
    send_guest_email = fields.Boolean(
        'Send Guest Confirmation Email', default=False,
        help='Off by default: the OTA already sent the guest a confirmation, '
             'and OTA e-mail addresses are usually masked relays.',
    )
    activity_user_id = fields.Many2one(
        'res.users', string='Responsible',
        help='Who gets the to-do when an OTA booking needs a human: no room '
             'free, or a change the channel sent that cannot be applied. '
             'Leave empty to assign it to whoever the sync runs as, which for '
             'inbound bookings is the system user — so set a real person.',
    )
    source_id = fields.Many2one(
        'hotel.booking.source', string='Default Booking Source',
        help='Fallback source for inbound bookings when the channel name '
             'does not match an existing source.',
    )

    # ── Mappings & bookkeeping ──────────────────────────────────────────
    room_mapping_ids = fields.One2many(
        'aiosell.room.mapping', 'config_id', string='Room Type Mapping',
    )
    rate_mapping_ids = fields.One2many(
        'aiosell.rateplan.mapping', 'config_id', string='Rate Plan Mapping',
    )
    log_ids = fields.One2many('aiosell.sync.log', 'config_id', string='Logs')
    last_push_date = fields.Datetime('Last Successful Push', readonly=True)
    last_inbound_date = fields.Datetime('Last Inbound Booking', readonly=True)
    property_currency = fields.Char(
        'Aiosell Property Currency', readonly=True,
        help='Currency Aiosell holds for this property, read back by '
             '"Import Mapping". Rates are pushed as bare numbers in this '
             'currency, so it must match the company currency.',
    )

    _hotel_code_uniq = models.Constraint(
        'UNIQUE(hotel_code, company_id)',
        'One Aiosell connection per hotel code and company.',
    )
    _horizon_positive = models.Constraint(
        'CHECK(horizon_days > 0)', 'The sync horizon must be at least 1 day.',
    )

    def _compute_webhook_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for cfg in self:
            cfg.webhook_url = f'{base}/aiosell/reservation'

    # ── HTTP plumbing ───────────────────────────────────────────────────
    def _auth_header(self):
        self.ensure_one()
        raw = f'{self.api_user or ""}:{self.api_password or ""}'
        token = base64.b64encode(raw.encode()).decode()
        return f'Basic {token}'

    def _check_ready(self):
        self.ensure_one()
        missing = [
            label for label, value in (
                ('Partner ID (PMS slug)', self.pms_slug),
                ('Hotel Code', self.hotel_code),
                ('API Username', self.api_user),
                ('API Password', self.api_password),
            ) if not value
        ]
        if missing:
            raise UserError(_(
                'Aiosell credentials are incomplete. Missing: %s.\n'
                'Ask Aiosell for these when they onboard the property.'
            ) % ', '.join(missing))

    def _write_sync_log(self, vals):
        """Record one API call, so the row survives a rolled-back request.

        An outbound call that fails raises UserError; Odoo then rolls the
        whole request transaction back, and a log row written inside it would
        go with it — losing the record of the failure at exactly the moment it
        matters. The HTTP call happened whatever the ORM decides afterwards,
        so it is committed on its own cursor.

        Inside a test the separate cursor would commit real rows into the test
        database, so there the write stays in the test transaction.
        """
        self.ensure_one()
        vals = dict(vals, config_id=self.id)
        # Read through the module, never `from ... import`: the test
        # framework rebinds this attribute at run time.
        if odoo_module.current_test:
            return self.env['aiosell.sync.log'].create(vals)
        with self.env.registry.cursor() as cr:
            return self.env(cr=cr)['aiosell.sync.log'].create(vals)

    def _call(self, path, payload=None, method='POST', operation=None):
        """One API call, logged. Returns the decoded body.

        Raises UserError on transport failure or on a body that reports
        ``success: false`` — including the HTTP-400-means-auth-failed case.
        """
        self.ensure_one()
        self._check_ready()
        url = f'{(self.base_url or DEFAULT_BASE_URL).rstrip("/")}{path}'
        headers = {'Authorization': self._auth_header()}
        if payload is not None:
            headers['Content-Type'] = 'application/json'

        log_vals = {
            'direction': 'outbound',
            'operation': operation or path,
            'endpoint': url,
            'request_body': (
                json.dumps(payload, indent=2, default=str)[:20000]
                if payload is not None else False
            ),
        }
        try:
            response = requests.request(
                method, url, headers=headers,
                json=payload if payload is not None else None,
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            self._write_sync_log(dict(
                log_vals, state='error', response_body=str(exc),
                note=_('Could not reach Aiosell')))
            raise UserError(_('Could not reach Aiosell: %s') % exc) from exc

        try:
            body = response.json()
        except ValueError:
            body = None

        log_vals.update({
            'http_status': response.status_code,
            'response_body': response.text[:20000],
        })
        # The body decides, not the status code: Aiosell answers 400 with
        # {"success": false, "message": "Authentication Required!"}.
        failed = (
            body is None
            or (isinstance(body, dict)
                and (body.get('success') is False or body.get('status') is False))
            or (not response.ok and not isinstance(body, list))
        )
        if failed:
            message = ''
            if isinstance(body, dict):
                message = body.get('message') or body.get('error') or ''
            message = message or response.text[:300]
            self._write_sync_log(dict(log_vals, state='error', note=message[:500]))
            raise UserError(_(
                'Aiosell rejected the %(op)s call (HTTP %(status)s): %(msg)s'
            ) % {
                'op': operation or path,
                'status': response.status_code,
                'msg': message,
            })
        self._write_sync_log(dict(log_vals, state='success'))
        return body

    # ── Endpoints ───────────────────────────────────────────────────────
    def get_property_details(self):
        """Canonical hotel/room/rateplan codes, straight from Aiosell."""
        self.ensure_one()
        self._check_ready()
        path = f'/property_details/{self.hotel_code}?partnerId={self.pms_slug}'
        return self._call(path, method='GET', operation='property_details')

    def push_inventory(self, updates):
        if not updates:
            return None
        return self._call(
            f'/update/{self.pms_slug}',
            {'hotelCode': self.hotel_code, 'updates': updates},
            operation='inventory_push',
        )

    def push_rates(self, updates):
        if not updates:
            return None
        return self._call(
            f'/update-rates/{self.pms_slug}',
            {'hotelCode': self.hotel_code, 'updates': updates},
            operation='rate_push',
        )

    def push_restrictions(self, updates):
        """Room-level restrictions. Same URL as inventory, different body."""
        channels = [c.strip() for c in (self.restriction_channels or '').split(',') if c.strip()]
        if not updates or not channels:
            return None
        return self._call(
            f'/update/{self.pms_slug}',
            {
                'hotelCode': self.hotel_code,
                'toChannels': channels,
                'updates': updates,
            },
            operation='inventory_restrictions_push',
        )

    def mark_no_show(self, booking_id, channel):
        return self._call(
            f'/marknoshow/{self.pms_slug}',
            {
                'hotelCode': self.hotel_code,
                'bookingId': booking_id,
                'channel': channel,
            },
            operation='marknoshow',
        )

    def fetch_data(self, dataset, start_date, end_date):
        """Read inventory / rates / reservations back from Aiosell.

        Named ``fetch_data`` and not ``fetch``: ``Model.fetch`` is Odoo's own
        field-prefetch method, and shadowing it breaks the ORM for every
        record of this model.

        ``dataset`` is the ``type`` selector; the reservation one is the
        singular ``"reservation"``, not ``"reservations"``.
        """
        return self._call(
            f'/data/{self.pms_slug}',
            {
                'type': dataset,
                'hotelCode': self.hotel_code,
                'startDate': fields.Date.to_string(start_date),
                'endDate': fields.Date.to_string(end_date),
            },
            operation=f'fetch_{dataset}',
        )

    # ── UI actions ──────────────────────────────────────────────────────
    def action_test_connection(self):
        self.ensure_one()
        data = self.get_property_details()
        rooms = data.get('rooms') or [] if isinstance(data, dict) else []
        return self._notify(
            _('Connection Successful'),
            _('Aiosell answered for "%(hotel)s": %(rooms)s room types, '
              'currency %(currency)s.') % {
                'hotel': data.get('hotel_name') if isinstance(data, dict) else '?',
                'rooms': len(rooms),
                'currency': data.get('currency') if isinstance(data, dict) else '?',
            },
            'success',
        )

    def action_import_mapping(self):
        """Pull the codes from Aiosell and pre-fill the mapping tables.

        Room types and rate plans are matched by name where possible; anything
        unmatched is left blank for a human to pair up, rather than guessed.
        """
        self.ensure_one()
        data = self.get_property_details()
        if not isinstance(data, dict):
            raise UserError(_('Unexpected property_details response from Aiosell.'))

        currency = (data.get('currency') or '').upper()
        self.property_currency = currency
        company_currency = self.company_id.currency_id.name
        if currency and currency != company_currency:
            raise UserError(_(
                'Aiosell holds this property in %(theirs)s but the company '
                'books in %(ours)s. Rates are pushed as plain numbers in the '
                'property currency, so pushing now would list a '
                '%(ours)s price as a %(theirs)s one. Have Aiosell change the '
                'property currency to %(ours)s before syncing.'
            ) % {'theirs': currency, 'ours': company_currency})

        RoomMap = self.env['aiosell.room.mapping']
        RateMap = self.env['aiosell.rateplan.mapping']
        RoomType = self.env['hotel.room.type']
        RatePlan = self.env['hotel.rate.plan']
        created = matched = 0

        for room in data.get('rooms') or []:
            code = room.get('room_id')
            if not code:
                continue
            mapping = RoomMap.search([
                ('config_id', '=', self.id), ('room_code', '=', code),
            ], limit=1)
            guess = RoomType.search([
                ('name', '=ilike', room.get('room_name') or '~none~'),
            ], limit=1)
            vals = {
                'config_id': self.id,
                'room_code': code,
                'remote_name': room.get('room_name') or code,
                'remote_count': room.get('count') or 0,
            }
            if not mapping:
                if guess:
                    vals['room_type_id'] = guess.id
                    matched += 1
                mapping = RoomMap.create(vals)
                created += 1
            else:
                mapping.write({k: v for k, v in vals.items() if k != 'config_id'})

            for plan in room.get('rateplans') or []:
                plan_code = plan.get('rateplan_id')
                if not plan_code:
                    continue
                existing = RateMap.search([
                    ('config_id', '=', self.id), ('rateplan_code', '=', plan_code),
                ], limit=1)
                plan_guess = RatePlan.search([
                    ('name', '=ilike', plan.get('rateplan_name') or '~none~'),
                ], limit=1)
                rvals = {
                    'config_id': self.id,
                    'rateplan_code': plan_code,
                    'room_mapping_id': mapping.id,
                    'remote_name': plan.get('rateplan_name') or plan_code,
                    'occupancy': plan.get('occupancy') or 0,
                }
                if not existing:
                    if plan_guess:
                        rvals['rate_plan_id'] = plan_guess.id
                    RateMap.create(rvals)
                    created += 1
                else:
                    existing.write({k: v for k, v in rvals.items() if k != 'config_id'})

        return self._notify(
            _('Mapping Imported'),
            _('%(created)s codes imported from Aiosell, %(matched)s room types '
              'matched by name. Check the mapping tables and fill in anything '
              'left blank — unmapped codes are not synced.')
            % {'created': created, 'matched': matched},
            'success',
        )

    def action_push_now(self):
        """Push the whole horizon on demand."""
        self.ensure_one()
        summary = self._push_ari()
        return self._notify(_('Pushed to Aiosell'), summary, 'success')

    def _notify(self, title, message, kind):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title, 'message': message,
                'type': kind, 'sticky': kind != 'success',
            },
        }

    # ── Cron ────────────────────────────────────────────────────────────
    @api.model
    def _cron_push_ari(self):
        """Push availability and rates for every live connection."""
        for config in self.search([]):
            try:
                config._push_ari()
                self.env.cr.commit()
            except Exception:  # noqa: BLE001 - one bad config must not stop the rest
                self.env.cr.rollback()
                _logger.exception('Aiosell ARI push failed for %s', config.display_name)

    def _horizon(self):
        self.ensure_one()
        start = fields.Date.context_today(self)
        return start, start + timedelta(days=self.horizon_days)
