# -*- coding: utf-8 -*-
import hashlib
import json
import logging

from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError
from odoo.modules.module import current_test
from odoo.tools import float_compare

from . import gdt_xml
from .gdt_xml import LINE_NATURE_DISCOUNT, LINE_NATURE_NOTE

_logger = logging.getLogger(__name__)

STATE_LABELS = [
    ('downloaded', 'Downloaded'),
    ('no_xml', 'XML Unavailable'),
    ('parse_error', 'Parse Error'),
    ('billed', 'Bill Created'),
    ('ignored', 'Ignored'),
]


class Hoadon30sPurchaseEinvoice(models.Model):
    """An input (purchase) VAT e-invoice downloaded from the GDT portal.

    Every downloaded invoice lands here first, whether or not its XML could
    be retrieved and whether or not a vendor bill was made from it. Downloads
    are billed per invoice by the provider, so nothing is ever discarded: a
    row that cannot be parsed is kept with its error so the same invoice is
    not paid for twice.
    """
    _name = 'hoadon30s.purchase.einvoice'
    _description = 'Input VAT E-Invoice (hoadon30s.vn)'
    _order = 'invoice_date desc, id desc'
    _rec_name = 'display_label'

    # ── Natural key ──────────────────────────────────────────────────────
    # The GDT identifies an invoice by seller + form + serial + number.
    seller_tax_code = fields.Char('Seller Tax Code', required=True,
                                  readonly=True, index=True)
    form_no = fields.Char('Form No.', readonly=True)
    serial = fields.Char('Serial', readonly=True)
    number = fields.Char('Invoice No.', required=True, readonly=True)

    display_label = fields.Char(compute='_compute_display_label', store=True)
    # A single stored key rather than a composite UNIQUE: form_no and serial
    # are optional, and in Postgres NULLs never collide, which would let the
    # same invoice be downloaded (and paid for) twice.
    natural_key = fields.Char(compute='_compute_natural_key', store=True,
                              index=True)
    is_mtt = fields.Boolean('Cash Register Invoice', readonly=True)
    invoice_date = fields.Date('Issue Date', readonly=True, index=True)
    code_cqt = fields.Char('Tax Authority Code', readonly=True)
    state = fields.Selection(STATE_LABELS, default='downloaded',
                             required=True, readonly=True, index=True)
    error_message = fields.Text('Message', readonly=True)

    # ── Seller ───────────────────────────────────────────────────────────
    seller_name = fields.Char('Seller', readonly=True)
    seller_address = fields.Char('Seller Address', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Vendor',
                                 readonly=True, index=True)

    # ── Amounts ──────────────────────────────────────────────────────────
    # Digits are left to the company currency: VND has no decimal places and
    # a hardcoded 2-digit scale would misrepresent the invoice.
    currency_name = fields.Char('Currency', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency Record',
                                  compute='_compute_currency_id')
    amount_untaxed = fields.Monetary('Untaxed', readonly=True,
                                     currency_field='currency_id')
    amount_tax = fields.Monetary('VAT', readonly=True,
                                 currency_field='currency_id')
    amount_total = fields.Monetary('Total', readonly=True,
                                   currency_field='currency_id')

    move_id = fields.Many2one('account.move', string='Vendor Bill',
                              readonly=True, index=True)
    xml_file = fields.Binary('Invoice XML', readonly=True, attachment=True)
    xml_filename = fields.Char(compute='_compute_xml_filename')
    pdf_file = fields.Binary('Invoice PDF', readonly=True, attachment=True)
    pdf_filename = fields.Char(compute='_compute_pdf_filename')
    raw_json = fields.Text('Provider JSON', readonly=True)
    parsed_json = fields.Text('Parsed XML', readonly=True)

    _natural_key_unique = models.Constraint(
        'UNIQUE(natural_key)',
        'This input invoice has already been downloaded.')

    @api.depends('serial', 'number', 'seller_name')
    def _compute_display_label(self):
        for rec in self:
            rec.display_label = '%s %s — %s' % (
                rec.serial or '?', rec.number or '?',
                rec.seller_name or rec.seller_tax_code or '')

    @api.depends('seller_tax_code', 'form_no', 'serial', 'number', 'is_mtt')
    def _compute_natural_key(self):
        for rec in self:
            rec.natural_key = self._build_natural_key(
                rec.seller_tax_code, rec.form_no, rec.serial, rec.number,
                rec.is_mtt)

    @api.model
    def _build_natural_key(self, seller_tax_code, form_no, serial, number,
                           mtt):
        return '|'.join([
            (seller_tax_code or '').strip(),
            (form_no or '').strip(),
            (serial or '').strip(),
            (number or '').strip(),
            'MTT' if mtt else 'VAT',
        ])

    @api.depends('currency_name')
    def _compute_currency_id(self):
        Currency = self.env['res.currency']
        company_currency = self.env.company.currency_id
        for rec in self:
            currency = Currency
            if rec.currency_name:
                currency = Currency.with_context(active_test=False).search(
                    [('name', '=', rec.currency_name)], limit=1)
            rec.currency_id = currency or company_currency

    @api.depends('serial', 'number')
    def _compute_xml_filename(self):
        for rec in self:
            rec.xml_filename = '%s-%s.xml' % (rec.serial or 'invoice',
                                              rec.number or rec.id)

    @api.depends('serial', 'number')
    def _compute_pdf_filename(self):
        for rec in self:
            rec.pdf_filename = '%s-%s.pdf' % (rec.serial or 'invoice',
                                              rec.number or rec.id)

    # ── Download & upsert ────────────────────────────────────────────────

    @api.model
    def fetch_purchase_invoices(self, date_from, date_to, include_mtt=True,
                                want_pdf=False):
        """Download input invoices for a period and store them here.

        Returns a summary dict. Each page is committed before the next is
        requested: the provider charges per invoice downloaded, so a failure
        part-way through must not discard what has already been paid for.
        """
        api_model = self.env['hoadon30s.sync.api']
        summary = {'found': 0, 'created': 0, 'updated': 0,
                   'no_xml': 0, 'parse_errors': 0, 'partners_created': 0,
                   'total_reported': 0}
        for mtt in ((False, True) if include_mtt else (False,)):
            for page in api_model.download_purchase(
                    date_from, date_to, mtt=mtt, want_pdf=want_pdf):
                summary['total_reported'] = max(
                    summary['total_reported'], int(page.get('total') or 0))
                for inv in page.get('invoices') or []:
                    self._upsert_from_download(inv, mtt, summary)
                for inv in page.get('invoicesError') or []:
                    summary['found'] += 1
                    summary['no_xml'] += 1
                    self._upsert_error_row(inv, mtt, summary)
                # Downloads are metered — persist each page as it arrives so
                # a later failure cannot discard invoices already paid for.
                # Never inside a test, which must stay in one transaction.
                if not (current_test or tools.config['test_enable']):
                    self.env.cr.commit()
        return summary

    @api.model
    def _upsert_from_download(self, inv, mtt, summary):
        """Store one invoice that came back with XML."""
        summary['found'] += 1
        xml_b64 = inv.get('xml')
        raw_json = inv.get('json')
        if not xml_b64:
            summary['no_xml'] += 1
            return self._upsert_error_row(
                dict(inv, message=_('The provider returned no XML content.')),
                mtt, summary)
        try:
            parsed = gdt_xml.parse_invoice_xml(xml_b64)
        except ValueError as exc:
            summary['parse_errors'] += 1
            return self._upsert_error_row(
                dict(inv, message=str(exc)), mtt, summary,
                state='parse_error', xml_b64=xml_b64)

        seller = parsed['seller']
        seller_tax_code = seller.get('tax_code') or ''
        number = parsed['number'] or ''
        if not seller_tax_code or not number:
            summary['parse_errors'] += 1
            return self._upsert_error_row(
                dict(inv, message=_(
                    'The invoice XML has no seller tax code or no invoice '
                    'number, so it cannot be identified.')),
                mtt, summary, state='parse_error', xml_b64=xml_b64)

        partner, partner_created = self._find_or_create_partner(seller)
        summary['partners_created'] += int(partner_created)
        vals = {
            'form_no': parsed['form_no'],
            'serial': parsed['serial'],
            'invoice_date': parsed['date'] or False,
            'code_cqt': parsed['code_cqt'],
            'seller_name': seller.get('name'),
            'seller_address': seller.get('address'),
            'partner_id': partner.id if partner else False,
            'currency_name': parsed['currency'],
            'amount_untaxed': parsed['total_untaxed'],
            'amount_tax': parsed['total_tax'],
            'amount_total': parsed['total_amount'],
            'xml_file': xml_b64,
            'pdf_file': inv.get('pdf') or False,
            'raw_json': json.dumps(raw_json, ensure_ascii=False)
                        if raw_json else False,
            'parsed_json': json.dumps(parsed, ensure_ascii=False),
            'error_message': False,
        }
        existing = self._find_existing(seller_tax_code, parsed['form_no'],
                                       parsed['serial'], number, mtt)
        if existing:
            # Never overwrite a row already turned into a bill.
            if existing.state != 'billed':
                vals['state'] = 'downloaded'
            existing.write(vals)
            summary['updated'] += 1
            return existing
        vals.update({
            'seller_tax_code': seller_tax_code,
            'number': number,
            'is_mtt': mtt,
            'state': 'downloaded',
        })
        summary['created'] += 1
        return self.create([vals])

    @api.model
    def _upsert_error_row(self, inv, mtt, summary, state='no_xml',
                          xml_b64=False):
        """Store an invoice the provider could not give us XML for.

        These rows carry only header totals, but dropping them would hide
        purchase invoices the company has actually received. Counting is the
        caller's job — this is reached from several paths.
        """
        seller_tax_code, number = self._identify(inv, xml_b64)
        vals = {
            'form_no': str(inv.get('category') or ''),
            'serial': inv.get('serial') or '',
            'invoice_date': inv.get('dateExport') or False,
            'amount_untaxed': inv.get('total') or 0.0,
            'amount_tax': inv.get('amount_vat') or 0.0,
            'amount_total': inv.get('amount_total') or 0.0,
            'raw_json': json.dumps(inv.get('json'), ensure_ascii=False)
                        if inv.get('json') else False,
            'error_message': inv.get('message') or _(
                'The provider could not retrieve the XML for this invoice.'),
            'state': state,
        }
        if xml_b64:
            vals['xml_file'] = xml_b64
        existing = self._find_existing(seller_tax_code, vals['form_no'],
                                       vals['serial'], number, mtt)
        if existing:
            if existing.state == 'billed':
                return existing
            existing.write(vals)
            return existing
        vals.update({
            'seller_tax_code': seller_tax_code,
            'number': number,
            'is_mtt': mtt,
        })
        return self.create([vals])

    @api.model
    def _identify(self, inv, xml_b64=False):
        """Work out a (seller tax code, number) pair for an invoice we could
        not parse.

        Rows in ``invoicesError[]`` carry these outright. Rows in
        ``invoices[]`` do not — the documented schema there is only
        xml/json/pdf — so fall back to the provider's JSON rendition and,
        failing that, to a digest of the XML itself. An invoice has already
        been paid for by the time we see it, so it must always be storable,
        even when nothing about it can be read.
        """
        seller_tax_code = str(inv.get('sellerTaxCode') or '').strip()
        number = str(inv.get('invoiceNumber') or '').strip()
        raw = inv.get('json')
        if isinstance(raw, dict):
            # Field names as the GDT portal itself returns them.
            seller_tax_code = seller_tax_code or str(
                raw.get('nbmst') or raw.get('sellerTaxCode') or '').strip()
            number = number or str(
                raw.get('shdon') or raw.get('invoiceNumber') or '').strip()
        if not seller_tax_code:
            seller_tax_code = 'UNKNOWN'
        if not number and xml_b64:
            digest = hashlib.sha256(
                xml_b64.encode() if isinstance(xml_b64, str) else xml_b64
            ).hexdigest()[:32]
            number = 'XML-%s' % digest
        elif not number:
            number = 'UNIDENTIFIED-%s' % hashlib.sha256(
                json.dumps(inv, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()[:32]
        return seller_tax_code, number

    @api.model
    def _find_existing(self, seller_tax_code, form_no, serial, number, mtt):
        return self.search([('natural_key', '=', self._build_natural_key(
            seller_tax_code, form_no, serial, number, mtt))], limit=1)

    @api.model
    def _find_or_create_partner(self, seller):
        """Match the seller to a vendor, creating one when unknown.

        Matching order: tax code, then exact name.
        """
        Partner = self.env['res.partner']
        tax_code = (seller.get('tax_code') or '').strip()
        name = (seller.get('name') or '').strip()
        if not tax_code and not name:
            return Partner, False
        partner = Partner
        if tax_code:
            partner = Partner.search([('vat', '=', tax_code)], limit=1)
        if not partner and name:
            partner = Partner.search([('name', '=ilike', name)], limit=1)
        if partner:
            if not partner.supplier_rank:
                partner.sudo().write({'supplier_rank': 1})
            return partner, False
        vn = self.env.ref('base.vn', raise_if_not_found=False)
        partner = Partner.create([{
            'name': name or tax_code,
            'vat': tax_code or False,
            'is_company': bool(tax_code),
            'street': seller.get('address') or False,
            'phone': seller.get('phone') or False,
            'email': seller.get('email') or False,
            'country_id': vn.id if vn else False,
            'supplier_rank': 1,
            'comment': _('Created automatically from a downloaded input '
                         'VAT e-invoice.'),
        }])
        return partner, True

    # ── Vendor bill creation ─────────────────────────────────────────────

    def action_create_bill(self):
        """Create a draft vendor bill for each selected invoice."""
        created = self.env['account.move']
        for rec in self:
            created |= rec._create_bill()
        if len(created) == 1:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'res_id': created.id,
                'view_mode': 'form',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vendor Bills'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created.ids)],
        }

    def _create_bill(self):
        """Build one draft vendor bill from the parsed XML.

        Bills are always left in draft: the amounts come from a third party
        and an accountant has to confirm the expense accounts before posting.
        """
        self.ensure_one()
        if self.move_id:
            raise UserError(_(
                'A vendor bill already exists for invoice %s.',
                self.display_label))
        if self.state in ('no_xml', 'parse_error'):
            raise UserError(_(
                'Invoice %(label)s has no usable XML, so a bill cannot be '
                'built from it automatically:\n%(error)s',
                label=self.display_label, error=self.error_message or ''))
        if not self.partner_id:
            raise UserError(_(
                'Invoice %s has no vendor assigned.', self.display_label))
        parsed = json.loads(self.parsed_json or '{}')
        if not parsed:
            raise UserError(_(
                'Invoice %s has no parsed content.', self.display_label))

        move_vals = {
            'move_type': 'in_invoice',
            'partner_id': self.partner_id.id,
            'invoice_date': self.invoice_date or False,
            'ref': '%s %s' % (self.serial or '', self.number or ''),
            'narration': _('Imported from GDT input e-invoice %(label)s'
                           '%(code)s',
                           label=self.display_label,
                           code=' (tax authority code %s)' % self.code_cqt
                                if self.code_cqt else ''),
            'invoice_line_ids': [
                (0, 0, vals) for vals in self._prepare_bill_lines(parsed)],
        }
        currency = self._currency_for_bill(parsed)
        if currency:
            move_vals['currency_id'] = currency.id
        move = self.env['account.move'].create([move_vals])
        self.write({'move_id': move.id, 'state': 'billed'})
        self._check_bill_totals(move)
        return move

    def _currency_for_bill(self, parsed):
        name = parsed.get('currency') or self.currency_name
        if not name or name == self.env.company.currency_id.name:
            return self.env['res.currency']
        currency = self.env['res.currency'].with_context(
            active_test=False).search([('name', '=', name)], limit=1)
        if not currency:
            raise UserError(_(
                'Invoice %(label)s is in %(currency)s, which is not set up in '
                'Odoo. Activate that currency first.',
                label=self.display_label, currency=name))
        return currency

    def _prepare_bill_lines(self, parsed):
        """Turn parsed XML lines into vendor bill line values.

        No product matching is attempted — the line keeps the seller's own
        description and lands on the vendor's default expense account, which
        an accountant reviews before posting.
        """
        self.ensure_one()
        lines = []
        for line in parsed.get('lines') or []:
            nature = line.get('nature') or '1'
            if nature == LINE_NATURE_NOTE:
                # Free-text annotation, carries no amount.
                continue
            subtotal = line.get('subtotal') or 0.0
            if nature == LINE_NATURE_DISCOUNT:
                subtotal = -abs(subtotal)
            quantity = line.get('quantity') or 0.0
            if quantity:
                price_unit = line.get('price_unit') or (subtotal / quantity)
            else:
                quantity, price_unit = 1.0, subtotal
            if nature == LINE_NATURE_DISCOUNT and price_unit > 0:
                price_unit = -price_unit
            tax = self._find_purchase_tax(line)
            lines.append({
                'name': line.get('name') or _('Imported line'),
                'quantity': quantity,
                'price_unit': price_unit,
                'tax_ids': [(6, 0, tax.ids)],
            })
        if not lines:
            # Some cash-register invoices carry totals but no itemisation.
            lines.append({
                'name': _('Input invoice %s', self.display_label),
                'quantity': 1.0,
                'price_unit': self.amount_untaxed,
                'tax_ids': [(6, 0, [])],
            })
        return lines

    def _find_purchase_tax(self, line):
        """Find the purchase tax matching a line's VAT rate.

        A Vietnamese purchase tax with no UNECE tax-type code makes Odoo's
        import framework drop the tax and book the gross amount as untaxed,
        so such a tax is refused rather than used silently.
        """
        AccountTax = self.env['account.tax']
        if not line.get('taxable'):
            return AccountTax
        rate = line.get('tax_rate') or 0.0
        taxes = AccountTax.search([
            ('type_tax_use', '=', 'purchase'),
            ('amount_type', '=', 'percent'),
            ('amount', '=', rate),
            ('company_id', '=', self.env.company.id),
        ])
        if not taxes:
            _logger.warning(
                'No purchase tax configured for %s%% on input invoice %s; '
                'the line is imported untaxed.', rate, self.display_label)
            return AccountTax
        if 'unece_code' in AccountTax._fields:
            with_code = taxes.filtered(lambda t: t.unece_code)
            if with_code:
                return with_code[0]
            _logger.warning(
                'Purchase tax %s has no UNECE code; Odoo would post the '
                'gross amount as untaxed, so input invoice %s is imported '
                'without it.', taxes[0].display_name, self.display_label)
            return AccountTax
        return taxes[0]

    def _check_bill_totals(self, move):
        """Compare the created bill against the totals stated on the XML.

        Rounding, missing taxes or an unmapped line can make Odoo's computed
        total differ from what the vendor actually invoiced. That is never
        corrected silently — it is written onto the record and logged on the
        bill so an accountant sees it before posting.
        """
        self.ensure_one()
        currency = move.currency_id or self.env.company.currency_id
        mismatches = []
        for label, stated, computed in (
                (_('Untaxed'), self.amount_untaxed, move.amount_untaxed),
                (_('VAT'), self.amount_tax, move.amount_tax),
                (_('Total'), self.amount_total, move.amount_total)):
            if float_compare(stated, computed,
                             precision_rounding=currency.rounding) != 0:
                mismatches.append(_(
                    '%(label)s: invoice states %(stated)s, Odoo computed '
                    '%(computed)s',
                    label=label, stated=stated, computed=computed))
        if not mismatches:
            return
        message = _(
            'This bill does not match the amounts on the original '
            'e-invoice. Check the lines and taxes before posting.\n%s',
            '\n'.join(mismatches))
        self.write({'error_message': message})
        move.message_post(body=message.replace('\n', '<br/>'))

    def action_ignore(self):
        self.filtered(lambda r: r.state != 'billed').write({'state': 'ignored'})

    def action_reset_to_downloaded(self):
        self.filtered(lambda r: not r.move_id).write({'state': 'downloaded'})

    def action_open_xml(self):
        """Show the decoded XML — useful when a parse needs checking."""
        self.ensure_one()
        if not self.xml_file:
            raise UserError(_('This invoice has no XML attached.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/xml_file/%s?download=true' % (
                self._name, self.id, self.xml_filename),
            'target': 'self',
        }

    # ── Cron ─────────────────────────────────────────────────────────────

    @api.model
    def _cron_fetch_purchase_einvoices(self):
        """Download recently issued input invoices.

        Starts from a stored watermark so a range that has already been paid
        for is never downloaded twice, and never asks for more than the
        provider's one-month window.
        """
        api_model = self.env['hoadon30s.sync.api']
        if not api_model._is_configured() \
                or not api_model._get_param('gdt_username') \
                or not api_model._get_param('cron_enabled'):
            return
        icp = self.env['ir.config_parameter'].sudo()
        today = fields.Date.context_today(self)
        watermark = icp.get_param('hoadon30s.sync.last_fetch_date')
        if watermark:
            # Re-scan a few days: invoices are often uploaded to the portal
            # some days after their issue date.
            date_from = fields.Date.subtract(
                fields.Date.to_date(watermark), days=3)
        else:
            date_from = fields.Date.subtract(today, days=7)
        # One download covers at most a month. If the cron has been off for
        # longer, cover the oldest outstanding month rather than jumping to
        # today — otherwise the gap in between would be skipped for good.
        earliest = fields.Date.subtract(today, days=30)
        if date_from < earliest:
            date_to = fields.Date.add(date_from, days=30)
            _logger.warning(
                'hoadon30s input invoices are %s days behind; catching up '
                'one month at a time (%s → %s). The next run continues from '
                'there.', (today - date_from).days, date_from, date_to)
        else:
            date_to = today
        try:
            summary = self.fetch_purchase_invoices(date_from, date_to)
            icp.set_param('hoadon30s.sync.last_fetch_date',
                          fields.Date.to_string(date_to))
            _logger.info('hoadon30s input-invoice fetch %s → %s: %s',
                         date_from, date_to, summary)
        except Exception:
            _logger.exception('hoadon30s input-invoice fetch failed')
