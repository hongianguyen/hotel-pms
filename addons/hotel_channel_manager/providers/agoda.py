# -*- coding: utf-8 -*-
import logging

import requests

from .base_provider import AbstractChannelProvider, register_provider

_logger = logging.getLogger(__name__)


@register_provider('agoda')
class AgodaProvider(AbstractChannelProvider):
    """Agoda YCS Partner API adapter (REST/JSON)."""

    def _get_headers(self):
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
            'X-Api-Key': self.api_secret,
        }

    def _get_base_url(self):
        return self.api_url or 'https://ycs.agoda.com/api/v3'

    def test_connection(self):
        try:
            url = f'{self._get_base_url()}/property/{self.property_id}/status'
            resp = requests.get(
                url,
                headers=self._get_headers(),
                timeout=15,
            )
            if resp.status_code == 200:
                return True, 'Successfully connected to Agoda YCS API.'
            return False, (
                f'Agoda API returned status {resp.status_code}: '
                f'{resp.text[:500]}'
            )
        except requests.RequestException as e:
            return False, f'Connection error: {e}'

    def push_availability(self, data):
        if not data:
            return None
        try:
            payload = self._build_availability_json(data)
            url = (
                f'{self._get_base_url()}/property/{self.property_id}'
                f'/availability'
            )
            resp = requests.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            _logger.error('Agoda availability push failed: %s', e)
            raise

    def _build_availability_json(self, data):
        inventory = []
        for room_type_id, dates in data.items():
            for date_str, count in dates.items():
                inventory.append({
                    'roomTypeId': room_type_id,
                    'date': date_str,
                    'available': count,
                })
        return {'inventory': inventory}

    def push_rates(self, data):
        if not data:
            return None
        try:
            payload = self._build_rate_json(data)
            url = (
                f'{self._get_base_url()}/property/{self.property_id}/rates'
            )
            resp = requests.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            _logger.error('Agoda rate push failed: %s', e)
            raise

    def _build_rate_json(self, data):
        rates = []
        for rate_plan_id, room_types in data.items():
            for room_type_id, dates in room_types.items():
                for date_str, amount in dates.items():
                    rates.append({
                        'ratePlanId': rate_plan_id,
                        'roomTypeId': room_type_id,
                        'date': date_str,
                        'rate': amount,
                    })
        return {'rates': rates}

    def push_restrictions(self, data):
        if not data:
            return None
        try:
            payload = self._build_restriction_json(data)
            url = (
                f'{self._get_base_url()}/property/{self.property_id}'
                f'/restrictions'
            )
            resp = requests.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            _logger.error('Agoda restriction push failed: %s', e)
            raise

    def _build_restriction_json(self, data):
        restrictions = []
        for rate_plan_id, dates in data.items():
            for date_str, r in dates.items():
                restrictions.append({
                    'ratePlanId': rate_plan_id,
                    'date': date_str,
                    'minStay': r.get('min_stay', 1),
                    'stopSell': r.get('stop_sell', False),
                })
        return {'restrictions': restrictions}

    def push_cancellation(self, channel_booking_id):
        if not channel_booking_id:
            return None
        try:
            url = (
                f'{self._get_base_url()}/property/{self.property_id}'
                f'/booking/{channel_booking_id}/cancel'
            )
            resp = requests.post(
                url,
                headers=self._get_headers(),
                json={'bookingId': channel_booking_id},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            _logger.error('Agoda cancellation push failed: %s', e)
            raise

    def parse_booking_webhook(self, payload):
        """Parse Agoda booking webhook (JSON).

        Expected payload keys:
            bookingId, guestName, guestEmail, guestPhone,
            checkIn, checkOut, roomTypeId, adults, children,
            totalAmount, specialRequests
        """
        return {
            'channel_booking_id': str(payload.get('bookingId', '')),
            'guest_name': payload.get('guestName', ''),
            'guest_email': payload.get('guestEmail', ''),
            'guest_phone': payload.get('guestPhone', ''),
            'checkin_date': payload.get('checkIn', ''),
            'checkout_date': payload.get('checkOut', ''),
            'channel_room_type_id': str(payload.get('roomTypeId', '')),
            'adults': int(payload.get('adults', 1)),
            'children': int(payload.get('children', 0)),
            'total_amount': float(payload.get('totalAmount', 0)),
            'notes': payload.get('specialRequests', ''),
        }

    def parse_cancellation_webhook(self, payload):
        return {
            'channel_booking_id': str(payload.get('bookingId', '')),
        }
