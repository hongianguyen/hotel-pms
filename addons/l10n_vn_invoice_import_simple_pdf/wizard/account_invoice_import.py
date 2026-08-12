# -*- coding: utf-8 -*-
# Copyright 2026 Lak Tented Camp
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
import re
from datetime import date

from odoo import api, models

logger = logging.getLogger(__name__)

# Label wording below is mandated by Decree 123/2020/ND-CP + Circular 78/2021/TT-BTC,
# so it is stable across VN e-invoice providers. The English parentheticals
# ("(Seller)", "(Tax code)", ...) are provider-specific, so every pattern here
# tolerates any non-colon filler between the Vietnamese label and its colon.
_SELLER_LABEL = "Đơn vị bán hàng"
# Where the seller block ends and the buyer block begins. Scoping the parse to the
# seller block is what keeps us off the buyer's tax code and off the e-invoice
# provider's tax code in the footer (a plain "first Mã số thuế wins" rule would be
# correct on most layouts but is not robust).
_BUYER_LABELS = ("Tên khách hàng", "Tên đơn vị", "Người mua hàng", "Họ tên người mua")

RE_SELLER_NAME = re.compile(rf"{_SELLER_LABEL}[^:\n]*:[ \t]*(.+)")
RE_TAX_CODE = re.compile(r"Mã số thuế[^:\n]*:[ \t]*([0-9]{10}(?:-[0-9]{3})?)")
RE_ADDRESS = re.compile(r"Địa chỉ[^:\n]*:[ \t]*(.+)")
RE_PHONE = re.compile(r"Điện thoại[^:\n]*:[ \t]*(.+)")
RE_EMAIL = re.compile(r"Email[^:\n]*?:?[ \t]*([^\s@]+@[^\s@]+\.[^\s@]+)")

# "Ký hiệu (Serial):\n1C26MTP" — value usually sits on the next line.
RE_SERIAL = re.compile(r"Ký hiệu[^:\n]*:[ \t]*\n?[ \t]*([A-Z0-9/]+)")
RE_NUMBER = re.compile(r"Số[ \t]*\(No\.?\)[^:\n]*:[ \t]*\n?[ \t]*([0-9]+)")
RE_NUMBER_ALT = re.compile(r"Số hóa đơn[^:\n]*:[ \t]*\n?[ \t]*([0-9]+)")
# "Ngày (date) 22tháng (month) 07năm (year) 2026" — note there is no space between
# the day digits and the next label, so the separators must be non-greedy filler.
RE_DATE_LONG = re.compile(
    r"Ngày[^0-9]{0,20}([0-9]{1,2})[^0-9]{0,20}tháng[^0-9]{0,20}([0-9]{1,2})"
    r"[^0-9]{0,20}năm[^0-9]{0,20}([0-9]{4})"
)
# Digital-signature stamp, used as a fallback: "Ký ngày 22/07/2026"
RE_DATE_SIGNED = re.compile(r"Ký ngày[ \t]*([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})")
RE_VAT_RATE = re.compile(
    r"Thuế suất GTGT[^:\n]*:[ \t]*([0-9]+(?:[.,][0-9]+)?)[ \t]*%"
)

# Extraction rules seeded on a newly created vendor. The amounts are delegated to
# the OCA engine. A "date" rule is mandatory (_simple_pdf_partner_config refuses a
# partner without one) so we seed it off the digital-signature stamp; the invoice
# date and number are then recomputed in _vn_set_number_and_date from the
# Circular-78 header, which is more portable across providers.
VN_FIELD_RULES = [
    ("amount_untaxed", "Cộng tiền hàng"),
    ("amount_tax", "Tiền thuế GTGT"),
    ("amount_total", "Tổng cộng tiền thanh toán"),
    ("date", "Ký ngày"),
]

AUTOCREATE_PARAM = "l10n_vn_invoice_import.autocreate_vendor"


