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

    # ── Filling a company in from its tax code ───────────────────────────

    def test_known_tax_code_warns_instead_of_duplicating(self):
        """A tax code identifies a company; a second record is a duplicate."""
        company = self.Partner.new({'is_company': True, 'vat': '0100112437'})
        with patch(LOOKUP_PATH) as get:
            result = company._onchange_vat_fill_from_registry()

        self.assertTrue(result and result.get('warning'))
        self.assertIn(self.agency.name, result['warning']['message'])
        get.assert_not_called()

    def test_new_tax_code_fills_the_company_in(self):
        company = self.Partner.new({'is_company': True, 'vat': '0101248141'})
        with patch(LOOKUP_PATH, return_value=FakeResponse(FPT_PAYLOAD)):
            company._onchange_vat_fill_from_registry()

        self.assertEqual(company.name, 'CÔNG TY CỔ PHẦN FPT')
        self.assertIn('Phạm Văn Bạch', company.street)
        self.assertEqual(company.country_id, self.env.ref('base.vn'))
        self.assertIn('FPT CORPORATION', company.comment,
                      'the international name should be kept')
        self.assertIn('NNT đang hoạt động', company.comment,
                      'the tax status should be kept')

    def test_lookup_never_overwrites_a_name_already_typed(self):
        """Reception's own input wins; the difference is reported instead."""
        company = self.Partner.new({
            'is_company': True, 'name': 'FPT (as we know them)',
            'vat': '0101248141',
        })
        with patch(LOOKUP_PATH, return_value=FakeResponse(FPT_PAYLOAD)):
            result = company._onchange_vat_fill_from_registry()

        self.assertEqual(company.name, 'FPT (as we know them)')
        self.assertTrue(result and result.get('warning'))
        self.assertIn('CÔNG TY CỔ PHẦN FPT', result['warning']['message'])
        self.assertIn('Phạm Văn Bạch', company.street,
                      'blank fields should still be filled')

    def test_individuals_are_left_alone(self):
        """A personal tax ID is not a company lookup."""
        person = self.Partner.new({'is_company': False, 'vat': '079123456789'})
        with patch(LOOKUP_PATH) as get:
            person._onchange_vat_fill_from_registry()
        get.assert_not_called()

    def test_malformed_tax_code_is_not_sent_to_the_registry(self):
        company = self.Partner.new({'is_company': True, 'vat': '123'})
        with patch(LOOKUP_PATH) as get:
            company._onchange_vat_fill_from_registry()
        get.assert_not_called()

    def test_tax_code_spacing_is_ignored(self):
        company = self.Partner.new({'is_company': True, 'vat': '0101 248 141'})
        with patch(LOOKUP_PATH,
                   return_value=FakeResponse(FPT_PAYLOAD)) as get:
            company._onchange_vat_fill_from_registry()
        get.assert_called_once()
        self.assertEqual(company.name, 'CÔNG TY CỔ PHẦN FPT')

    def test_registry_not_found_warns_and_fills_nothing(self):
        """Code 51 arrives as HTTP 200 — the body decides, not the status."""
        company = self.Partner.new({'is_company': True, 'vat': '0000000000'})
        with patch(LOOKUP_PATH, return_value=FakeResponse(NOT_FOUND_PAYLOAD)):
            result = company._onchange_vat_fill_from_registry()

        self.assertTrue(result and result.get('warning'))
        self.assertFalse(company.name)

    def test_rate_limiting_warns_instead_of_blocking_the_company(self):
        company = self.Partner.new({'is_company': True, 'vat': '0101248141'})
        with patch(LOOKUP_PATH, return_value=FakeResponse(None, 429)):
            result = company._onchange_vat_fill_from_registry()

        self.assertTrue(result and result.get('warning'),
                        'a 429 must not stop anyone creating the company')

    def test_registry_timeout_warns_instead_of_blocking(self):
        company = self.Partner.new({'is_company': True, 'vat': '0101248141'})
        with patch(LOOKUP_PATH, side_effect=requests.exceptions.Timeout()):
            result = company._onchange_vat_fill_from_registry()
        self.assertTrue(result and result.get('warning'))

    # ── The lookup helpers themselves ────────────────────────────────────

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

    def test_find_or_create_reuses_a_company_already_on_file(self):
        with patch(LOOKUP_PATH) as get:
            found = self.Partner._vn_find_or_create_by_vat('0100112437')
        self.assertEqual(found, self.agency)
        get.assert_not_called()

    def test_find_or_create_puts_a_registry_company_on_file(self):
        with patch(LOOKUP_PATH, return_value=FakeResponse(FPT_PAYLOAD)):
            created = self.Partner._vn_find_or_create_by_vat(
                '0101248141', extra_vals={'is_hotel_agency': True})

        self.assertEqual(created.vat, '0101248141')
        self.assertTrue(created.is_company)
        self.assertTrue(
            created.is_hotel_agency,
            'without is_hotel_agency the company fails the agency domain',
        )

    def test_find_or_create_returns_nothing_for_an_unknown_code(self):
        with patch(LOOKUP_PATH, return_value=FakeResponse(NOT_FOUND_PAYLOAD)):
            self.assertFalse(
                self.Partner._vn_find_or_create_by_vat('0000000000'))

    # ── Group bookings get the same behaviour ────────────────────────────

    def test_group_booking_finds_the_guest_by_phone_too(self):
        group = self.env['hotel.booking.group'].new({'guest_phone': '0912345678'})
        group._onchange_guest_phone()
        self.assertEqual(group.guest_id, self.guest)

