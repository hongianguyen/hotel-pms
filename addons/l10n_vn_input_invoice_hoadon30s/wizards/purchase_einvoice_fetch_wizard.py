# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..models.hoadon30s_sync_api import MAX_RANGE_DAYS


class PurchaseEinvoiceFetchWizard(models.TransientModel):
    _name = 'hoadon30s.purchase.einvoice.fetch.wizard'
    _description = 'Download Input VAT E-Invoices'

    date_from = fields.Date('From', required=True)
    date_to = fields.Date('To', required=True)
    include_mtt = fields.Boolean(
        'Include Cash Register Invoices', default=True,
        help='Also download hoá đơn máy tính tiền issued to the company.')
    want_pdf = fields.Boolean(
        'Download PDF Copies', default=True,
        help='Attach the vendor\'s PDF to each invoice as well as the XML.')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        res.setdefault('date_to', today)
        res.setdefault('date_from', today.replace(day=1))
        return res

    @api.constrains('date_from', 'date_to')
    def _check_range(self):
        for wizard in self:
            if wizard.date_to < wizard.date_from:
                raise UserError(_('The end date must not precede the '
                                  'start date.'))
            if (wizard.date_to - wizard.date_from).days > MAX_RANGE_DAYS:
                raise UserError(_(
                    'The provider accepts a range of at most one month per '
                    'download. Split the period into several downloads.'))

    def action_fetch(self):
        """Download the period, then show what came back."""
        self.ensure_one()
        Registry = self.env['hoadon30s.purchase.einvoice']
        summary = Registry.fetch_purchase_invoices(
            self.date_from, self.date_to,
            include_mtt=self.include_mtt, want_pdf=self.want_pdf)
        message = _(
            '%(found)s invoice(s) downloaded — %(created)s new, '
            '%(updated)s updated, %(no_xml)s without XML, '
            '%(parse_errors)s could not be parsed. '
            '%(partners_created)s vendor(s) created.', **summary)
        action = self.env['ir.actions.act_window']._for_xml_id(
            'l10n_vn_input_invoice_hoadon30s.action_purchase_einvoice')
        action['context'] = {'search_default_filter_not_billed': 1}
        action['help'] = '<p class="o_view_nocontent_smiling_face">%s</p>' % (
            message)
        return action

    def action_previous_month(self):
        self.ensure_one()
        first_of_this_month = fields.Date.context_today(self).replace(day=1)
        previous = first_of_this_month - relativedelta(months=1)
        self.write({
            'date_from': previous,
            'date_to': first_of_this_month - relativedelta(days=1),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
