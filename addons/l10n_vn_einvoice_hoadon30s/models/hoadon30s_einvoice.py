# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models, _

from .hoadon30s_api import EINVOICE_STATUSES, STATUS_BY_CODE

_logger = logging.getLogger(__name__)


class Hoadon30sEinvoice(models.Model):
    """Registry of VAT e-invoices issued at hoadon30s.vn.

    Mirrors every invoice the company issued through the provider — whether
    it originated in Odoo (Accounting, Hotel PMS, POS) or was keyed directly
    into the hoadon30s web app — and auto-creates the buyer partners.
    """
    _name = 'hoadon30s.einvoice'
    _description = 'VAT E-Invoice (hoadon30s.vn)'
    _order = 'date_export desc, id desc'
    _rec_name = 'display_label'

    id_attr = fields.Char('Provider ID', required=True, readonly=True, index=True)
    init_type = fields.Selection([
        ('HDGTGT', 'VAT Invoice'),
        ('HDGTGTMTT', 'VAT Invoice (Cash Register)'),
    ], string='Invoice Kind', required=True, readonly=True)
    display_label = fields.Char(
        compute='_compute_display_label', store=True)
    serial = fields.Char('Serial', readonly=True)
    no = fields.Char('Invoice No.', readonly=True)
    date_export = fields.Date('Issue Date', readonly=True, index=True)
    lookup_code = fields.Char('Lookup Code', readonly=True)
    code_cqt = fields.Char('Tax Authority Code', readonly=True)
    status = fields.Selection(EINVOICE_STATUSES, readonly=True)
    partner_id = fields.Many2one(
        'res.partner', string='Buyer', readonly=True, index=True)
    cus_name = fields.Char('Buyer Name', readonly=True)
    cus_tax_code = fields.Char('Buyer Tax Code', readonly=True)
    cus_address = fields.Char('Buyer Address', readonly=True)
    currency = fields.Char('Currency', readonly=True)
    total = fields.Float('Untaxed', readonly=True, digits=(16, 2))
    vat_amount = fields.Float('VAT', readonly=True, digits=(16, 2))
    amount = fields.Float('Total', readonly=True, digits=(16, 2))
    move_id = fields.Many2one(
        'account.move', string='Odoo Invoice', readonly=True, index=True)
    pos_order_id = fields.Many2one(
        'pos.order', string='POS Order', readonly=True, index=True)
    raw_data = fields.Text('Raw Data', readonly=True)

    _id_attr_unique = models.Constraint(
        'UNIQUE(id_attr)',
        'This e-invoice was already imported.')

    @api.depends('serial', 'no', 'lookup_code')
    def _compute_display_label(self):
        for rec in self:
            rec.display_label = '%s %s' % (
                rec.serial or '?', rec.no or rec.lookup_code or rec.id_attr)

    # ── Fetch from provider ──────────────────────────────────────────────

    @api.model
    def fetch_invoices(self, date_from, date_to):
        """Pull issued e-invoices from the provider and upsert them here.

        Returns a summary dict: counts of fetched invoices and newly
        created partners.
        """
        api_model = self.env['hoadon30s.api']
        found = created = partners_new = 0
        for init_type in ('HDGTGT', 'HDGTGTMTT'):
            data = api_model._call_checked('api/invoice/get-data', {
                'init_invoice': init_type,
                'from_date': fields.Date.to_string(date_from),
                'to_date': fields.Date.to_string(date_to),
                # 0 = keyed into the hoadon30s web app, 1 = created via API
                'type': [0, 1],
            })
            for inv in data.get('data') or []:
                found += 1
                is_new, partner_created = self._upsert(init_type, inv)
                created += int(is_new)
                partners_new += int(partner_created)
        return {'found': found, 'created': created,
                'partners_created': partners_new}

    @api.model
    def _upsert(self, init_type, inv):
        id_attr = inv.get('id_attr')
        existing = self.search([('id_attr', '=', id_attr)], limit=1)
        partner, partner_created = self._find_or_create_partner(inv)
        vals = {
            'init_type': init_type,
            'serial': inv.get('serial'),
            'no': str(inv['no']) if inv.get('no') else False,
            'date_export': inv.get('date_export') or False,
            'lookup_code': inv.get('lookup_code'),
            'code_cqt': inv.get('code_cqt'),
            'status': STATUS_BY_CODE.get(inv.get('status'), 'draft'),
            'partner_id': partner.id if partner else False,
            'cus_name': inv.get('cus_name') or inv.get('cus_buyer'),
            'cus_tax_code': inv.get('cus_taxCode'),
            'cus_address': inv.get('cus_address'),
            'currency': inv.get('currency'),
            'total': inv.get('total') or 0.0,
            'vat_amount': inv.get('vat_amount') or 0.0,
            'amount': inv.get('amount') or 0.0,
            'raw_data': json.dumps(inv, ensure_ascii=False),
        }
        if init_type == 'HDGTGT':
            move = self.env['account.move'].search(
                [('einvoice_id_attr', '=', id_attr)], limit=1)
            vals['move_id'] = move.id
            # The provider allocates number and GDT code after signing;
            # push whatever it has back onto the Odoo invoice.
            if move:
                move._update_from_sync(
                    {'statusInv': inv.get('status'), 'data': inv})
        else:
            order = self.env['pos.order'].search(
                [('einvoice_id_attr', '=', id_attr)], limit=1)
            vals['pos_order_id'] = order.id
        if existing:
            existing.write(vals)
            return False, partner_created
        vals['id_attr'] = id_attr
        self.create([vals])
        return True, partner_created

    @api.model
    def _find_or_create_partner(self, inv):
        """Match the buyer to a partner, creating one when unknown.

        Returns (partner, created?). Matching order: tax code, then exact
        name. Invoices with neither a buyer name nor a tax code (anonymous
        cash-register sales) get no partner.
        """
        Partner = self.env['res.partner']
        tax_code = (inv.get('cus_taxCode') or '').strip()
        name = (inv.get('cus_name') or '').strip() \
            or (inv.get('cus_buyer') or '').strip()
        if not tax_code and not name:
            return Partner, False
        partner = Partner
        if tax_code:
            partner = Partner.search([('vat', '=', tax_code)], limit=1)
        if not partner and name:
            partner = Partner.search([('name', '=ilike', name)], limit=1)
        if partner:
            return partner, False
        partner = Partner.create([{
            'name': name or tax_code,
            'vat': tax_code or False,
            'is_company': bool(tax_code),
            'street': inv.get('cus_address') or False,
            'phone': inv.get('cus_phone') or False,
            'email': inv.get('cus_email') or False,
            'country_id': self.env.ref('base.vn').id,
            'customer_rank': 1,
            'comment': _('Created automatically from hoadon30s '
                         'e-invoice sync.'),
        }])
        return partner, True

    @api.model
    def _cron_fetch_einvoices(self):
        """Daily pull of the last 7 days of issued e-invoices."""
        if not self.env['hoadon30s.api']._is_configured():
            return
        today = fields.Date.context_today(self)
        try:
            summary = self.fetch_invoices(
                fields.Date.subtract(today, days=7), today)
            _logger.info('hoadon30s e-invoice fetch: %s', summary)
        except Exception:
            _logger.exception('hoadon30s e-invoice fetch failed')
