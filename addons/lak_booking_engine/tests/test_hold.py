# -*- coding: utf-8 -*-
import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged

from ..models.booking_quote import BookingInputError
from .common import BookingEngineCase

ACCT = 'ZZ-TEST-2626'


def _setup_bank(env):
    Param = env['ir.config_parameter'].sudo()
    Param.set_param('lak_booking_engine.bank_account', ACCT)
    bank = env['res.partner.bank'].create({
        'acc_number': ACCT,
        'partner_id': env.company.partner_id.id,
        'acc_holder_name': 'Công Ty TNHH Đường Mòn Cao Nguyên',
    })
    return env['account.journal'].create({
        'name': 'ZZ MB Transfers', 'type': 'bank', 'code': 'ZZMB',
        'bank_account_id': bank.id,
    })


@tagged('post_install', '-at_install')
class TestHold(BookingEngineCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Hold = cls.env['lak.booking.hold']
        cls.journal = _setup_bank(cls.env)

    def _quote(self, adults=2, children=0, nights=2):
        result = self.Quote.search_offers(
            self.start.isoformat(), (self.start + timedelta(days=nights)).isoformat(),
            adults, children)
        offer = next(o for o in result['offers'] if o['room_type_id'] == self.room_type.id)
        return offer

    def _hold(self, offer=None, email='zz.guest@example.com', ip='10.9.9.9', **guest):
        offer = offer or self._quote()
        g = {'name': 'Zz Guest', 'email': email, 'phone': '+84 90 000 0000'}
        g.update(guest)
        view = self.Hold.create_from_web({'quote': offer['quote'], 'guest': g}, client_ip=ip)
        return self.Hold.search([('name', '=', view['reference'])]), view

    # ── creation ──────────────────────────────────────────────────────
    def test_hold_books_draft_rooms_at_the_quoted_price(self):
        offer = self._quote(adults=3, children=1)          # 2 rooms
        hold, view = self._hold(offer)
        res = hold.reservation_ids
        self.assertEqual(len(res), 2)
        self.assertEqual(set(res.mapped('state')), {'draft'})
        self.assertEqual(len(res.room_id), 2, 'each room assigned once')
        self.assertEqual(res.room_id.room_type_id, self.room_type)
        self.assertEqual(sorted(res.mapped('adults')), [1, 2])
        self.assertEqual(sum(res.mapped('children')), 1)
        self.assertTrue(all(res.mapped('payment_required')))
        self.assertEqual(hold.amount, offer['total'])
        self.assertEqual(view['amount'], sum(res.mapped('total_amount')))
        self.assertEqual(view['bank']['account_number'], ACCT)
        self.assertEqual(view['bank']['transfer_note'], hold.name)
        self.assertIn('970422-%s' % ACCT, view['qr_url'])
        self.assertIn('CONG%20TY%20TNHH%20DUONG%20MON', view['qr_url'])
        hours = (hold.expires_at - fields.Datetime.now()).total_seconds() / 3600
        self.assertAlmostEqual(hours, 24, delta=0.1)
        self.assertTrue(hold.name.startswith('LAK'))
        self.assertFalse(set(hold.name[3:]) & set('01OIL'))

    def test_hold_counts_against_availability(self):
        self._hold()
        self.assertEqual(self._free(), 2)

    def test_two_holds_never_share_a_room(self):
        offer = self._quote()
        h1, _v = self._hold(offer, email='a@example.com')
        h2, _v = self._hold(offer, email='b@example.com')
        self.assertNotEqual(h1.reservation_ids.room_id, h2.reservation_ids.room_id)

    def test_sold_out_after_quote(self):
        offer = self._quote(adults=6)                       # all 3 rooms
        self._book(state='confirmed', room_id=self.rooms[0].id)
        with self.assertRaises(BookingInputError) as ctx:
            self._hold(offer)
        self.assertEqual(ctx.exception.code, 'not_available')

    def test_price_change_after_quote_is_refused(self):
        offer = self._quote()
        self.room_type.base_rate = 1600000.0
        with self.assertRaises(BookingInputError) as ctx:
            self._hold(offer)
        self.assertEqual(ctx.exception.code, 'price_changed')

    def test_bad_token_and_bad_guest(self):
        with self.assertRaises(BookingInputError) as ctx:
            self.Hold.create_from_web({'quote': 'nonsense', 'guest': {}})
        self.assertEqual(ctx.exception.code, 'quote_expired')
        offer = self._quote()
        for guest in ({'name': 'Zz', 'email': 'not-an-email'},
                      {'name': '', 'email': 'a@example.com'},
                      {'name': 'Zz Guest', 'email': 'a@example.com', 'phone': 'call me'}):
            with self.assertRaises(BookingInputError) as ctx:
                self.Hold.create_from_web({'quote': offer['quote'], 'guest': guest})
            self.assertEqual(ctx.exception.code, 'bad_guest')

    def test_existing_partner_is_reused_but_never_overwritten(self):
        partner = self.env['res.partner'].create({
            'name': 'Real Person', 'email': 'zz.real@example.com', 'phone': '0123'})
        hold, _v = self._hold(email='ZZ.Real@example.com', name='Someone Else', phone='0999 999 999')
        self.assertEqual(hold.guest_id, partner)
        self.assertEqual(partner.name, 'Real Person')
        self.assertEqual(partner.phone, '0123')
        self.assertEqual(hold.guest_name, 'Someone Else')

    def test_caps_on_pending_holds(self):
        self._hold(email='cap@example.com', ip='10.1.1.1')
        self._hold(email='cap@example.com', ip='10.1.1.2')
        with self.assertRaises(BookingInputError) as ctx:
            self._hold(email='cap@example.com', ip='10.1.1.3')
        self.assertEqual(ctx.exception.code, 'too_many_holds')

    def test_infants_ride_along(self):
        """Infants (0-6) take no bed and no price, but are recorded."""
        base = self._quote(adults=2)
        result = self.Quote.search_offers(
            self.start.isoformat(), (self.start + timedelta(days=2)).isoformat(), 2, 0, 3)
        offer = next(o for o in result['offers'] if o['room_type_id'] == self.room_type.id)
        self.assertEqual(result['infants'], 3)
        self.assertEqual(offer['rooms_needed'], 1)
        self.assertEqual(offer['total'], base['total'])
        hold, view = self._hold(offer)
        self.assertEqual(hold.infants, 3)
        self.assertEqual(view['infants'], 3)
        self.assertEqual(hold.reservation_ids.infants, 3)
        # Spread over the rooms of a multi-room booking.
        result = self.Quote.search_offers(
            self.start.isoformat(), (self.start + timedelta(days=2)).isoformat(), 4, 0, 3)
        offer = next(o for o in result['offers'] if o['room_type_id'] == self.room_type.id)
        hold, _v = self._hold(offer, email='zz.inf2@example.com', ip='10.3.3.3')
        self.assertEqual(sorted(hold.reservation_ids.mapped('infants')), [1, 2])

    def test_bad_infant_counts_refused(self):
        for bad in (-1, 7, 'x'):
            with self.assertRaises(BookingInputError) as ctx:
                self.Quote.search_offers(
                    self.start.isoformat(), (self.start + timedelta(days=1)).isoformat(), 2, 0, bad)
            self.assertEqual(ctx.exception.code, 'bad_party')

    def test_party_split(self):
        split = self.Quote._party_split
        self.assertEqual(split(3, 1, 2), [(2, 1), (1, 0)])
        self.assertEqual(split(4, 0, 2), [(2, 0), (2, 0)])
        self.assertIsNone(split(1, 3, 2), 'a child never gets a room alone')

    # ── reception ─────────────────────────────────────────────────────
    def test_confirm_payment_confirms_and_pays_every_room(self):
        hold, _v = self._hold(self._quote(adults=4))        # 2 rooms
        hold.action_confirm_payment()
        self.assertEqual(hold.state, 'confirmed')
        for res in hold.reservation_ids:
            self.assertEqual(res.state, 'confirmed')
            self.assertEqual(res.folio_id.amount_paid, res.total_amount)
            self.assertEqual(res.folio_id.payment_ids.journal_id, self.journal)
            self.assertTrue(res._prepayment_received(), 'check-in must not be barred')
        with self.assertRaises(UserError):
            hold.action_confirm_payment()

    def test_confirm_refused_when_booking_changed_since(self):
        hold, _v = self._hold()
        hold.reservation_ids.checkout_date = self.start + timedelta(days=3)
        with self.assertRaises(UserError):
            hold.action_confirm_payment()
        self.assertEqual(hold.state, 'pending')
        self.assertEqual(hold.reservation_ids.state, 'draft')

    def test_reception_user_can_work_the_booking(self):
        """Reception holds no accounting rights; the screen and both buttons
        must still work for them."""
        user = self.env['res.users'].create({
            'name': 'Zz Reception', 'login': 'zz.reception.hold',
            'group_ids': [(6, 0, [self.env.ref('hotel_core.group_hotel_reception').id])],
        })
        hold, _v = self._hold(self._quote(adults=4))
        other, _v = self._hold(email='zz.other@example.com', ip='10.2.2.2')
        as_rec = hold.with_user(user)
        as_rec.read(['name', 'amount_display', 'qr_url', 'expiring_soon', 'expires_display', 'state'])
        as_rec.reservation_ids.folio_id.mapped('name')
        self.env['lak.booking.hold'].with_user(user).search([('expiring_soon', '=', True)])
        as_rec.action_confirm_payment()
        self.assertEqual(hold.state, 'confirmed')
        self.assertTrue(all(r._prepayment_received() for r in hold.reservation_ids))
        other.with_user(user).action_cancel()
        self.assertEqual(other.state, 'cancelled')

    def test_cancel_releases_rooms(self):
        hold, _v = self._hold()
        hold.action_cancel()
        self.assertEqual(hold.state, 'cancelled')
        self.assertEqual(hold.reservation_ids.state, 'cancelled')
        self.assertEqual(self._free(), 3)

    # ── expiry ────────────────────────────────────────────────────────
    def test_expired_hold_releases_rooms(self):
        hold, _v = self._hold()
        hold.expires_at = fields.Datetime.now() - timedelta(minutes=1)
        self.Hold._cron_expire_holds()
        self.assertEqual(hold.state, 'expired')
        self.assertEqual(hold.reservation_ids.state, 'cancelled')
        self.assertEqual(self._free(), 3)

    def test_expiry_leaves_a_booking_reception_confirmed_alone(self):
        hold, _v = self._hold()
        hold.reservation_ids.with_context(skip_confirmation_email=True).action_confirm()
        hold.expires_at = fields.Datetime.now() - timedelta(minutes=1)
        self.Hold._cron_expire_holds()
        self.assertEqual(hold.state, 'confirmed')
        self.assertEqual(hold.reservation_ids.state, 'confirmed')

    def test_unexpired_hold_is_kept(self):
        hold, _v = self._hold()
        self.Hold._cron_expire_holds()
        self.assertEqual(hold.state, 'pending')

    def test_public_lookup_needs_the_token(self):
        hold, view = self._hold()
        self.assertEqual(self.Hold.find_public(view['reference'], view['token']), hold)
        self.assertFalse(self.Hold.find_public(view['reference'], 'wrong'))
        self.assertFalse(self.Hold.find_public(view['reference'], ''))


@tagged('post_install', '-at_install')
class TestHoldApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Param = cls.env['ir.config_parameter'].sudo()
        _setup_bank(cls.env)
        cls.start = cls.env['lak.booking.quote']._hotel_today() + timedelta(days=401)
        cls.room_type = cls.env['hotel.room.type'].create({
            'name': 'ZZ Hold Api Tent', 'capacity': 2, 'base_rate': 1100000.0,
        })
        cls.env['hotel.room'].create({'name': 'ZZH-01', 'room_type_id': cls.room_type.id})
        cls.Param.set_param('lak_booking_engine.enabled', '1')
        cls.Param.set_param('lak_booking_engine.turnstile_secret', ' ')
        # Real unpaid holds on the database must not trip the caps here.
        for key in ('max_pending_per_ip', 'max_pending_per_email', 'max_pending_rooms'):
            cls.Param.set_param('lak_booking_engine.%s' % key, '1000')

    def _offer(self):
        result = self.env['lak.booking.quote'].search_offers(
            self.start.isoformat(), (self.start + timedelta(days=1)).isoformat(), 2, 0)
        return next(o for o in result['offers'] if o['room_type_id'] == self.room_type.id)

    def _post(self, body):
        return self.url_open('/api/book/hold', data=json.dumps(body),
                             headers={'Content-Type': 'application/json'})

    def _body(self):
        return {'quote': self._offer()['quote'],
                'guest': {'name': 'Zz Api', 'email': 'zz.api@example.com'}}

    def test_refused_without_bot_check_on_a_live_server(self):
        self.Param.set_param('lak_booking_engine.allow_without_turnstile', '0')
        resp = self._post(self._body())
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['error'], 'bot_check')

    def test_hold_then_status(self):
        self.Param.set_param('lak_booking_engine.allow_without_turnstile', '1')
        resp = self._post(self._body())
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data['state'], 'pending')
        self.assertEqual(data['amount'], 1100000.0)
        status = self.url_open('/api/book/hold/status?ref=%s&token=%s' % (data['reference'], data['token']))
        self.assertEqual(status.json()['reference'], data['reference'])
        self.assertEqual(self.url_open('/api/book/hold/status?ref=%s&token=x' % data['reference']).status_code, 404)
        # The room is gone: a second booking of the same offer is refused
        # and leaves nothing behind.
        before = self.env['hotel.reservation'].search_count([('room_type_id', '=', self.room_type.id)])
        again = self._post(dict(self._body_from(data)))
        self.assertEqual(again.status_code, 409, again.text)
        after = self.env['hotel.reservation'].search_count([('room_type_id', '=', self.room_type.id)])
        self.assertEqual(before, after)

    def _body_from(self, _data):
        # A fresh token for the same stay, signed now (the search no longer
        # offers the room, so build it by hand).
        Quote = self.env['lak.booking.quote']
        token = Quote.make_quote_token({
            'room_type_id': self.room_type.id,
            'checkin': self.start.isoformat(),
            'checkout': (self.start + timedelta(days=1)).isoformat(),
            'adults': 2, 'children': 0, 'rooms': 1, 'total': 1100000.0,
        })
        return {'quote': token, 'guest': {'name': 'Zz Other', 'email': 'zz.other@example.com'}}

    def test_disabled(self):
        self.Param.set_param('lak_booking_engine.enabled', '0')
        self.assertEqual(self._post({}).status_code, 503)
        self.assertEqual(self.url_open('/book').status_code, 503)

    def test_book_page_served_when_enabled(self):
        resp = self.url_open('/book')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('/api/book/hold', resp.text)


