# -*- coding: utf-8 -*-
"""Canaries for the private point_of_sale APIs this module overrides.

`hotel_pos_folio` extends four underscore-private POS methods whose signatures
have already churned between major versions (they were `_loader_params_*` two
versions ago). If v20 moves them again, these tests fail with a TypeError
instead of the module silently loading an empty customer list in a live
restaurant. That is the entire point of this file — see UPGRADE_READINESS.md,
findings #1, #3 and #4.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.hotel_frontdesk.tests.common import HotelCommon


@tagged('post_install', '-at_install')
class TestPosApiSurface(HotelCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('point_of_sale.group_pos_manager')
        cls.pos_config = cls.env['pos.config'].create({
            'name': 'Test Restaurant',
        })
        cls.clearing_account = cls.env['account.account'].create({
            'code': 'TEST101950',
            'name': 'Test Room Charge Clearing',
            'account_type': 'asset_current',
            'reconcile': True,
        })

    # ── In-house flag maintenance ────────────────────────────────────────────

    def test_in_house_flags_track_the_stay(self):
        today = fields.Date.context_today(self.env['hotel.reservation'])
        res = self._make_reservation(today, today + timedelta(days=2))

        self.assertFalse(self.guest.hotel_in_house)

        res.action_confirm()
        res.action_check_in()
        self.assertTrue(self.guest.hotel_in_house,
                        'check-in must make the guest visible to POS')
        self.assertEqual(self.guest.hotel_room_number, self.room.name)
        self.assertEqual(self.guest.hotel_folio_id, res.folio_id)

        res.action_check_out()
        self.assertFalse(self.guest.hotel_in_house,
                         'check-out must hide the guest from POS')
        self.assertFalse(self.guest.hotel_room_number)

    def test_open_folio_refuses_an_invoiced_folio(self):
        """Once billed, a folio must not accept further room charges."""
        today = fields.Date.context_today(self.env['hotel.reservation'])
        res = self._make_reservation(today, today + timedelta(days=1))
        res.action_confirm()
        res.action_check_in()

        _reservation, folio = self.guest._hotel_open_folio()
        self.assertEqual(folio, res.folio_id)

        res.action_check_out()
        _reservation, folio = self.guest._hotel_open_folio()
        self.assertFalse(folio)

    # ── The private POS loader APIs ──────────────────────────────────────────

    def test_load_pos_data_domain_signature_and_behaviour(self):
        Partner = self.env['res.partner']
        # POS passes the partially-loaded session payload as `data`; core reads
        # data['pos.order'] out of it. Both the argument count and this shape
        # are part of the contract we are pinning down.
        data = {'pos.order': []}

        self.pos_config.limit_partners_to_in_house = True
        domain = Partner._load_pos_data_domain(data, self.pos_config)
        self.assertIn(('hotel_in_house', '=', True), domain,
                      'the in-house toggle must restrict the POS customer list')

        self.pos_config.limit_partners_to_in_house = False
        domain = Partner._load_pos_data_domain(data, self.pos_config)
        self.assertNotIn(('hotel_in_house', '=', True), domain,
                         'with the toggle off POS must load its normal partners')

    def test_load_pos_data_fields_extends_super(self):
        fields_list = self.env['res.partner']._load_pos_data_fields(self.pos_config)
        self.assertIn('hotel_in_house', fields_list)
        self.assertIn('hotel_room_number', fields_list)
        self.assertIn('name', fields_list,
                      'the override must extend POS fields, not replace them')

        method_fields = self.env['pos.payment.method']._load_pos_data_fields(
            self.pos_config)
        self.assertIn('is_hotel_folio', method_fields)

    def test_extract_search_term_recovers_the_typed_term(self):
        """Reverse-engineers POS's OR-domain. Fragile by nature: if POS builds
        its search domain differently in a future version, room-number search
        stops matching with no error at all."""
        Partner = self.env['res.partner']
        pos_shaped_domain = [
            '|', '|',
            ('name', 'ilike', 'Nguyen'),
            ('barcode', 'ilike', 'Nguyen'),
            ('phone', 'ilike', 'Nguyen'),
        ]
        self.assertEqual(Partner._extract_search_term(pos_shaped_domain), 'Nguyen')
        self.assertIsNone(Partner._extract_search_term([]))

    # ── The clearing-account contract ────────────────────────────────────────

    def test_room_charge_method_rejects_a_receivable_account(self):
        """Odoo strips receivable accounts off invoice lines, so a receivable
        clearing account would never reach the guest's check-out invoice."""
        receivable = self.env['account.account'].create({
            'code': 'TEST101951',
            'name': 'Test Receivable',
            'account_type': 'asset_receivable',
            'reconcile': True,
        })
        with self.assertRaises(ValidationError):
            self.env['pos.payment.method'].create({
                'name': 'Bad Charge to Room',
                'is_hotel_folio': True,
                'receivable_account_id': receivable.id,
            })

    def test_room_charge_method_requires_a_clearing_account(self):
        with self.assertRaises(ValidationError):
            self.env['pos.payment.method'].create({
                'name': 'Unconfigured Charge to Room',
                'is_hotel_folio': True,
            })

    def test_room_charge_method_accepts_a_current_asset(self):
        method = self.env['pos.payment.method'].create({
            'name': 'Good Charge to Room',
            'is_hotel_folio': True,
            'receivable_account_id': self.clearing_account.id,
        })
        self.assertTrue(method.is_hotel_folio)
