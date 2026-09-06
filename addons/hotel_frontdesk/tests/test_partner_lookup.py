# -*- coding: utf-8 -*-
"""Finding the customer from a phone number or a tax code.

The registry calls are patched throughout: the fixtures below are the real
payloads api.vietqr.io returned for Vietcombank, FPT and an unknown code, so
the parsing is tested against what the service actually sends without the
suite depending on the network (or on staying under its rate limit).
"""
import json
from unittest.mock import patch

import requests

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

LOOKUP_PATH = 'odoo.addons.hotel_frontdesk.models.res_partner.requests.get'

FPT_PAYLOAD = {
    'code': '00', 'desc': 'Success - Thành công',
    'data': {
        'id': '0101248141',
        'name': 'CÔNG TY CỔ PHẦN FPT',
        'internationalName': 'FPT CORPORATION',
        'shortName': 'FPT CORP',
        'address': 'Số 10 phố Phạm Văn Bạch, Phường Cầu Giấy, TP Hà Nội',
        'status': 'NNT đang hoạt động',
    },
}
NOT_FOUND_PAYLOAD = {
    'code': '51', 'desc': 'Tax not found - Mã số thuế không tồn tại',
    'data': None,
}


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if self._payload is None:
            raise ValueError('no json')
        return json.loads(json.dumps(self._payload))


