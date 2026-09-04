# -*- coding: utf-8 -*-
"""Turning an Aiosell reservation push into PMS records.

Aiosell POSTs ``book`` / ``modify`` / ``cancel`` to a webhook this module
exposes; the ``action`` field is the only thing separating them. Everything
here runs as sudo from an unauthenticated route, so it validates hard and
touches nothing outside the reservation it owns.

Retry contract, decided once and applied throughout:

* **Transport or programming failure** -> the controller answers HTTP 500 and
  Aiosell retries. Nothing was written.
* **Deliberate refusal** — a modify or cancel for a guest already checked in,
  say — -> HTTP 200 with ``success: true``, so Aiosell stops retrying, plus a
  log line and an activity on the reservation so a human picks it up. Retrying
  would never make such a request succeed; silently swallowing it would lose
  it.

Guest fields are all optional. OTAs mask e-mail and phone routinely, so
nothing here may require them.
"""
import json
import logging
from datetime import datetime

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# States where an inbound change can no longer be applied automatically:
# the guest is in-house or gone, and money has moved on the folio.
LOCKED_STATES = ('checked_in', 'checked_out')


class AiosellConfig(models.Model):
    _inherit = 'aiosell.config'

    # ── Entry point ─────────────────────────────────────────────────────
    @api.model
    def handle_reservation_push(self, payload):
        """Apply one inbound payload. Returns (http_status, body).

        Raises nothing for business refusals — those come back as a 200 with
        an explanatory message. Genuine errors are allowed to propagate so the
        controller can turn them into a 500 and let Aiosell retry.
        """
        action = (payload.get('action') or '').lower()
        hotel_code = payload.get('hotelCode')
        booking_id = payload.get('bookingId')

        config = self.search([('hotel_code', '=', hotel_code)], limit=1)
        if not config:
            return 200, {
                'success': False,
                'message': f'Unknown hotelCode: {hotel_code}',
            }
        if not booking_id:
            return 200, {'success': False, 'message': 'bookingId is required'}

        log = self.env['aiosell.sync.log'].create({
            'config_id': config.id,
            'direction': 'inbound',
            'operation': action or 'unknown',
            'booking_id': str(booking_id),
            'request_body': json.dumps(payload, indent=2)[:20000],
            'state': 'pending',
        })

        if action == 'cancel':
            body = config._inbound_cancel(payload, log)
        elif action in ('book', 'modify'):
            body = config._inbound_book(payload, log, modify=(action == 'modify'))
        else:
            log.write({'state': 'error', 'note': 'unsupported action'})
            return 200, {
                'success': False,
                'message': f'Unsupported action: {action}',
            }

        config.last_inbound_date = fields.Datetime.now()
        return 200, body

    # ── book / modify ───────────────────────────────────────────────────
    def _inbound_book(self, payload, log, modify=False):
        self.ensure_one()
        booking_id = str(payload.get('bookingId'))
        existing = self.env['hotel.reservation'].search([
            ('aiosell_config_id', '=', self.id),
            ('aiosell_booking_id', '=', booking_id),
        ])

        # A repeated 'book' for a booking already held is a modify. Aiosell
        # retries on any non-2xx, so this has to be idempotent.
        if existing:
            locked = existing.filtered(lambda r: r.state in LOCKED_STATES)
            if locked:
                return self._refuse(
                    log, existing,
                    _('Booking %(ref)s changed on the channel, but %(rooms)s '
                      'is already %(state)s in the PMS. Apply the change by '
                      'hand and settle the folio.') % {
                        'ref': booking_id,
                        'rooms': ', '.join(locked.mapped('reservation_number')),
                        'state': ', '.join(set(locked.mapped('state'))),
                    },
                )
            return self._apply_booking(payload, log, existing)

        if modify:
            # Modify for something never delivered: treat it as the booking
            # itself rather than dropping a live reservation on the floor.
            _logger.info(
                'Aiosell: modify for unknown booking %s, creating it', booking_id)
        return self._apply_booking(payload, log, self.env['hotel.reservation'])

    def _apply_booking(self, payload, log, existing):
        """Create or update the reservations behind one OTA booking."""
        self.ensure_one()
        booking_id = str(payload.get('bookingId'))
        checkin = fields.Date.to_date(payload.get('checkin'))
        checkout = fields.Date.to_date(payload.get('checkout'))
        if not checkin or not checkout or checkout <= checkin:
            return self._refuse(
                log, existing,
                _('Booking %(ref)s has an unusable stay: %(in)s to %(out)s.')
                % {'ref': booking_id, 'in': payload.get('checkin'),
                   'out': payload.get('checkout')},
            )

        rooms = payload.get('rooms') or []
        if not rooms:
            return self._refuse(
                log, existing, _('Booking %s carries no rooms.') % booking_id)

        guest = self._find_or_create_guest(payload, existing)
        source = self._resolve_source(payload.get('channel'))
        prepaid = not payload.get('pah', False)
        agency = self._resolve_channel_agency(payload.get('channel'), prepaid)
        notes = self._booking_notes(payload)

        reservations = self.env['hotel.reservation']
        # Oldest first: the default order is newest-first, and reusing records
        # in the wrong order makes a modify rewrite the wrong room.
        unclaimed = existing.sorted('id')
        for room in rooms:
            vals = self._reservation_vals(
                payload, room, checkin, checkout, guest, source, prepaid,
                notes, agency)
            if vals is None:
                return self._refuse(
                    log, existing,
                    _('Booking %(ref)s uses room code "%(code)s", which is not '
                      'mapped to a PMS room type. Map it under Aiosell → '
                      'Room Type Mapping, then have the channel resend.')
                    % {'ref': booking_id, 'code': room.get('roomCode')},
                )
            # Prefer an existing room of the same type, so a modify keeps each
            # room's history (and its folio) attached to the right record.
            target = unclaimed.filtered(
                lambda r: r.room_type_id.id == vals['room_type_id'])[:1]
            if not target:
                target = unclaimed[:1]
            if target:
                unclaimed -= target
                target.write(vals)
            else:
                target = self.env['hotel.reservation'].create(vals)
            reservations |= target

        # A modify that drops a room leaves a reservation behind that nobody
        # is coming for.
        for stale in unclaimed:
            if stale.state not in LOCKED_STATES and stale.state != 'cancelled':
                stale.action_cancel()

        for reservation in reservations:
            self._assign_and_confirm(reservation)

        log.write({
            'state': 'success',
            'reservation_id': reservations[:1].id,
            'note': ', '.join(reservations.mapped('reservation_number')),
        })
        return {
            'success': True,
            'message': 'Reservation %s Successfully' % (
                'Modified' if existing else 'Created'),
        }

    def _reservation_vals(self, payload, room, checkin, checkout, guest,
                          source, prepaid, notes, agency=None):
        """Field values for one room of an OTA booking, or None if unmappable."""
        self.ensure_one()
        mapping = self.room_mapping_ids.filtered(
            lambda m: m.room_code == room.get('roomCode') and m.room_type_id
        )[:1]
        if not mapping:
            return None

        occupancy = room.get('occupancy') or {}
        vals = {
            'guest_id': guest.id,
            'room_type_id': mapping.room_type_id.id,
            'checkin_date': checkin,
            'checkout_date': checkout,
            'adults': occupancy.get('adults') or 1,
            'children': occupancy.get('children') or 0,
            'source_id': source.id if source else False,
            'notes': notes,
            # The channel already e-mailed the guest; a second confirmation
            # from the PMS to a masked OTA relay address helps nobody.
            'send_confirmation': self.send_guest_email,
            'agency_id': agency.id if agency else False,
            # A prepaid stay billed to the channel owes nothing at the desk,
            # so it must not be gated on a prepayment the guest never makes.
            'payment_required': prepaid and not agency,
            'prepaid': prepaid,
            'ota_nightly_rate': self._nightly_from_prices(room, checkin, checkout),
            'aiosell_config_id': self.id,
            'aiosell_booking_id': str(payload.get('bookingId')),
            'aiosell_payload': json.dumps(payload, indent=2)[:60000],
        }
        # Only carried when the payload carries them: a modify that repeats
        # just the stay dates would otherwise blank the channel manager's own
        # reference and the channel name on an existing reservation.
        if payload.get('cmBookingId'):
            vals['aiosell_cm_booking_id'] = payload['cmBookingId']
        if payload.get('channel'):
            vals['aiosell_channel'] = payload['channel']
        return vals

    def _nightly_from_prices(self, room, checkin, checkout):
        """Average nightly sell rate for a room.

        The channel prices each night separately; the PMS carries one nightly
        rate per reservation. Averaging keeps the stay total right, which is
        the number the folio and the OTA statement have to agree on.
        """
        prices = room.get('prices') or []
        nights = (checkout - checkin).days or 1
        total = sum(float(p.get('sellRate') or 0.0) for p in prices)
        if not total:
            return 0.0
        return round(total / nights, 2)

    def _assign_and_confirm(self, reservation):
        """Give the booking a room and confirm it, as far as it can get.

        Confirmation is what opens the folio, and the PMS refuses to confirm a
        roomless booking, so the two go together. When no room is free the
        reservation stays draft and an activity asks reception to sort it —
        an OTA booking that cannot be housed is exactly what a human needs to
        see.
        """
        self.ensure_one()
        if reservation.state != 'draft':
            return
        if self.auto_assign_room and not reservation.room_id:
            free = self.env['hotel.room'].get_available_rooms(
                reservation.checkin_date, reservation.checkout_date,
                room_type_id=reservation.room_type_id.id,
            )
            # get_available_rooms ignores draft holds; exclude rooms another
            # draft booking is already sitting on so two OTA arrivals do not
            # land in the same bed.
            taken = self.env['hotel.reservation'].search([
                ('id', '!=', reservation.id),
                ('state', '=', 'draft'),
                ('room_id', '!=', False),
                ('checkin_date', '<', reservation.checkout_date),
                ('checkout_date', '>', reservation.checkin_date),
            ]).mapped('room_id').ids
            free = free.filtered(lambda r: r.id not in taken)
            # get_available_rooms only excludes maintenance, so a room whose
            # board status is still 'occupied' (a stale check-out, a guest who
            # never left) can come back as free. Never walk an OTA guest into
            # one of those.
            ready = free.filtered(lambda r: r.status != 'occupied')
            if ready:
                reservation.room_id = ready[0]

        if not reservation.room_id:
            reservation.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('OTA booking needs a room'),
                note=_('%(channel)s booking %(ref)s arrived but no room of '
                       'type %(type)s is free. Assign a room and confirm, or '
                       'close the channel for these dates.') % {
                    'channel': reservation.aiosell_channel or _('Channel'),
                    'ref': reservation.aiosell_booking_id,
                    'type': reservation.room_type_id.name,
                },
                user_id=self._activity_user(),
            )
            return

        if self.auto_confirm_bookings:
            reservation.with_context(
                skip_confirmation_email=not self.send_guest_email,
            ).action_confirm()

    # ── cancel ──────────────────────────────────────────────────────────
    def _inbound_cancel(self, payload, log):
        self.ensure_one()
        booking_id = str(payload.get('bookingId'))
        reservations = self.env['hotel.reservation'].search([
            ('aiosell_config_id', '=', self.id),
            ('aiosell_booking_id', '=', booking_id),
        ])
        if not reservations:
            log.write({'state': 'success', 'note': 'nothing to cancel'})
            return {'success': True, 'message': 'No matching reservation'}

        locked = reservations.filtered(lambda r: r.state in LOCKED_STATES)
        if locked:
            return self._refuse(
                log, reservations,
                _('The channel cancelled booking %(ref)s, but %(rooms)s is '
                  'already %(state)s. Check the guest out and settle the '
                  'folio by hand — a cancellation cannot undo money already '
                  'posted.') % {
                    'ref': booking_id,
                    'rooms': ', '.join(locked.mapped('reservation_number')),
                    'state': ', '.join(set(locked.mapped('state'))),
                },
            )

        open_ones = reservations.filtered(lambda r: r.state != 'cancelled')
        open_ones.action_cancel()
        log.write({
            'state': 'success',
            'reservation_id': reservations[:1].id,
            'note': ', '.join(reservations.mapped('reservation_number')),
        })
        return {'success': True, 'message': 'Reservation Cancelled Successfully'}

    # ── helpers ─────────────────────────────────────────────────────────
    def _activity_user(self):
        """Who to chase. Inbound runs as the system user, so a real person
        has to be named or the to-do lands nowhere useful."""
        self.ensure_one()
        return (self.activity_user_id or self.env.user).id

    def _refuse(self, log, reservations, message):
        """Record something a human has to deal with, and stop the retries."""
        self.ensure_one()
        _logger.warning('Aiosell refusal: %s', message)
        log.write({
            'state': 'refused',
            'note': message[:500],
            'reservation_id': reservations[:1].id if reservations else False,
        })
        for reservation in reservations[:1]:
            reservation.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('Channel change needs manual handling'),
                note=message,
                user_id=self._activity_user(),
            )
            reservation.message_post(body=message)
        # 'success' so Aiosell stops retrying something that can never
        # succeed; the message says what happened and the activity chases it.
        return {'success': True, 'message': message}

    def _find_or_create_guest(self, payload, existing=None):
        """Match the OTA guest to a partner, or make one.

        Matching is by e-mail only. OTAs hand out per-booking relay addresses,
        so this rarely merges anything, but a repeat guest booking direct with
        their real address will be recognised.

        ``existing`` is the booking already held, if any. A modify often
        repeats only the guest's name — the e-mail, phone and address came
        with the original book — and resolving that from scratch would create
        a second, contactless partner and hang the reservation on it, losing
        the only way anyone has to reach the guest.
        """
        self.ensure_one()
        guest = payload.get('guest') or {}
        first = (guest.get('firstName') or '').strip()
        last = (guest.get('lastName') or '').strip()
        rooms = payload.get('rooms') or []
        name = ' '.join(p for p in (first, last) if p)
        if not name and rooms:
            name = (rooms[0].get('guestName') or '').strip()
        if not name:
            name = _('%(channel)s guest %(ref)s') % {
                'channel': payload.get('channel') or _('OTA'),
                'ref': payload.get('bookingId'),
            }

        Partner = self.env['res.partner']
        email = (guest.get('email') or '').strip()
        if email:
            match = Partner.search([('email', '=ilike', email)], limit=1)
            if match:
                return match

        # No e-mail to go on: keep whoever the booking already names rather
        # than minting a nameless twin. A modify that does carry an e-mail
        # falls through, so a genuine change of guest still lands.
        if not email and existing is not None and existing.guest_id:
            return existing.guest_id[:1]

        address = guest.get('address') or {}
        country = self.env['res.country']
        if address.get('country'):
            country = country.search([
                '|', ('name', '=ilike', address['country']),
                ('code', '=ilike', address['country']),
            ], limit=1)
        return Partner.create({
            'name': name,
            'email': email or False,
            'phone': (guest.get('phone') or '').strip() or False,
            'street': address.get('line1') or False,
            'city': address.get('city') or False,
            'zip': address.get('zipCode') or False,
            'country_id': country.id if country else False,
            'is_company': False,
        })

    def _resolve_channel_agency(self, channel, prepaid):
        """The channel as a billable account, for stays it collected for.

        A prepaid OTA booking is money the *channel* owes the hotel, not the
        guest: the guest settles nothing on departure. Billing it to the guest
        folio leaves a charge nobody will pay at the desk, and the check-out
        balance guard then bars every prepaid OTA departure — with no manager
        override available to reception.

        Routing it to the channel as an agency on credit terms puts the room
        charge on a company folio, which the guard treats as a city-ledger
        balance and does not hold the guest for. The debt stays visible there
        until the channel's remittance is reconciled against it.
        """
        self.ensure_one()
        if not (prepaid and self.route_prepaid_to_channel and channel):
            return None
        Partner = self.env['res.partner']
        agency = Partner.search([
            ('name', '=ilike', channel), ('is_hotel_agency', '=', True),
        ], limit=1)
        if agency:
            return agency
        return Partner.create({
            'name': channel,
            'is_company': True,
            'is_hotel_agency': True,
            'hotel_credit_term': True,
            'hotel_routing': 'room',
            'comment': _('Created automatically for prepaid bookings arriving '
                         'from %s through Aiosell. Room charges are carried '
                         'here until the channel remits.') % channel,
        })

    def _resolve_source(self, channel):
        """Match the channel name to a booking source, creating it if new."""
        self.ensure_one()
        if not channel:
            return self.source_id
        Source = self.env['hotel.booking.source']
        source = Source.search([('name', '=ilike', channel)], limit=1)
        if source:
            return source
        return Source.create({'name': channel})

    def _booking_notes(self, payload):
        """Everything the channel said that has nowhere else to live."""
        amount = payload.get('amount') or {}
        lines = [
            _('Channel: %s') % (payload.get('channel') or '?'),
            _('OTA booking ID: %s') % payload.get('bookingId'),
        ]
        if payload.get('cmBookingId'):
            lines.append(_('Channel manager ID: %s') % payload['cmBookingId'])
        if payload.get('bookedOn'):
            lines.append(_('Booked on: %s') % payload['bookedOn'])
        if amount:
            lines.append(_('Channel total: %(total)s %(cur)s (before tax '
                           '%(net)s, tax %(tax)s)') % {
                'total': amount.get('amountAfterTax'),
                'cur': amount.get('currency') or '',
                'net': amount.get('amountBeforeTax'),
                'tax': amount.get('tax'),
            })
            if amount.get('commission'):
                lines.append(_('OTA commission: %s') % amount['commission'])
        lines.append(_('Payment: %s') % (
            _('collect at hotel') if payload.get('pah') else _('prepaid to channel')))
        if payload.get('specialRequests'):
            # Free text whose meaning varies by channel; stored as-is.
            lines.append(_('Special requests: %s') % payload['specialRequests'])
        return '\n'.join(lines)
