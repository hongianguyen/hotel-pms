# -*- coding: utf-8 -*-
import logging

import requests

from .base_provider import AbstractChannelProvider, register_provider

_logger = logging.getLogger(__name__)


@register_provider('booking_com')
class BookingComProvider(AbstractChannelProvider):
    """Booking.com Connectivity API adapter.

    Booking.com uses XML/SOAP for the Connectivity API.
    This implementation uses simplified REST-style calls that can be
    adapted to the actual SOAP envelope format in production.
    """

    def _get_headers(self):
        return {
            'Content-Type': 'application/xml',
            'Authorization': f'Basic {self.api_key}',
        }

    def _get_base_url(self):
        return self.api_url or 'https://supply-xml.booking.com/hotels/xml'

    def test_connection(self):
        try:
            url = f'{self._get_base_url()}/test'
            resp = requests.get(
                url,
                headers=self._get_headers(),
                params={'hotel_id': self.property_id},
                timeout=15,
            )
            if resp.status_code == 200:
                return True, 'Successfully connected to Booking.com API.'
            return False, (
                f'Booking.com API returned status {resp.status_code}: '
                f'{resp.text[:500]}'
            )
        except requests.RequestException as e:
            return False, f'Connection error: {e}'

    def push_availability(self, data):
        """Push availability using OTA_HotelAvailNotifRQ format."""
        if not data:
            return None
        try:
            xml_payload = self._build_availability_xml(data)
            url = f'{self._get_base_url()}/availability'
            resp = requests.post(
                url,
                headers=self._get_headers(),
                data=xml_payload,
                timeout=30,
            )
            resp.raise_for_status()
            return {'status': resp.status_code, 'body': resp.text[:2000]}
        except requests.RequestException as e:
            _logger.error('Booking.com availability push failed: %s', e)
            raise

    def _build_availability_xml(self, data):
        """Build OTA_HotelAvailNotifRQ XML payload."""
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<OTA_HotelAvailNotifRQ xmlns="http://www.opentravel.org/OTA/2003/05">',
            f'  <AvailStatusMessages HotelCode="{self.property_id}">',
        ]
        for room_type_id, dates in data.items():
            for date_str, count in dates.items():
                parts.append(
                    f'    <AvailStatusMessage>'
                    f'<StatusApplicationControl Start="{date_str}" End="{date_str}" '
                    f'InvTypeCode="{room_type_id}"/>'
                    f'<LengthsOfStay/>'
                    f'<BookingLimit>{count}</BookingLimit>'
                    f'</AvailStatusMessage>'
                )
        parts.append('  </AvailStatusMessages>')
        parts.append('</OTA_HotelAvailNotifRQ>')
        return '\n'.join(parts)

    def push_rates(self, data):
        if not data:
            return None
        try:
            xml_payload = self._build_rate_xml(data)
            url = f'{self._get_base_url()}/rates'
            resp = requests.post(
                url,
                headers=self._get_headers(),
                data=xml_payload,
                timeout=30,
            )
            resp.raise_for_status()
            return {'status': resp.status_code, 'body': resp.text[:2000]}
        except requests.RequestException as e:
            _logger.error('Booking.com rate push failed: %s', e)
            raise

    def _build_rate_xml(self, data):
        """Build OTA_HotelRatePlanNotifRQ XML payload."""
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<OTA_HotelRatePlanNotifRQ xmlns="http://www.opentravel.org/OTA/2003/05">',
            f'  <RatePlans HotelCode="{self.property_id}">',
        ]
        for rate_plan_id, room_types in data.items():
            parts.append(f'    <RatePlan RatePlanCode="{rate_plan_id}">')
            for room_type_id, dates in room_types.items():
                for date_str, amount in dates.items():
                    parts.append(
                        f'      <Rate InvTypeCode="{room_type_id}" '
                        f'Start="{date_str}" End="{date_str}">'
                        f'<BaseByGuestAmt AmountAfterTax="{amount:.2f}"/>'
                        f'</Rate>'
                    )
            parts.append('    </RatePlan>')
        parts.append('  </RatePlans>')
        parts.append('</OTA_HotelRatePlanNotifRQ>')
        return '\n'.join(parts)

    def push_restrictions(self, data):
        if not data:
            return None
        try:
            xml_payload = self._build_restriction_xml(data)
            url = f'{self._get_base_url()}/restrictions'
            resp = requests.post(
                url,
                headers=self._get_headers(),
                data=xml_payload,
                timeout=30,
            )
            resp.raise_for_status()
            return {'status': resp.status_code, 'body': resp.text[:2000]}
        except requests.RequestException as e:
            _logger.error('Booking.com restriction push failed: %s', e)
            raise

    def _build_restriction_xml(self, data):
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<OTA_HotelAvailNotifRQ xmlns="http://www.opentravel.org/OTA/2003/05">',
            f'  <AvailStatusMessages HotelCode="{self.property_id}">',
        ]
        for rate_plan_id, dates in data.items():
            for date_str, restrictions in dates.items():
                stop_sell_val = '1' if restrictions.get('stop_sell') else '0'
                min_stay = restrictions.get('min_stay', 1)
                parts.append(
                    f'    <AvailStatusMessage>'
                    f'<StatusApplicationControl Start="{date_str}" End="{date_str}" '
                    f'RatePlanCode="{rate_plan_id}"/>'
                    f'<LengthsOfStay><LengthOfStay MinMaxMessageType="MinLOS" '
                    f'Time="{min_stay}"/></LengthsOfStay>'
                    f'<RestrictionStatus Restriction="Master" Status="{stop_sell_val}"/>'
                    f'</AvailStatusMessage>'
                )
        parts.append('  </AvailStatusMessages>')
        parts.append('</OTA_HotelAvailNotifRQ>')
        return '\n'.join(parts)

    def push_cancellation(self, channel_booking_id):
        if not channel_booking_id:
            return None
        _logger.info(
            'Booking.com: cancellation acknowledged for %s (push-back not '
            'required for Booking.com — they initiate cancellations)',
            channel_booking_id,
        )
        return {'acknowledged': True}

    def parse_booking_webhook(self, payload):
        """Parse Booking.com reservation notification.

        Expected payload keys (simplified from actual XML-converted dict):
            reservation_id, guest_first_name, guest_last_name, email, phone,
            checkin, checkout, room_id (their room type code), adults, children,
            total_price, currency, remarks
        """
        return {
            'channel_booking_id': str(payload.get('reservation_id', '')),
            'guest_name': '{} {}'.format(
                payload.get('guest_first_name', ''),
                payload.get('guest_last_name', ''),
            ).strip(),
            'guest_email': payload.get('email', ''),
            'guest_phone': payload.get('phone', ''),
            'checkin_date': payload.get('checkin', ''),
            'checkout_date': payload.get('checkout', ''),
            'channel_room_type_id': str(payload.get('room_id', '')),
            'adults': int(payload.get('adults', 1)),
            'children': int(payload.get('children', 0)),
            'total_amount': float(payload.get('total_price', 0)),
            'notes': payload.get('remarks', ''),
        }

    def parse_cancellation_webhook(self, payload):
        return {
            'channel_booking_id': str(payload.get('reservation_id', '')),
        }