@tagged('post_install', '-at_install')
class TestPartnerLookup(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env['res.partner']
        cls.Reservation = cls.env['hotel.reservation']

        # hotel_pms_test carries a copy of the real address book, which
        # already holds this number. Clear any incumbent so the "exactly one
        # match" tests below are testing the lookup, not the fixture data —
        # the whole class runs in a transaction that is rolled back.
        cls.PHONE = '0912 345 678'
        cls.Partner._vn_find_by_phone(cls.PHONE).write({'phone': False})

        cls.guest = cls.Partner.create({
            'name': 'ZZ Lookup Guest', 'phone': cls.PHONE,
        })
        cls.agency = cls.Partner.create({
            'name': 'ZZ Lookup Corp', 'is_company': True,
            'is_hotel_agency': True, 'vat': '0100112437',
        })

    # ── Phone normalisation ──────────────────────────────────────────────

    def test_phone_key_ignores_formatting_and_country_code(self):
        """The same subscriber, however it was written down."""
        keys = {
            self.Partner._vn_phone_key(raw) for raw in (
                '0912345678', '0912 345 678', '+84912345678',
                '84.912.345.678', '(091) 234 5678',
            )
        }
        self.assertEqual(keys, {'912345678'},
                         'all five spellings must reduce to one key')

    def test_phone_key_refuses_a_stub(self):
        """Too few digits to identify anyone."""
        self.assertFalse(self.Partner._vn_phone_key('0912'))
        self.assertFalse(self.Partner._vn_phone_key(''))
        self.assertFalse(self.Partner._vn_phone_key(False))

    # ── Finding a guest by phone ─────────────────────────────────────────

    def test_find_by_phone_matches_across_formats(self):
        found = self.Partner._vn_find_by_phone('+84 912 345 678')
        self.assertIn(self.guest, found,
                      'a stored 0912 345 678 must match its +84 spelling')

    def test_find_by_phone_ignores_companies(self):
        self.Partner.create({
            'name': 'ZZ Phone Co', 'is_company': True, 'phone': '0988777666',
        })
        self.assertFalse(self.Partner._vn_find_by_phone('0988777666'),
                         'the guest search must not return companies')

    def test_onchange_phone_fills_the_guest(self):
        res = self.Reservation.new({'guest_phone': '0912345678'})
        res._onchange_guest_phone()
        self.assertEqual(res.guest_id, self.guest)

    def test_onchange_phone_warns_when_several_guests_share_it(self):
        twin = self.Partner.create({
            'name': 'ZZ Lookup Twin', 'phone': '+84912345678',
        })
        res = self.Reservation.new({'guest_phone': '0912345678'})
        result = res._onchange_guest_phone()

        self.assertTrue(result and result.get('warning'),
                        'an ambiguous number must warn, not guess')
        self.assertFalse(res.guest_id,
                         'no guest may be picked when the number is ambiguous')
        self.assertIn(twin.name, result['warning']['message'])

    def test_onchange_phone_clears_a_stale_guest(self):
        """A number belonging to nobody is a new guest, not the old one."""
        res = self.Reservation.new({'guest_id': self.guest.id})
        res.guest_phone = '0900000001'
        res._onchange_guest_phone()
        self.assertFalse(res.guest_id)

    def test_onchange_phone_leaves_the_selected_guest_alone(self):
        """Showing the guest's own number is not a search."""
        res = self.Reservation.new({'guest_id': self.guest.id})
        res._onchange_guest_phone()
        self.assertEqual(res.guest_id, self.guest)

    def test_selecting_a_phoneless_guest_does_not_keep_the_typed_number(self):
        """The box mirrors the guest once one is chosen, blank phone and all.

        Otherwise the form shows, under a Phone label, a number the guest
        record itself denies having.
        """
        phoneless = self.Partner.create({'name': 'ZZ No Phone Guest'})
        res = self.Reservation.new({'guest_phone': '0900000002'})
        res.guest_id = phoneless
        self.assertFalse(res.guest_phone)

    def test_a_search_in_progress_survives_until_a_guest_is_picked(self):
        res = self.Reservation.new({'guest_phone': '0900000003'})
        self.assertEqual(res.guest_phone, '0900000003')

    # ── Finding a company by tax code ────────────────────────────────────

    def test_known_tax_code_never_reaches_the_registry(self):
        res = self.Reservation.new({'agency_vat': '0100112437'})
        with patch(LOOKUP_PATH) as get:
            res._onchange_agency_vat()
        self.assertEqual(res.agency_id, self.agency)
        get.assert_not_called()

    def test_tax_code_ignores_spacing(self):
        res = self.Reservation.new({'agency_vat': '0100 112 437'})
        with patch(LOOKUP_PATH):
            res._onchange_agency_vat()
        self.assertEqual(res.agency_id, self.agency)

    def test_unknown_tax_code_previews_the_registry_without_creating(self):
        res = self.Reservation.new({'agency_vat': '0101248141'})
        with patch(LOOKUP_PATH, return_value=FakeResponse(FPT_PAYLOAD)):
            res._onchange_agency_vat()

        self.assertTrue(res.vn_registry_found)
        self.assertEqual(res.vn_registry_name, 'CÔNG TY CỔ PHẦN FPT')
        self.assertEqual(res.vn_registry_status, 'NNT đang hoạt động')
        self.assertFalse(
            self.Partner.search([('vat', '=', '0101248141')]),
            'previewing must not put the company on file',
        )

    def test_malformed_tax_code_is_not_sent_to_the_registry(self):
        res = self.Reservation.new({'agency_vat': '123'})
        with patch(LOOKUP_PATH) as get:
            res._onchange_agency_vat()
        get.assert_not_called()
        self.assertFalse(res.vn_registry_found)

    def test_registry_not_found_warns_and_previews_nothing(self):
        """Code 51 arrives as HTTP 200 — the body decides, not the status."""
        res = self.Reservation.new({'agency_vat': '0000000000'})
        with patch(LOOKUP_PATH, return_value=FakeResponse(NOT_FOUND_PAYLOAD)):
            result = res._onchange_agency_vat()

        self.assertTrue(result and result.get('warning'))
        self.assertFalse(res.vn_registry_found)

    def test_rate_limiting_warns_instead_of_blocking_the_booking(self):
        res = self.Reservation.new({'agency_vat': '0101248141'})
        with patch(LOOKUP_PATH, return_value=FakeResponse(None, 429)):
            result = res._onchange_agency_vat()

        self.assertTrue(result and result.get('warning'),
                        'a 429 must not stop reception taking the booking')
        self.assertFalse(res.vn_registry_found)

    def test_registry_timeout_warns_instead_of_blocking(self):
        res = self.Reservation.new({'agency_vat': '0101248141'})
        with patch(LOOKUP_PATH, side_effect=requests.exceptions.Timeout()):
            result = res._onchange_agency_vat()
        self.assertTrue(result and result.get('warning'))

    # ── Putting a registry company on file ───────────────────────────────

    def test_create_from_registry_fills_the_company_in(self):
        res = self.Reservation.new({'agency_vat': '0101248141'})
        with patch(LOOKUP_PATH, return_value=FakeResponse(FPT_PAYLOAD)):
            res._onchange_agency_vat()
            res.action_create_agency_from_registry()

        partner = res.agency_id
        self.assertTrue(partner, 'the company was not selected')
        self.assertEqual(partner.vat, '0101248141')
        self.assertEqual(partner.name, 'CÔNG TY CỔ PHẦN FPT')
        self.assertIn('Phạm Văn Bạch', partner.street)
        self.assertTrue(partner.is_company)
        self.assertTrue(
            partner.is_hotel_agency,
            'without is_hotel_agency the new company fails the agency domain',
        )
        self.assertIn('FPT CORPORATION', partner.comment,
                      'the international name should be kept')
        self.assertFalse(res.vn_registry_found,
                         'the preview should clear once the company is on file')

    def test_create_from_registry_reuses_a_company_added_meanwhile(self):
        """Another user got there first: reuse, never duplicate the tax code."""
        res = self.Reservation.new({'agency_vat': '0101248141'})
        with patch(LOOKUP_PATH, return_value=FakeResponse(FPT_PAYLOAD)):
            res._onchange_agency_vat()
            meanwhile = self.Partner.create({
                'name': 'FPT (added by a colleague)', 'is_company': True,
                'is_hotel_agency': True, 'vat': '0101248141',
            })
            res.action_create_agency_from_registry()

        self.assertEqual(res.agency_id, meanwhile)
        self.assertEqual(
            self.Partner.search_count([('vat', '=', '0101248141')]), 1)

    def test_lookup_rejects_a_bad_tax_code_before_spending_a_call(self):
        with patch(LOOKUP_PATH) as get:
            with self.assertRaises(UserError):
                self.Partner._vn_lookup_tax_code('12345')
        get.assert_not_called()

    def test_lookup_accepts_the_three_valid_vn_shapes(self):
        """10-digit, 10+3 branch suffix, and the 12-digit personal tax ID."""
        for code in ('0101248141', '0101248141-001', '079123456789'):
            with patch(LOOKUP_PATH,
                       return_value=FakeResponse(NOT_FOUND_PAYLOAD)) as get:
                self.Partner._vn_lookup_tax_code(code)
                get.assert_called_once()

    # ── Group bookings get the same behaviour ────────────────────────────

    def test_group_booking_finds_the_guest_by_phone_too(self):
        group = self.env['hotel.booking.group'].new({'guest_phone': '0912345678'})
        group._onchange_guest_phone()
        self.assertEqual(group.guest_id, self.guest)

    def test_group_booking_finds_the_company_by_tax_code_too(self):
        group = self.env['hotel.booking.group'].new({'agency_vat': '0100112437'})
        with patch(LOOKUP_PATH):
            group._onchange_agency_vat()
        self.assertEqual(group.agency_id, self.agency)
