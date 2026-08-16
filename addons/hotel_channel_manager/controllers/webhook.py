# -*- coding: utf-8 -*-
import json
import logging

from odoo import http, fields
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class ChannelWebhookController(http.Controller):

    @http.route(
        '/channel/webhook/booking/<string:provider_code>',
        type='json',
        auth='none',
        methods=['POST'],
        csrf=False,
    )
    def receive_booking(self, provider_code, **kwargs):
        """Inbound booking webhook from OTA channel."""
        payload = request.get_json_data()
        signature = request.httprequest.headers.get('X-Channel-Signature', '')

        _logger.info(
            'Channel webhook received: provider=%s', provider_code,
        )

        config = self._get_verified_config(provider_code, payload, signature)
        if not config:
            return {'status': 'error', 'message': 'Authentication failed'}

        try:
            result = self._process_booking(config, payload)
            return result
        except Exception as e:
            _logger.exception(
                'Error processing channel booking: %s', e,
            )
            self._log_error(config, 'booking', payload, str(e))
            return {'status': 'error', 'message': 'Internal processing error'}

    @http.route(
        '/channel/webhook/cancellation/<string:provider_code>',
        type='json',
        auth='none',
        methods=['POST'],
        csrf=False,
    )
    def receive_cancellation(self, provider_code, **kwargs):
        """Inbound cancellation webhook from OTA channel."""
        payload = request.get_json_data()
        signature = request.httprequest.headers.get('X-Channel-Signature', '')

        config = self._get_verified_config(provider_code, payload, signature)
        if not config:
            return {'status': 'error', 'message': 'Authentication failed'}

        try:
            result = self._process_cancellation(config, payload)
            return result
        except Exception as e:
            _logger.exception(
                'Error processing channel cancellation: %s', e,
            )
            self._log_error(config, 'cancellation', payload, str(e))
            return {'status': 'error', 'message': 'Internal processing error'}

    def _get_verified_config(self, provider_code, payload, signature):
        """Find config and verify HMAC signature."""
        Config = request.env['channel.manager.config'].sudo()
        config = Config.search([
            ('provider_code', '=', provider_code),
            ('active', '=', True),
        ], limit=1)
        if not config:
            _logger.warning(
                'No active config for provider: %s', provider_code,
            )
            return None

        payload_bytes = json.dumps(payload, sort_keys=True).encode()
        if not config.verify_webhook_signature(payload_bytes, signature):
            _logger.warning(
                'Invalid webhook signature for provider: %s', provider_code,
            )
            return None

        return config

    def _process_booking(self, config, payload):
        """Process inbound booking: parse, check availability, create reservation."""
        provider = config._get_provider()
        booking_data = provider.parse_booking_webhook(payload)

        channel_booking_id = booking_data.get('channel_booking_id')
        if not channel_booking_id:
            return {'status': 'error', 'message': 'Missing booking ID'}

        # Check for duplicate
        Reservation = request.env['hotel.reservation'].sudo()
        existing = Reservation.search([
            ('channel_booking_id', '=', channel_booking_id),
            ('channel_config_id', '=', config.id),
        ], limit=1)
        if existing:
            _logger.info(
                'Duplicate channel booking %s, skipping', channel_booking_id,
            )
            return {
                'status': 'ok',
                'message': 'Booking already exists',
                'reservation_id': existing.reservation_number,
            }

        # Find room type mapping
        mapping = request.env['channel.room.type.mapping'].sudo().search([
            ('config_id', '=', config.id),
            ('channel_room_type_id', '=', booking_data['channel_room_type_id']),
        ], limit=1)
        if not mapping:
            msg = (
                f"No room type mapping for channel room type "
                f"{booking_data['channel_room_type_id']}"
            )
            self._log_error(config, 'booking', payload, msg)
            return {'status': 'error', 'message': msg}

        room_type = mapping.room_type_id
        checkin = fields.Date.to_date(booking_data['checkin_date'])
        checkout = fields.Date.to_date(booking_data['checkout_date'])

        # Check availability
        Room = request.env['hotel.room'].sudo()
        available = Room.get_available_rooms(checkin, checkout, room_type.id)
        if not available:
            _logger.warning(
                'No availability for channel booking %s, room type %s',
                channel_booking_id, room_type.name,
            )
            # Push corrected availability immediately
            self._push_corrected_availability(config, room_type)
            self._log_error(
                config, 'booking', payload,
                f'No availability for {room_type.name} '
                f'{checkin} to {checkout}',
            )
            return {'status': 'error', 'message': 'No availability'}

        # Find or create guest
        guest = self._find_or_create_guest(booking_data)

        # Create reservation
        room = available[0]
        reservation_vals = {
            'guest_id': guest.id,
            'room_type_id': room_type.id,
            'room_id': room.id,
            'checkin_date': checkin,
            'checkout_date': checkout,
            'adults': booking_data.get('adults', 1),
            'children': booking_data.get('children', 0),
            'source_id': config.booking_source_id.id
            if config.booking_source_id else False,
            'channel_config_id': config.id,
            'channel_booking_id': channel_booking_id,
            'channel_synced': True,
            'notes': booking_data.get('notes', ''),
        }
        reservation = Reservation.with_context(
            skip_channel_sync=True,
        ).create(reservation_vals)

        # Auto-confirm if configured
        if config.auto_confirm_bookings:
            reservation.with_context(skip_channel_sync=True).action_confirm()

        # Log success
        request.env['channel.sync.log'].sudo().create({
            'config_id': config.id,
            'direction': 'inbound',
            'sync_type': 'booking',
            'state': 'success',
            'reservation_id': reservation.id,
            'room_type_id': room_type.id,
            'request_payload': json.dumps(payload)[:5000],
            'response_payload': json.dumps({
                'reservation_number': reservation.reservation_number,
            }),
        })

        # Push updated availability to ALL channels
        reservation._trigger_availability_push_for_room_types(room_type)

        _logger.info(
            'Channel booking %s created as reservation %s',
            channel_booking_id, reservation.reservation_number,
        )

        return {
            'status': 'ok',
            'reservation_id': reservation.reservation_number,
        }

    def _process_cancellation(self, config, payload):
        """Process inbound cancellation."""
        provider = config._get_provider()
        cancel_data = provider.parse_cancellation_webhook(payload)

        channel_booking_id = cancel_data.get('channel_booking_id')
        if not channel_booking_id:
            return {'status': 'error', 'message': 'Missing booking ID'}

        Reservation = request.env['hotel.reservation'].sudo()
        reservation = Reservation.search([
            ('channel_booking_id', '=', channel_booking_id),
            ('channel_config_id', '=', config.id),
            ('state', 'not in', ['cancelled', 'checked_out']),
        ], limit=1)

        if not reservation:
            _logger.warning(
                'No active reservation for channel cancellation %s',
                channel_booking_id,
            )
            return {
                'status': 'ok',
                'message': 'No matching active reservation found',
            }

        room_types = reservation.room_type_id
        reservation.with_context(skip_channel_sync=True).action_cancel()

        # Log success
        request.env['channel.sync.log'].sudo().create({
            'config_id': config.id,
            'direction': 'inbound',
            'sync_type': 'cancellation',
            'state': 'success',
            'reservation_id': reservation.id,
            'request_payload': json.dumps(payload)[:5000],
        })

        # Push updated availability to ALL channels
        reservation._trigger_availability_push_for_room_types(room_types)

        return {
            'status': 'ok',
            'reservation_id': reservation.reservation_number,
        }

    def _find_or_create_guest(self, booking_data):
        """Find existing partner by email or create new one."""
        Partner = request.env['res.partner'].sudo()
        email = booking_data.get('guest_email', '').strip()
        if email:
            guest = Partner.search([('email', '=', email)], limit=1)
            if guest:
                return guest

        name = booking_data.get('guest_name', '').strip() or 'Channel Guest'
        vals = {
            'name': name,
            'email': email or False,
            'phone': booking_data.get('guest_phone', '') or False,
            'is_company': False,
        }
        return Partner.create(vals)

    def _push_corrected_availability(self, config, room_type):
        """Push corrected availability when overbooking is detected."""
        request.env['channel.sync.log'].sudo().create({
            'config_id': config.id,
            'direction': 'outbound',
            'sync_type': 'availability',
            'room_type_id': room_type.id,
            'state': 'pending',
        })

    def _log_error(self, config, sync_type, payload, error_msg):
        """Log an error in the sync log."""
        request.env['channel.sync.log'].sudo().create({
            'config_id': config.id,
            'direction': 'inbound',
            'sync_type': sync_type,
            'state': 'error',
            'request_payload': json.dumps(payload)[:5000] if payload else '',
            'error_message': error_msg[:2000],
        })