class AccountInvoiceImport(models.TransientModel):
    _inherit = "account.invoice.import"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @api.model
    def _vn_raw_text(self, file_data, test_info=None):
        """Return the flat text of the PDF, using the OCA extraction chain."""
        if test_info is None:
            test_info = {"test_mode": False}
        self._simple_pdf_update_test_info(test_info)
        return self.simple_pdf_text_extraction(file_data, test_info)["all"]

    @api.model
    def _vn_is_einvoice(self, text):
        return "Mã số thuế" in text and (
            "Ký hiệu" in text or "HÓA ĐƠN" in text.upper()
        )

    @api.model
    def _vn_seller_block(self, text):
        start = text.find(_SELLER_LABEL)
        if start < 0:
            return ""
        rest = text[start:]
        ends = [pos for pos in (rest.find(lbl) for lbl in _BUYER_LABELS) if pos > 0]
        return rest[: min(ends)] if ends else rest

    @api.model
    def _vn_parse_seller(self, text):
        """Extract the seller identity from a VN VAT e-invoice. {} if not one."""
        if not self._vn_is_einvoice(text):
            return {}
        block = self._vn_seller_block(text)
        if not block:
            return {}
        name_m = RE_SELLER_NAME.search(block)
        vat_m = RE_TAX_CODE.search(block)
        if not name_m or not vat_m:
            return {}
        vals = {"name": name_m.group(1).strip(), "vat": vat_m.group(1).strip()}
        for key, rx in (
            ("street", RE_ADDRESS),
            ("phone", RE_PHONE),
            ("email", RE_EMAIL),
        ):
            found = rx.search(block)
            if found:
                vals[key] = found.group(1).strip()
        return vals

    @api.model
    def _vn_invoice_number(self, text):
        """Vietnamese invoices are identified by serial + number ("Ký hiệu" +
        "Số"). The number alone restarts every year, so on its own it would
        trip the partner-scoped duplicate check in account_invoice_import."""
        num_m = RE_NUMBER.search(text) or RE_NUMBER_ALT.search(text)
        if not num_m:
            return False
        number = num_m.group(1).strip()
        serial_m = RE_SERIAL.search(text)
        return f"{serial_m.group(1).strip()}-{number}" if serial_m else number

    @api.model
    def _vn_invoice_date(self, text):
        found = RE_DATE_LONG.search(text) or RE_DATE_SIGNED.search(text)
        if not found:
            return False
        day, month, year = (int(g) for g in found.groups())
        try:
            return date(year, month, day)
        except ValueError:
            logger.warning("VN e-invoice: invalid date %s-%s-%s", year, month, day)
            return False

    @api.model
    def _vn_vat_rate(self, text):
        """The VAT rate printed on the invoice, e.g. 8.0 for 'VAT rate: 8%'."""
        found = RE_VAT_RATE.search(text)
        if not found:
            return None
        try:
            return float(found.group(1).replace(",", "."))
        except ValueError:
            return None

    @api.model
    def _vn_find_purchase_tax(self, rate):
        """Purchase tax matching the invoice's VAT rate.

        The UNECE code is not cosmetic: account_invoice_import calls
        res.company._cannot_refund_vat(), which returns True when the company
        owns no purchase tax carrying unece_type_code == 'VAT'. In that case the
        importer deliberately zeroes amount_tax and posts the gross figure as
        untaxed, so a VN bill would book 27.702.000 untaxed instead of
        25.650.000 + 2.052.000 VAT.
        """
        if rate is None:
            return self.env["account.tax"]
        return self.env["account.tax"].search(
            [
                ("company_id", "=", self.env.company.id),
                ("type_tax_use", "=", "purchase"),
                ("amount_type", "=", "percent"),
                ("amount", ">=", rate - 0.001),
                ("amount", "<=", rate + 0.001),
                ("unece_type_code", "=", "VAT"),
            ],
            limit=1,
        )

    # ------------------------------------------------------------------
    # vendor creation
    # ------------------------------------------------------------------
    @api.model
    def _vn_prepare_vendor_vals(self, seller):
        vnd = (
            self.env["res.currency"]
            .with_context(active_test=False)
            .search([("name", "=", "VND")], limit=1)
        )
        if vnd and not vnd.active:
            vnd.active = True
        country = self.env.ref("base.vn", raise_if_not_found=False)
        vals = dict(
            seller,
            is_company=True,
            supplier_rank=1,
            # VN VAT amounts carry no decimals; with a 2-decimal currency the OCA
            # amount pattern demands a ",00" tail that VN invoices never print,
            # and every amount silently fails to extract.
            simple_pdf_currency_id=vnd.id if vnd else False,
            simple_pdf_decimal_separator="comma",
            simple_pdf_thousand_separator="dot",
            simple_pdf_date_format="dd-mm-y4",
            simple_pdf_date_separator="slash",
            simple_pdf_pages="all",
        )
        if country:
            vals["country_id"] = country.id
        return vals

    @api.model
    def _vn_create_vendor(self, seller, vat_rate=None):
        company_vat = self.env.company.partner_id.vat or ""
        if seller["vat"] and seller["vat"] in company_vat.replace("VN", ""):
            # the buyer is us — never create a vendor for our own tax code
            return self.env["res.partner"]
        vals = self._vn_prepare_vendor_vals(seller)
        tax = self._vn_find_purchase_tax(vat_rate)
        if tax:
            vals["invoice_import_tax_ids"] = [(6, 0, tax.ids)]
        partner = self.env["res.partner"].create(vals)
        rule_model = self.env["account.invoice.import.simple.pdf.fields"]
        for seq, (name, start) in enumerate(VN_FIELD_RULES, start=1):
            rule_model.create(
                {
                    "partner_id": partner.id,
                    "sequence": seq * 10,
                    "name": name,
                    "start": start,
                    "extract_rule": "first",
                }
            )
        logger.info(
            "VN e-invoice: created vendor %s (MST %s) id=%s",
            partner.name,
            partner.vat,
            partner.id,
        )
        return partner

    @api.model
    def _vn_autocreate_enabled(self):
        param = (
            self.env["ir.config_parameter"].sudo().get_param(AUTOCREATE_PARAM, "True")
        )
        return str(param).strip().lower() not in ("false", "0", "")

    # ------------------------------------------------------------------
    # entry point
    # ------------------------------------------------------------------
    @api.model
    def simple_pdf_parse_invoice(self, file_data, test_info=None):
        parsed_inv = super().simple_pdf_parse_invoice(file_data, test_info)
        if not parsed_inv.get("partner"):
            if not self._vn_autocreate_enabled():
                return parsed_inv
            text = self._vn_raw_text(file_data, test_info)
            seller = self._vn_parse_seller(text)
            if not seller:
                return parsed_inv
            existing = self.env["res.partner"].search(
                [("vat", "in", (seller["vat"], f"VN{seller['vat']}"))], limit=1
            )
            if existing:
                # Present but unmatchable by the OCA keyword search (e.g. the VAT
                # is stored with a country prefix). Don't duplicate the record.
                logger.info(
                    "VN e-invoice: MST %s already on partner %s, not creating",
                    seller["vat"],
                    existing.id,
                )
                return parsed_inv
            if not self._vn_create_vendor(seller, self._vn_vat_rate(text)):
                return parsed_inv
            # Re-run now that the vendor and its extraction rules exist.
            parsed_inv = super().simple_pdf_parse_invoice(file_data, test_info)
            if not parsed_inv.get("partner"):
                return parsed_inv

        return self._vn_set_number_and_date(parsed_inv, file_data, test_info)

    @api.model
    def _vn_set_number_and_date(self, parsed_inv, file_data, test_info=None):
        text = self._vn_raw_text(file_data, test_info)
        if not self._vn_is_einvoice(text):
            return parsed_inv
        number = self._vn_invoice_number(text)
        if number:
            parsed_inv["invoice_number"] = number
        inv_date = self._vn_invoice_date(text)
        if inv_date:
            parsed_inv["date"] = inv_date
        rate = self._vn_vat_rate(text)
        if rate is not None and not self._vn_find_purchase_tax(rate):
            parsed_inv.setdefault("chatter_msg", []).append(
                "Vietnamese VAT e-invoice at %g%% VAT, but this company has no "
                "purchase tax at that rate carrying the UNECE code 'VAT'. The "
                "importer will post the gross amount as untaxed and zero the VAT. "
                "Create a %g%% purchase tax with UNECE Tax Type 'VAT' to fix this."
                % (rate, rate)
            )
        return parsed_inv
