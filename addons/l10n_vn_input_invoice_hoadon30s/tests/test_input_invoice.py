# -*- coding: utf-8 -*-
import base64

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.l10n_vn_input_invoice_hoadon30s.models import gdt_xml
from odoo.addons.l10n_vn_input_invoice_hoadon30s.models.hoadon30s_sync_api \
    import Hoadon30sSyncApi

# A TT78 invoice as the GDT emits it: two taxed lines at different rates and
# one line not subject to VAT (KCT).
INVOICE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<HDon>
  <DLHDon Id="INV1">
    <TTChung>
      <PBan>2.0.0</PBan>
      <THDon>Hóa đơn giá trị gia tăng</THDon>
      <KHMSHDon>1</KHMSHDon>
      <KHHDon>C26TAA</KHHDon>
      <SHDon>1234</SHDon>
      <NLap>2026-08-05</NLap>
      <DVTTe>VND</DVTTe>
      <TGia>1</TGia>
      <HTTToan>CK</HTTToan>
    </TTChung>
    <NDHDon>
      <NBan>
        <Ten>Công ty TNHH Vật Tư Miền Trung</Ten>
        <MST>0400123456</MST>
        <DChi>15 Nguyen Van Linh, Da Nang</DChi>
        <SDThoai>02363888888</SDThoai>
        <DCTDTu>ketoan@vattumt.vn</DCTDTu>
      </NBan>
      <NMua>
        <Ten>Lak Tented Camp</Ten>
        <MST>6001234567</MST>
        <DChi>Lien Son, Lak, Dak Lak</DChi>
      </NMua>
      <DSHHDVu>
        <HHDVu>
          <TChat>1</TChat>
          <STT>1</STT>
          <THHDVu>Ga trải giường cotton</THHDVu>
          <DVTinh>Cái</DVTinh>
          <SLuong>10</SLuong>
          <DGia>250000</DGia>
          <ThTien>2500000</ThTien>
          <TSuat>10%</TSuat>
          <TThue>250000</TThue>
        </HHDVu>
        <HHDVu>
          <TChat>1</TChat>
          <STT>2</STT>
          <THHDVu>Dịch vụ vận chuyển</THHDVu>
          <DVTinh>Lần</DVTinh>
          <SLuong>1</SLuong>
          <DGia>500000</DGia>
          <ThTien>500000</ThTien>
          <TSuat>8%</TSuat>
          <TThue>40000</TThue>
        </HHDVu>
        <HHDVu>
          <TChat>1</TChat>
          <STT>3</STT>
          <THHDVu>Phí không chịu thuế</THHDVu>
          <DVTinh>Lần</DVTinh>
          <SLuong>1</SLuong>
          <DGia>100000</DGia>
          <ThTien>100000</ThTien>
          <TSuat>KCT</TSuat>
        </HHDVu>
      </DSHHDVu>
      <TToan>
        <TgTCThue>3100000</TgTCThue>
        <TgTThue>290000</TgTThue>
        <TgTTTBSo>3390000</TgTTTBSo>
      </TToan>
    </NDHDon>
  </DLHDon>
  <MCCQT>M1-26-ABCDE-12345678901234567890123456</MCCQT>
