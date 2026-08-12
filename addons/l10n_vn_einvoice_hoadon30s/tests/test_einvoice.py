# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.l10n_vn_einvoice_hoadon30s.models.hoadon30s_api import (
    Hoadon30sApi, fmt_number,
)

CREATE_RESPONSE = {
    'status': 200,
    'message': 'Tạo mới hóa đơn thành công',
    'id_attr': 'TESTID00000000000000000000000001',
    'lookup_code': 'TESTLOOKUP001',
    'autoSign': 200,
    'sendCQT': 200,
}
SYNC_RESPONSE = {
    'status': 200,
    'message': 'success',
    'statusInv': 3,
    'data': {
        'no': 123,
        'code_cqt': 'CQT-TEST-CODE',
        'serial': '1C26TPA',
        'date_release': '2026-08-12',
    },
}


@tagged('post_install', '-at_install')
class TestEinvoice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        icp = cls.env['ir.config_parameter'].sudo()
        icp.set_param('hoadon30s.client_id', 'test-client')
        icp.set_param('hoadon30s.client_secret', 'test-secret')
        icp.set_param('hoadon30s.serial_vat', '1C26TPA')
        icp.set_param('hoadon30s.serial_mtt', '1C26MEE')
        cls.partner = cls.env['res.partner'].create({
            'name': 'Công ty TNHH Kiểm Thử',
            'vat': '0101234567',
            'street': '1 Trang Tien',
            'city': 'Ha Noi',
            'is_company': True,
        })
        cls.tax_10 = cls.env['account.tax'].create({
            'name': 'VAT 10% (test)',
            'amount': 10,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Room Night (test)',
            'default_code': 'ROOMTEST',
            'type': 'service',
        })
        cls.invoice = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': cls.partner.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [
                Command.create({
                    'product_id': cls.product.id,
                    'name': 'Bungalow night',
                    'quantity': 2,
                    'price_unit': 1500000,
                    'tax_ids': [Command.set(cls.tax_10.ids)],
                }),
                Command.create({
                    'product_id': cls.product.id,
                    'name': 'Untaxed service',
                    'quantity': 1,
                    'price_unit': 500000,
                    'tax_ids': [Command.clear()],
                }),
            ],
        })
        cls.invoice.action_post()

    def test_fmt_number(self):
        self.assertEqual(fmt_number(1500000.0), '1500000')
        self.assertEqual(fmt_number(150.50), '150.5')
        self.assertEqual(fmt_number(0.0), '0')

    def test_map_vat_rate(self):
        api = self.env['hoadon30s.api']
        self.assertEqual(api._map_vat_rate(10, True), (10, None))
        self.assertEqual(api._map_vat_rate(8.0, True), (8, None))
        self.assertEqual(api._map_vat_rate(0, True), (0, None))
        self.assertEqual(api._map_vat_rate(0, False), (-1, None))
        self.assertEqual(api._map_vat_rate(6, True), (-3, 6))

    def test_move_payload(self):
        payload = self.invoice._prepare_einvoice_payload()
        self.assertEqual(payload['init_invoice'], 'HDGTGT')
        self.assertEqual(payload['serial'], '1C26TPA')
        self.assertEqual(payload['vat_rate'], -1)
        self.assertEqual(payload['cus_taxCode'], '0101234567')
        self.assertEqual(payload['cus_name'], self.partner.name)
        self.assertEqual(payload['total'], self.invoice.amount_untaxed)
        self.assertEqual(payload['vat_amount'], self.invoice.amount_tax)
        self.assertEqual(payload['amount'], self.invoice.amount_total)
        self.assertEqual(len(payload['detail']), 2)
        taxed, untaxed = payload['detail']
        self.assertEqual(taxed['vatRate'], 10)
        self.assertEqual(taxed['quantity'], 2)
        self.assertEqual(untaxed['vatRate'], -1)

    def test_issue_einvoice(self):
        responses = [CREATE_RESPONSE, SYNC_RESPONSE]

        def fake_call(model, endpoint, payload):
            return responses.pop(0)

        with patch.object(Hoadon30sApi, '_call', fake_call):
            self.invoice.action_issue_einvoice()
        self.assertEqual(self.invoice.einvoice_id_attr,
                         CREATE_RESPONSE['id_attr'])
        self.assertEqual(self.invoice.einvoice_lookup_code, 'TESTLOOKUP001')
        self.assertEqual(self.invoice.einvoice_status, 'coded')
        self.assertEqual(self.invoice.einvoice_no, '123')
        self.assertEqual(self.invoice.einvoice_code_cqt, 'CQT-TEST-CODE')

    def test_fetch_creates_partner_and_registry(self):
        fetched_invoice = {
            'id_attr': 'FETCHED000000000000000000000001',
            'serial': '1C26TPA',
            'no': 55,
            'date_export': '2026-08-10',
            'lookup_code': 'FETCHLOOKUP01',
            'code_cqt': 'CQT-55',
            'status': 3,
            'currency': 'VND',
            'total': 1000000,
            'vat_amount': 100000,
            'amount': 1100000,
            'cus_taxCode': '0109876543',
            'cus_name': 'Công ty CP Khách Mới',
            'cus_address': '2 Ly Thuong Kiet, Ha Noi',
            'cus_phone': '0912345678',
        }

        def fake_call(model, endpoint, payload):
            if payload.get('init_invoice') == 'HDGTGT':
                return {'status': 200, 'message': 'success',
                        'totalInvoice': 1, 'data': [fetched_invoice]}
            return {'status': 200, 'message': 'success',
                    'totalInvoice': 0, 'data': []}

        Registry = self.env['hoadon30s.einvoice']
        with patch.object(Hoadon30sApi, '_call', fake_call):
            summary = Registry.fetch_invoices(
                fields.Date.to_date('2026-08-01'),
                fields.Date.to_date('2026-08-12'))
        self.assertEqual(summary['found'], 1)
        self.assertEqual(summary['created'], 1)
        self.assertEqual(summary['partners_created'], 1)

        record = Registry.search(
            [('id_attr', '=', fetched_invoice['id_attr'])])
        self.assertEqual(len(record), 1)
        self.assertEqual(record.status, 'coded')
        self.assertEqual(record.no, '55')
        partner = record.partner_id
        self.assertEqual(partner.vat, '0109876543')
        self.assertEqual(partner.name, 'Công ty CP Khách Mới')
        self.assertTrue(partner.is_company)
        self.assertEqual(partner.customer_rank, 1)

        # Second fetch: idempotent — same row updated, no second partner.
        with patch.object(Hoadon30sApi, '_call', fake_call):
            summary = Registry.fetch_invoices(
                fields.Date.to_date('2026-08-01'),
                fields.Date.to_date('2026-08-12'))
        self.assertEqual(summary['created'], 0)
        self.assertEqual(summary['partners_created'], 0)
        self.assertEqual(Registry.search_count(
            [('id_attr', '=', fetched_invoice['id_attr'])]), 1)

    def test_fetch_matches_partner_by_vat(self):
        existing = self.env['res.partner'].create({
            'name': 'Different Display Name',
            'vat': '0105555555',
        })
        inv = {
            'id_attr': 'FETCHED000000000000000000000002',
            'status': 1,
            'date_export': '2026-08-11',
            'cus_taxCode': '0105555555',
            'cus_name': 'Công ty với tên khác',
        }

        def fake_call(model, endpoint, payload):
            if payload.get('init_invoice') == 'HDGTGT':
                return {'status': 200, 'message': 'success',
                        'totalInvoice': 1, 'data': [inv]}
            return {'status': 200, 'message': 'success',
                    'totalInvoice': 0, 'data': []}

        with patch.object(Hoadon30sApi, '_call', fake_call):
            summary = self.env['hoadon30s.einvoice'].fetch_invoices(
                fields.Date.to_date('2026-08-01'),
                fields.Date.to_date('2026-08-12'))
        self.assertEqual(summary['partners_created'], 0)
        record = self.env['hoadon30s.einvoice'].search(
            [('id_attr', '=', inv['id_attr'])])
        self.assertEqual(record.partner_id, existing)
