# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo.tests import tagged

from .common import AiosellCase


def _payload(config, today, **overrides):
    payload = {
        'action': 'book',
        'hotelCode': config.hotel_code,
        'channel': 'Booking.com',
        'bookingId': '111222333',
        'cmBookingId': 'AAABBBCCC',
        'bookedOn': '2026-09-01 15:25:35',
        'checkin': str(today + timedelta(days=1)),
        'checkout': str(today + timedelta(days=3)),
        'segment': 'OTA',
        'specialRequests': 'Late arrival',
        'pah': False,
        'amount': {'amountAfterTax': 2400000.0, 'amountBeforeTax': 2181818.0,
                   'tax': 218182.0, 'currency': 'VND', 'commission': 360000.0},
        'guest': {
            'firstName': 'Astrid', 'lastName': 'Haerens',
            'email': 'astrid@example.com', 'phone': '0900000000',
            'address': {'line1': '1', 'city': 'Antwerp', 'country': 'Belgium'},
        },
        'rooms': [{
            'roomCode': 'bungalow',
            'rateplanCode': 'bungalow-d-ep',
            'guestName': 'Astrid Haerens',
            'occupancy': {'adults': 2, 'children': 0},
            'prices': [{'date': str(today + timedelta(days=1)), 'sellRate': 1000000.0},
                       {'date': str(today + timedelta(days=2)), 'sellRate': 1200000.0}],
        }],
    }
    payload.update(overrides)
    return payload


