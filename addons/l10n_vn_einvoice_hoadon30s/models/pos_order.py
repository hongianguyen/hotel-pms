# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .hoadon30s_api import (
    EINVOICE_STATUSES, STATUS_BY_CODE, fmt_number,
)

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    einvoice_id_attr = fields.Char(
        'E-Invoice ID', readonly=True, copy=False, index=True)
    einvoice_lookup_code = fields.Char(
        'E-Invoice Lookup Code', readonly=True, copy=False)
    einvoice_serial = fields.Char('E-Invoice Serial', readonly=True, copy=False)
    einvoice_no = fields.Char('E-Invoice No.', readonly=True, copy=False)
    einvoice_code_cqt = fields.Char(
        'Tax Authority Code', readonly=True, copy=False)
    einvoice_status = fields.Selection(
        EINVOICE_STATUSES, string='E-Invoice Status', readonly=True, copy=False)
    einvoice_error = fields.Text('E-Invoice Error', readonly=True, copy=False)

    def _process_saved_order(self, draft):
        res = super()._process_saved_order(draft)
        if not draft and self.state in ('paid', 'done', 'invoiced'):
            api_model = self.env['hoadon30s.api']
            auto = api_model._get_param('pos_auto_issue', 'True') \
                not in ('False', '0', '')
            if auto and api_model._is_configured():
                self._issue_einvoice_safe()
        return res

    def _issue_einvoice_safe(self):
        """Issue e-invoices without ever blocking the sale on an API error."""
        for order in self:
            if order.einvoice_id_attr:
                continue
            try:
                order.action_issue_einvoice()
            except Exception as exc:
                _logger.warning(
                    'Cash-register e-invoice failed for POS order %s: %s',
                    order.name, exc)
                order.write({
                    'einvoice_status': 'error',
                    'einvoice_error': str(exc),
                })

    def action_issue_einvoice(self):
        api_model = self.env['hoadon30s.api']
        for order in self:
            if order.einvoice_id_attr:
                raise UserError(_(
                    '%s: an e-invoice was already issued (lookup code %s).',
                    order.name, order.einvoice_lookup_code))
            if order.state not in ('paid', 'done', 'invoiced'):
                raise UserError(_(
                    '%s: the order must be paid before issuing the '
                    'e-invoice.', order.name))
            if order.currency_id.compare_amounts(order.amount_total, 0) <= 0:
                raise UserError(_(
                    '%s: refunds and zero orders need a manual adjustment '
                    'invoice on hoadon30s.vn.', order.name))

            payload = order._prepare_einvoice_payload()
            data = api_model._call_checked(
                'api/invoice/create-cash-register', payload)
            status = 'draft'
            if data.get('autoSign') == 200:
                status = 'signed'
            if data.get('sendCQT') == 200:
                status = 'sent'
            order.write({
                'einvoice_id_attr': data.get('id_attr'),
                'einvoice_lookup_code': data.get('lookup_code'),
                'einvoice_serial': payload.get('serial'),
                'einvoice_status': status,
                'einvoice_error': False,
            })
        return True

    def _prepare_einvoice_payload(self):
        """Build the multi-tax-line HDGTGTMTT (cash register) payload."""
        self.ensure_one()
        api_model = self.env['hoadon30s.api']

        currency = self.currency_id.name
        if currency not in ('VND', 'USD'):
            raise UserError(_(
                '%s: the e-invoice service only accepts VND or USD '
                'orders (this one is %s).', self.name, currency))

        detail = []
        lines = self.lines.filtered(lambda l: l.qty > 0)
        if not lines:
            raise UserError(_(
                '%s: the order has no positive-quantity lines for the '
                'e-invoice.', self.name))
        for num, line in enumerate(lines, start=1):
            qty = line.qty
            percent = sum(line.tax_ids.mapped('amount'))
            vat_rate, vat_other = api_model._map_vat_rate(
                percent, bool(line.tax_ids))
            item = {
                'num': num,
                'name': line.full_product_name
                        or line.product_id.display_name or '/',
                'code': line.product_id.default_code or 'P%s' % num,
                'unit': line.product_id.uom_id.name or _('Unit'),
                'quantity': qty,
                # Discounts are folded into the net price so no separate
                # discount block is needed on the e-invoice.
                'price': fmt_number(line.price_subtotal / qty),
                'detailTotal': fmt_number(line.price_subtotal),
                'detailVatRate': vat_rate,
                'detailVatAmount': fmt_number(
                    line.price_subtotal_incl - line.price_subtotal),
                'detailAmount': fmt_number(line.price_subtotal_incl),
                'feature': 1,
            }
            if vat_other is not None:
                item['detailVatRateOther'] = vat_other
            detail.append(item)

        partner = self.partner_id
        commercial = partner.commercial_partner_id if partner else partner
        customer = {
            # Walk-in customers go on the e-invoice as "khách lẻ" per the
            # cash-register invoice regime (buyer details optional).
            'cus_name': commercial.name if commercial else _('Khách lẻ'),
            'cus_buyer': partner.name if partner else _('Khách lẻ'),
        }
        if commercial:
            tax_code = (commercial.vat or '').replace(' ', '')
            if tax_code and 10 <= len(tax_code) <= 14:
                customer['cus_taxCode'] = tax_code
            address = ', '.join(filter(None, [
                commercial.street, commercial.street2, commercial.city,
                commercial.state_id.name, commercial.country_id.name]))
            if address:
                customer['cus_address'] = address
            if commercial.email:
                customer['cus_email'] = commercial.email[:50]
            if commercial.phone:
                customer['cus_phone'] = commercial.phone[:20]

        payload = {
            'init_invoice': 'HDGTGTMTT',
            'action': 'create',
            'date_export': fields.Date.to_string(
                self.date_order.date() if self.date_order
                else fields.Date.context_today(self)),
            'payment_type': self._einvoice_payment_type(),
            'vat_rate': -1,
            'total': self.amount_total - self.amount_tax,
            'vat_amount': self.amount_tax,
            'discount_amount': 0,
            'amount': self.amount_total,
            'customer': customer,
            'detail': detail,
            'autoSign': 1 if api_model._get_param('auto_sign', 'True') not in
                        ('False', '0', '') else 0,
        }
        serial = api_model._get_param('serial_mtt')
        if serial:
            payload['serial'] = serial
        return payload

    def _einvoice_payment_type(self):
        """1 = cash, 2 = bank transfer, 3 = mixed (API payment_type codes)."""
        self.ensure_one()
        journal_types = set(
            self.payment_ids.mapped('payment_method_id.journal_id.type'))
        if journal_types == {'cash'}:
            return 1
        if journal_types and 'cash' not in journal_types:
            return 2
        return 3

    def action_sync_einvoice(self):
        """Refresh number / GDT code / status from the provider."""
        api_model = self.env['hoadon30s.api']
        orders = self.filtered('einvoice_lookup_code')
        if not orders:
            return True
        date_from = min(orders.mapped('date_order')).date()
        date_to = max(orders.mapped('date_order')).date()
        data = api_model._call_checked('api/invoice/get-data', {
            'init_invoice': 'HDGTGTMTT',
            'from_date': fields.Date.to_string(date_from),
            'to_date': fields.Date.to_string(date_to),
            'type': [0, 1],
            'lookup_code': orders.mapped('einvoice_lookup_code'),
        })
        by_id_attr = {inv.get('id_attr'): inv
                      for inv in (data.get('data') or [])}
        for order in orders:
            inv = by_id_attr.get(order.einvoice_id_attr)
            if not inv:
                continue
            vals = {}
            status = STATUS_BY_CODE.get(inv.get('status'))
            if status:
                vals['einvoice_status'] = status
            if inv.get('no'):
                vals['einvoice_no'] = str(inv['no'])
            if inv.get('code_cqt'):
                vals['einvoice_code_cqt'] = inv['code_cqt']
            if vals:
                order.write(vals)
        return True