@tagged('post_install', '-at_install')
class TestRoomContentApi(HttpCase):

    # 1x1 PNG
    PIXEL = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ'
             'DwAEhQGAhKmMIQAAAABJRU5ErkJggg==')

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('lak_booking_engine.enabled', '1')
        cls.room_type = cls.env['hotel.room.type'].create({
            'name': 'ZZ Photo Tent', 'capacity': 2, 'base_rate': 1000000.0,
            'web_summary': 'A tent by the lake.',
            'web_description': '<p>Nice.</p><script>alert(1)</script>',
            'web_facilities': 'Balcony\n- Hot shower\n\n',
            'web_beds': '1 king bed',
        })
        cls.image = cls.env['lak.room.type.image'].create({
            'room_type_id': cls.room_type.id, 'image_1920': cls.PIXEL})

    def test_rooms_endpoint_carries_content(self):
        rooms = self.url_open('/api/book/rooms').json()['rooms']
        room = next(r for r in rooms if r['room_type_id'] == self.room_type.id)
        self.assertEqual(room['summary'], 'A tent by the lake.')
        self.assertEqual(room['facilities'], ['Balcony', 'Hot shower'])
        self.assertNotIn('<script', room['description_html'])
        self.assertEqual(len(room['photos']), 1)
        self.assertTrue(room['photos'][0]['medium'].startswith('/api/book/photo/%d/1024' % self.image.id))

    def test_photo_route(self):
        resp = self.url_open('/api/book/photo/%d/512' % self.image.id)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers['Content-Type'].startswith('image/'))
        self.assertEqual(self.url_open('/api/book/photo/%d/77' % self.image.id).status_code, 404)
        self.room_type.website_bookable = False
        self.assertEqual(self.url_open('/api/book/photo/%d/512' % self.image.id).status_code, 404)
