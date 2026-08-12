# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .hoadon30s_api import (
    EINVOICE_STATUSES, FINAL_STATUSES, STATUS_BY_CODE, fmt_number,
)

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    einvoice_id_attr = fields.Char(
        'E-Invoice ID', readonly=True, copy=False, index=True,
        help='id_attr of this invoice at hoadon30s.vn.')
    einvoice_lookup_code = fields.Char(
        'E-Invoice Lookup Code', readonly=True, copy=False)
    einvoice_serial = fields.Char('E-Invoice Serial', readonly=True, copy=False)
    einvoice_no = fields.Char('E-Invoice No.', readonly=True, copy=False)
    einvoice_code_cqt = fields.Char(
        'Tax Authority Code', readonly=True, copy=False)
    einvoice_status = fields.Selection(
        EINVOICE_STATUSES, string='E-Invoice Status', readonly=True,
        copy=False, tracking=True)
    einvoice_error = fields.Text('E-Invoice Error', readonly=True, copy=False)

    # ── Issue ────────────────────────────────────────────────────────────

    def action_issue_einvoice(self):
        api_model = self.env['hoadon30s.api']
        for move in self:
            if move.move_type != 'out_invoice':
                raise UserError(_(
                    '%s: only customer invoices can be issued as VAT '
                    'e-invoices. Credit notes need a manual adjustment '
                    'invoice on hoadon30s.vn.', move.display_name))
            if move.state != 'posted':
                raise UserError(_(
                    '%s: post the invoice before issuing the e-invoice.',
                    move.display_name))
            if move.einvoice_id_attr:
                raise UserError(_(
                    '%s: an e-invoice was already issued (lookup code %s).',
                    move.display_name, move.einvoice_lookup_code))
            if move.sudo().pos_order_ids:
                raise UserError(_(
                    '%s: this invoice comes from a POS order, which issues '
                    'its own cash-register e-invoice.', move.display_name))

            payload = move._prepare_einvoice_payload()
            data = api_model._call_checked('api/invoice/create', payload)
            status = 'draft'
            if data.get('autoSign') == 200:
                status = 'signed'
            if data.get('sendCQT') == 200:
                status = 'sent'
            move.write({
                'einvoice_id_attr': data.get('id_attr'),
                'einvoice_lookup_code': data.get('lookup_code'),
                'einvoice_serial': payload.get('serial'),
                'einvoice_status': status,
                'einvoice_error': False,
            })
            move.message_post(body=_(
                'VAT e-invoice created on hoadon30s.vn — lookup code '
                '%(lookup)s (serial %(serial)s).',
                lookup=move.einvoice_lookup_code,
                serial=move.einvoice_serial))
        # Pull the invoice number / tax authority code allocated on signing.
        self.action_sync_einvoice()
        return True

    def _prepare_einvoice_payload(self):
        """Build the multi-tax-line HDGTGT create payload for this invoice."""
        self.ensure_one()
        api_model = self.env['hoadon30s.api']

        currency = self.currency_id.name
        if currency not in ('VND', 'USD'):
            raise UserError(_(
                '%s: the e-invoice service only accepts VND or USD '
                'invoices (this one is %s).', self.display_name, currency))

        detail = []
        lines = self.invoice_line_ids.filtered(
            lambda l: l.display_type == 'product')
        if not lines:
            raise UserError(_(
                '%s: the invoice has no product lines to put on the '
                'e-invoice.', self.display_name))
        for num, line in enumerate(lines, start=1):
            qty = line.quantity or 1.0
            percent = sum(line.tax_ids.mapped('amount'))
            vat_rate, vat_other = api_model._map_vat_rate(
                percent, bool(line.tax_ids))
            item = {
                'num': num,
                'name': line.name or line.product_id.display_name or '/',
                'code': line.product_id.default_code or 'L%s' % num,
                'unit': line.product_uom_id.name or _('Unit'),
                'quantity': qty,
                'price': fmt_number(line.price_subtotal / qty),
                'total': fmt_number(line.price_subtotal),
                'vatRate': vat_rate,
                'vatAmount': fmt_number(line.price_total - line.price_subtotal),
                'amount': fmt_number(line.price_total),
                'feature': 1,
            }
            if vat_other is not None:
                item['vatRateOther'] = vat_other
            detail.append(item)

        partner = self.partner_id
        commercial = partner.commercial_partner_id
        tax_code = (commercial.vat or '').replace(' ', '')
        if tax_code and not 10 <= len(tax_code) <= 14:
            raise UserError(_(
                '%(move)s: the tax code of %(partner)s (%(vat)s) must be '
                '10 to 14 characters for a Vietnamese e-invoice.',
                move=self.display_name, partner=commercial.name,
                vat=tax_code))
        address = ', '.join(filter(None, [
            commercial.street, commercial.street2, commercial.city,
            commercial.state_id.name, commercial.country_id.name]))

        payload = {
            'init_invoice': 'HDGTGT',
            'action': 'create',
            'date_export': fields.Date.to_string(
                self.invoice_date or fields.Date.context_today(self)),
            'currency': currency,
            'payment_type': 3,
            'vat_rate': -1,
            'total': self.amount_untaxed,
            'vat_amount': self.amount_tax,
            'discount_amount': 0,
            'amount': self.amount_total,
            'cus_name': commercial.name,
            'cus_buyer': partner.name if partner != commercial else '',
            'cus_address': address,
            'detail': detail,
            'autoSign': 1 if api_model._get_param('auto_sign', 'True') not in
                        ('False', '0', '') else 0,
        }
        serial = api_model._get_param('serial_vat')
        if serial:
            payload['serial'] = serial
        if tax_code:
            payload['cus_taxCode'] = tax_code
        if commercial.phone:
            payload['cus_phone'] = commercial.phone[:20]
        if commercial.email:
            payload['cus_email'] = commercial.email[:50]
        return payload

    # ── Status sync ──────────────────────────────────────────────────────

    def action_sync_einvoice(self):
        api_model = self.env['hoadon30s.api']
        for move in self.filtered('einvoice_id_attr'):
            data = api_model._call_checked('api/invoice/sync-data', {
                'init_invoice': 'HDGTGT',
                'id_attr': move.einvoice_id_attr,
            })
            move._update_from_sync(data)
        return True

    def _update_from_sync(self, data):
        self.ensure_one()
        inv = data.get('data') or {}
        vals = {}
        status = STATUS_BY_CODE.get(data.get('statusInv'))
        if status:
            vals['einvoice_status'] = status
        if inv.get('no'):
            vals['einvoice_no'] = str(inv['no'])
        if inv.get('code_cqt'):
            vals['einvoice_code_cqt'] = inv['code_cqt']
        if inv.get('serial'):
            vals['einvoice_serial'] = inv['serial']
        if vals:
            self.write(vals)

    @api.model
    def _cron_sync_einvoices(self):
        """Poll the provider for invoices still waiting on a GDT code."""
        if not self.env['hoadon30s.api']._is_configured():
            return
        moves = self.search([
            ('einvoice_id_attr', '!=', False),
            ('einvoice_status', 'not in', FINAL_STATUSES),
        ], limit=200)
        for move in moves:
            try:
                move.action_sync_einvoice()
            except Exception:
                _logger.exception(
                    'e-invoice status sync failed for %s', move.display_name)

    # ── Cancel ───────────────────────────────────────────────────────────

    def action_cancel_einvoice(self):
        api_model = self.env['hoadon30s.api']
        for move in self.filtered('einvoice_id_attr'):
            api_model._call_checked('api/invoice/cancel', {
                'id_attr': move.einvoice_id_attr,
                'reason': _('Cancelled from Odoo (%s)', move.display_name),
                'date_cancel': fields.Date.to_string(
                    fields.Date.context_today(move)),
                'send': 0,
            })
            move.write({'einvoice_status': 'cancelled'})
            move.message_post(body=_('VAT e-invoice cancelled on hoadon30s.vn.'))
        return True