@tagged('post_install', '-at_install')
class TestInbound(AiosellCase):
    """OTA bookings become reservations; changes we cannot apply get flagged."""

    def _push(self, **overrides):
        return self.env['aiosell.config'].handle_reservation_push(
            _payload(self.config, self.today, **overrides))

    def _reservations(self, booking_id='111222333'):
        return self.env['hotel.reservation'].search([
            ('aiosell_booking_id', '=', booking_id)])

    def test_book_creates_a_confirmed_reservation(self):
        status, body = self._push()
        self.assertEqual(status, 200)
        self.assertTrue(body['success'])

        reservation = self._reservations()
        self.assertEqual(len(reservation), 1)
        self.assertEqual(reservation.state, 'confirmed')
        self.assertEqual(reservation.room_type_id, self.type_bungalow)
        self.assertTrue(reservation.room_id, 'A free room was assigned.')
        self.assertEqual(reservation.adults, 2)
        self.assertEqual(reservation.aiosell_channel, 'Booking.com')
        self.assertEqual(reservation.aiosell_cm_booking_id, 'AAABBBCCC')
        self.assertTrue(reservation.folio_id, 'Confirming opens the folio.')

    def test_ota_rate_beats_the_pms_price_list(self):
        """The guest agreed the channel's price, so the folio must use it."""
        self._push()
        reservation = self._reservations()
        self.assertEqual(reservation.ota_nightly_rate, 1100000.0)
        self.assertEqual(reservation.nightly_rate, 1100000.0)
        self.assertEqual(
            reservation.total_amount, 2200000.0,
            'Two nights at the averaged channel rate, not the 1,500,000 plan.')

    def test_prepaid_booking_is_marked_paid_to_the_channel(self):
        self._push()
        self.assertTrue(self._reservations().prepaid)

    def test_pay_at_hotel_booking_is_not_marked_prepaid(self):
        self._push(pah=True)
        reservation = self._reservations()
        self.assertFalse(reservation.prepaid)
        self.assertFalse(reservation.payment_required)

    def test_guest_and_source_are_created(self):
        self._push()
        reservation = self._reservations()
        self.assertEqual(reservation.guest_id.name, 'Astrid Haerens')
        self.assertEqual(reservation.guest_id.email, 'astrid@example.com')
        self.assertEqual(reservation.source_id.name, 'Booking.com')

    def test_existing_guest_is_reused_by_email(self):
        known = self.env['res.partner'].create({
            'name': 'Astrid H', 'email': 'astrid@example.com'})
        self._push()
        self.assertEqual(self._reservations().guest_id, known)

    def test_missing_guest_details_are_tolerated(self):
        """OTAs mask contact details; a booking must never be rejected for it."""
        status, body = self._push(guest={})
        self.assertTrue(body['success'])
        reservation = self._reservations()
        self.assertEqual(reservation.guest_id.name, 'Astrid Haerens',
                         'Fell back to the name on the room.')

    def test_no_guest_name_at_all_still_books(self):
        payload = _payload(self.config, self.today, guest={})
        payload['rooms'][0]['guestName'] = None
        status, body = self.env['aiosell.config'].handle_reservation_push(payload)
        self.assertTrue(body['success'])
        self.assertIn('111222333', self._reservations().guest_id.name)

    def test_repeated_book_does_not_duplicate(self):
        """Aiosell retries on any non-2xx, so delivery must be idempotent."""
        self._push()
        self._push()
        self.assertEqual(len(self._reservations()), 1)

    def test_modify_updates_in_place(self):
        self._push()
        original = self._reservations()
        self._push(action='modify', checkout=str(self.today + timedelta(days=4)))
        updated = self._reservations()
        self.assertEqual(updated, original, 'Same record, not a second one.')
        self.assertEqual(updated.checkout_date, self.today + timedelta(days=4))

    def test_cancel_cancels(self):
        self._push()
        status, body = self._push(action='cancel')
        self.assertTrue(body['success'])
        self.assertEqual(self._reservations().state, 'cancelled')

    def test_cancel_of_an_unknown_booking_is_harmless(self):
        status, body = self._push(action='cancel', bookingId='999')
        self.assertEqual(status, 200)
        self.assertTrue(body['success'])

    def test_cancel_of_a_checked_in_guest_is_refused_and_flagged(self):
        """Money has moved; a human has to settle it, and retrying cannot help."""
        self._push(checkin=str(self.today))
        reservation = self._reservations()
        reservation.action_check_in()

        status, body = self._push(action='cancel')
        self.assertEqual(status, 200)
        self.assertTrue(body['success'], 'Stops Aiosell retrying forever.')
        self.assertEqual(reservation.state, 'checked_in', 'Untouched.')

        log = self.env['aiosell.sync.log'].search([
            ('booking_id', '=', '111222333'), ('operation', '=', 'cancel'),
        ], limit=1)
        self.assertEqual(log.state, 'refused')
        self.assertTrue(
            reservation.activity_ids, 'Reception is asked to deal with it.')

    def test_modify_of_a_checked_in_guest_is_refused(self):
        self._push(checkin=str(self.today))
        reservation = self._reservations()
        reservation.action_check_in()
        self._push(action='modify', checkin=str(self.today),
                   checkout=str(self.today + timedelta(days=9)))
        self.assertEqual(reservation.checkout_date, self.today + timedelta(days=3))

    def test_unmapped_room_code_is_refused_with_a_readable_reason(self):
        payload = _payload(self.config, self.today)
        payload['rooms'][0]['roomCode'] = 'penthouse'
        status, body = self.env['aiosell.config'].handle_reservation_push(payload)
        self.assertEqual(status, 200)
        self.assertIn('not mapped', body['message'])
        self.assertFalse(self._reservations())

    def test_unknown_hotel_code_is_rejected(self):
        status, body = self._push(hotelCode='someone-elses-hotel')
        self.assertFalse(body['success'])
        self.assertIn('Unknown hotelCode', body['message'])

    def test_unsupported_action_is_rejected(self):
        status, body = self._push(action='reprice')
        self.assertFalse(body['success'])

    def test_booking_without_a_free_room_stays_draft_with_an_activity(self):
        for room in self.bungalows:
            room.write({'status': 'maintenance'})
            self.env['hotel.reservation'].create({
                'guest_id': self.guest.id,
                'room_type_id': self.type_bungalow.id,
                'room_id': room.id,
                'state': 'confirmed',
                'checkin_date': self.today,
                'checkout_date': self.today + timedelta(days=5),
            })
        status, body = self._push()
        self.assertTrue(body['success'])
        reservation = self._reservations()
        self.assertEqual(reservation.state, 'draft')
        self.assertFalse(reservation.room_id)
        self.assertTrue(reservation.activity_ids)

    def test_two_ota_bookings_do_not_share_a_room(self):
        self.config.auto_confirm_bookings = False
        self._push()
        self._push(bookingId='444555666')
        rooms = (self._reservations() | self._reservations('444555666')).mapped('room_id')
        self.assertEqual(len(rooms), 2, 'Each draft booking got its own room.')

    def test_multi_room_booking_creates_one_reservation_per_room(self):
        payload = _payload(self.config, self.today)
        payload['rooms'].append({
            'roomCode': 'tent',
            'rateplanCode': 'tent-d-ep',
            'guestName': 'Astrid Haerens',
            'occupancy': {'adults': 1, 'children': 0},
            'prices': [{'date': str(self.today + timedelta(days=1)), 'sellRate': 800000.0},
                       {'date': str(self.today + timedelta(days=2)), 'sellRate': 800000.0}],
        })
        self.env['aiosell.config'].handle_reservation_push(payload)
        reservations = self._reservations()
        self.assertEqual(len(reservations), 2)
        self.assertEqual(
            set(reservations.mapped('room_type_id.name')),
            {'AIO Bungalow', 'AIO Tent'})

    def test_modify_that_drops_a_room_cancels_the_leftover(self):
        payload = _payload(self.config, self.today)
        payload['rooms'].append({
            'roomCode': 'tent', 'rateplanCode': 'tent-d-ep',
            'occupancy': {'adults': 1, 'children': 0},
            'prices': [{'date': str(self.today + timedelta(days=1)),
                        'sellRate': 800000.0}],
        })
        self.env['aiosell.config'].handle_reservation_push(payload)
        self.assertEqual(len(self._reservations()), 2)

        self._push(action='modify')
        reservations = self._reservations()
        self.assertEqual(len(reservations), 2, 'The record is kept for history.')
        self.assertEqual(
            reservations.filtered(lambda r: r.state == 'cancelled').room_type_id,
            self.type_tent)

    def test_the_channel_email_is_not_duplicated_by_the_pms(self):
        self._push()
        self.assertFalse(self._reservations().send_confirmation)

    def test_payload_is_kept_for_disputes(self):
        self._push()
        self.assertIn('"bookingId": "111222333"',
                      self._reservations().aiosell_payload)