</HDon>
"""

INVOICE_XML_B64 = base64.b64encode(INVOICE_XML.encode()).decode()

ERROR_ROW = {
    'category': 1,
    'serial': 'C26TBB',
    'invoiceNumber': 77,
    'dateExport': '2026-08-06',
    'sellerTaxCode': '0400999888',
    'total': 1000000,
    'amount_vat': 100000,
    'amount_total': 1100000,
    'message': 'Không lấy được XML từ cơ quan thuế',
}


def make_page(invoices=None, errors=None, state=None, total=0):
    return {
        'status': 200,
        'message': 'success',
        'data': {
            'invoices': invoices or [],
            'invoicesError': errors or [],
            'state': state,
            'total': total,
        },
    }


@tagged('post_install', '-at_install')
class TestInputInvoiceParser(TransactionCase):
    """The XML parser is pure — test it without touching the ORM."""

    def test_parses_header(self):
        parsed = gdt_xml.parse_invoice_xml(INVOICE_XML_B64)
        self.assertEqual(parsed['form_no'], '1')
        self.assertEqual(parsed['serial'], 'C26TAA')
        self.assertEqual(parsed['number'], '1234')
        self.assertEqual(parsed['date'], '2026-08-05')
        self.assertEqual(parsed['currency'], 'VND')
        self.assertEqual(parsed['code_cqt'],
                         'M1-26-ABCDE-12345678901234567890123456')

    def test_parses_seller_not_buyer(self):
        parsed = gdt_xml.parse_invoice_xml(INVOICE_XML_B64)
        self.assertEqual(parsed['seller']['tax_code'], '0400123456')
        self.assertEqual(parsed['seller']['name'],
                         'Công ty TNHH Vật Tư Miền Trung')
        # The buyer is us — it must not be confused with the seller.
        self.assertEqual(parsed['buyer']['tax_code'], '6001234567')

    def test_parses_lines_and_rates(self):
        parsed = gdt_xml.parse_invoice_xml(INVOICE_XML_B64)
        self.assertEqual(len(parsed['lines']), 3)
        first, second, third = parsed['lines']
        self.assertEqual(first['name'], 'Ga trải giường cotton')
        self.assertEqual(first['quantity'], 10.0)
        self.assertEqual(first['price_unit'], 250000.0)
        self.assertEqual(first['tax_rate'], 10.0)
        self.assertTrue(first['taxable'])
        self.assertEqual(second['tax_rate'], 8.0)
        # KCT — not subject to VAT.
        self.assertFalse(third['taxable'])
        self.assertEqual(third['tax_rate'], 0.0)

    def test_parses_totals(self):
        parsed = gdt_xml.parse_invoice_xml(INVOICE_XML_B64)
        self.assertEqual(parsed['total_untaxed'], 3100000.0)
        self.assertEqual(parsed['total_tax'], 290000.0)
        self.assertEqual(parsed['total_amount'], 3390000.0)

    def test_parses_namespaced_and_enveloped_xml(self):
        """A TDiep envelope with namespaces must parse the same way."""
        wrapped = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<TDiep xmlns="http://kekhaithue.gdt.gov.vn/TKhaiThue">'
            '<DLieu>' + INVOICE_XML.split('?>', 1)[1] + '</DLieu></TDiep>'
        )
        parsed = gdt_xml.parse_invoice_xml(
            base64.b64encode(wrapped.encode()).decode())
        self.assertEqual(parsed['number'], '1234')
        self.assertEqual(parsed['seller']['tax_code'], '0400123456')

    def test_tax_rate_markers(self):
        self.assertEqual(gdt_xml.parse_tax_rate('10%'), (10.0, True))
        self.assertEqual(gdt_xml.parse_tax_rate('0%'), (0.0, True))
        self.assertEqual(gdt_xml.parse_tax_rate('KCT'), (0.0, False))
        self.assertEqual(gdt_xml.parse_tax_rate('KKKNT'), (0.0, False))
        self.assertEqual(gdt_xml.parse_tax_rate('\\'), (0.0, False))
        self.assertEqual(gdt_xml.parse_tax_rate(''), (0.0, False))

    def test_number_formats(self):
        self.assertEqual(gdt_xml._to_float('1234567'), 1234567.0)
        self.assertEqual(gdt_xml._to_float('1,234,567'), 1234567.0)
        self.assertEqual(gdt_xml._to_float('1234.56'), 1234.56)
        self.assertEqual(gdt_xml._to_float('1.234,56'), 1234.56)
        self.assertEqual(gdt_xml._to_float('1,5'), 1.5)
        self.assertEqual(gdt_xml._to_float(''), 0.0)

    def test_rejects_bad_payloads(self):
        with self.assertRaises(ValueError):
            gdt_xml.parse_invoice_xml(
                base64.b64encode(b'<HDon><unclosed>').decode())


@tagged('post_install', '-at_install')
class TestInputInvoiceDownload(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        icp = cls.env['ir.config_parameter'].sudo()
        icp.set_param('hoadon30s.sync.client_id', 'test-client')
        icp.set_param('hoadon30s.sync.client_secret', 'test-secret')
        icp.set_param('hoadon30s.sync.gdt_username', '6001234567')
        cls.Registry = cls.env['hoadon30s.purchase.einvoice']

    def _fetch(self, pages, **kwargs):
        """Run a download against a canned sequence of provider pages."""
        queue = list(pages)

        def fake_download(model, date_from, date_to, mtt=False, **kw):
            # Only the regular endpoint returns anything in these tests.
            if mtt:
                return
            for page in queue:
                yield page['data']

        with self.patch_download(fake_download):
            return self.Registry.fetch_purchase_invoices(
                fields.Date.to_date('2026-08-01'),
                fields.Date.to_date('2026-08-31'), **kwargs)

    def patch_download(self, func):
        from unittest.mock import patch
        return patch.object(Hoadon30sSyncApi, 'download_purchase', func)

    def test_download_creates_record_and_vendor(self):
        summary = self._fetch([make_page(
            invoices=[{'xml': INVOICE_XML_B64}], total=1)])
        self.assertEqual(summary['found'], 1)
        self.assertEqual(summary['created'], 1)
        self.assertEqual(summary['partners_created'], 1)

        record = self.Registry.search([('number', '=', '1234')])
        self.assertEqual(len(record), 1)
        self.assertEqual(record.state, 'downloaded')
        self.assertEqual(record.seller_tax_code, '0400123456')
        self.assertEqual(record.amount_total, 3390000.0)
        self.assertEqual(record.partner_id.vat, '0400123456')
        self.assertTrue(record.partner_id.supplier_rank)
        self.assertTrue(record.xml_file)

    def test_download_is_idempotent(self):
        """Re-downloading a period must never duplicate a bill-able row."""
        page = make_page(invoices=[{'xml': INVOICE_XML_B64}], total=1)
        self._fetch([page])
        summary = self._fetch([page])
        self.assertEqual(summary['created'], 0)
        self.assertEqual(summary['updated'], 1)
        self.assertEqual(summary['partners_created'], 0)
        self.assertEqual(self.Registry.search_count(
            [('number', '=', '1234')]), 1)

    def test_error_rows_are_kept(self):
        summary = self._fetch([make_page(errors=[ERROR_ROW], total=1)])
        self.assertEqual(summary['no_xml'], 1)
        self.assertEqual(summary['found'], 1)
        record = self.Registry.search([('number', '=', '77')])
        self.assertEqual(len(record), 1)
        self.assertEqual(record.state, 'no_xml')
        self.assertEqual(record.amount_total, 1100000.0)
        self.assertIn('XML', record.error_message)

    def test_unparseable_xml_is_kept_as_error(self):
        bad = base64.b64encode(b'<HDon><nope>').decode()
        summary = self._fetch([make_page(
            invoices=[{'xml': bad, 'sellerTaxCode': '0400777666',
                       'invoiceNumber': 9, 'serial': 'C26TCC',
                       'category': 1}], total=1)])
        self.assertEqual(summary['parse_errors'], 1)
        record = self.Registry.search([('number', '=', '9')])
        self.assertEqual(record.state, 'parse_error')

    def test_pagination_follows_cursor(self):
        second_xml = INVOICE_XML.replace(
            '<SHDon>1234</SHDon>', '<SHDon>1235</SHDon>')
        pages = [
            make_page(invoices=[{'xml': INVOICE_XML_B64}],
                      state='CURSOR', total=2),
            make_page(invoices=[{
                'xml': base64.b64encode(second_xml.encode()).decode()}],
                total=2),
        ]
        summary = self._fetch(pages)
        self.assertEqual(summary['created'], 2)
        self.assertEqual(summary['total_reported'], 2)

    def test_range_longer_than_a_month_is_refused(self):
        with self.assertRaises(UserError):
            list(self.env['hoadon30s.sync.api'].download_purchase(
                fields.Date.to_date('2026-01-01'),
                fields.Date.to_date('2026-06-30')))


@tagged('post_install', '-at_install')
class TestInputInvoiceBilling(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        icp = cls.env['ir.config_parameter'].sudo()
        icp.set_param('hoadon30s.sync.client_id', 'test-client')
        icp.set_param('hoadon30s.sync.client_secret', 'test-secret')
        icp.set_param('hoadon30s.sync.gdt_username', '6001234567')
        cls.Registry = cls.env['hoadon30s.purchase.einvoice']
        # The fixture invoice is in VND, so the bill needs that currency.
        cls.vnd = cls.env['res.currency'].with_context(
            active_test=False).search([('name', '=', 'VND')], limit=1)
        cls.vnd.active = True
        cls.tax_10 = cls.env['account.tax'].create({
            'name': 'Thuế GTGT 10% (mua vào)',
            'amount': 10,
            'amount_type': 'percent',
            'type_tax_use': 'purchase',
        })
        cls.tax_8 = cls.env['account.tax'].create({
            'name': 'Thuế GTGT 8% (mua vào)',
            'amount': 8,
            'amount_type': 'percent',
            'type_tax_use': 'purchase',
        })
        if 'unece_code' in cls.env['account.tax']._fields:
            (cls.tax_10 | cls.tax_8).write({'unece_code': 'VAT'})

    def _make_record(self):
        from unittest.mock import patch

        def fake_download(model, date_from, date_to, mtt=False, **kw):
            if not mtt:
                yield make_page(invoices=[{'xml': INVOICE_XML_B64}],
                                total=1)['data']

        with patch.object(Hoadon30sSyncApi, 'download_purchase',
                          fake_download):
            self.Registry.fetch_purchase_invoices(
                fields.Date.to_date('2026-08-01'),
                fields.Date.to_date('2026-08-31'))
        return self.Registry.search([('number', '=', '1234')])

    def test_creates_draft_bill_with_matching_totals(self):
        record = self._make_record()
        record.action_create_bill()
        bill = record.move_id
        self.assertTrue(bill)
        # Never auto-posted: an accountant reviews the accounts first.
        self.assertEqual(bill.state, 'draft')
        self.assertEqual(bill.move_type, 'in_invoice')
        self.assertEqual(bill.partner_id, record.partner_id)
        self.assertEqual(bill.invoice_date, fields.Date.to_date('2026-08-05'))
        self.assertEqual(len(bill.invoice_line_ids), 3)
        self.assertEqual(record.state, 'billed')

        taxed_10, taxed_8, untaxed = bill.invoice_line_ids
        self.assertEqual(taxed_10.tax_ids, self.tax_10)
        self.assertEqual(taxed_8.tax_ids, self.tax_8)
        self.assertFalse(untaxed.tax_ids)
        self.assertEqual(bill.amount_untaxed, 3100000.0)
        self.assertEqual(bill.amount_tax, 290000.0)
        self.assertEqual(bill.amount_total, 3390000.0)
        # Totals agree, so no mismatch warning was recorded.
        self.assertFalse(record.error_message)

    def test_total_mismatch_is_flagged_not_hidden(self):
        """A missing purchase tax must be surfaced, never posted silently."""
        self.tax_8.unlink()
        record = self._make_record()
        record.action_create_bill()
        self.assertTrue(record.error_message)
        self.assertIn('VAT', record.error_message)
        # The bill still exists, in draft, for the accountant to fix.
        self.assertEqual(record.move_id.state, 'draft')

    def test_second_bill_is_refused(self):
        record = self._make_record()
        record.action_create_bill()
        with self.assertRaises(UserError):
            record.action_create_bill()

    def test_no_xml_row_cannot_be_billed(self):
        record = self.Registry.create([{
            'seller_tax_code': '0400999888',
            'number': '77',
            'serial': 'C26TBB',
            'form_no': '1',
            'state': 'no_xml',
            'error_message': 'no xml',
        }])
        with self.assertRaises(UserError):
            record.action_create_bill()
