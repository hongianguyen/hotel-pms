# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    is_hotel_folio = fields.Boolean(
        'Charge to Room',
        help='Orders paid with this method are posted to the in-house guest\'s '
             'hotel folio instead of being settled in the point of sale.',
    )

    # Odoo restricts this to receivable accounts, but a receivable account
    # cannot survive on an invoice product line — Odoo reclassifies it out of
    # invoice_line_ids entirely. The folio charge must reach the checkout
    # invoice as a normal line, so the clearing account has to be a current
    # asset. Widen the domain rather than carry a second account field.
    receivable_account_id = fields.Many2one(
        domain=[('reconcile', '=', True),
                ('account_type', 'in', ('asset_receivable', 'asset_current'))],
    )

    @api.constrains('is_hotel_folio', 'receivable_account_id')
    def _check_hotel_folio_account(self):
        for method in self:
            if not method.is_hotel_folio:
                continue
            account = method.receivable_account_id
            if not account:
                raise ValidationError(_(
                    'Payment method "%s" charges to the hotel folio, so it needs '
                    'an Intermediary Account. Use a reconcilable Current Asset '
                    'account — the same account will be credited when the folio '
                    'is invoiced at check-out, clearing it to zero.'
                ) % method.name)
            if account.account_type != 'asset_current':
                raise ValidationError(_(
                    'The Intermediary Account on "%(method)s" is %(type)s. A room-charge '
                    'clearing account must be a Current Asset: Odoo removes '
                    'receivable accounts from invoice lines, so the charge would '
                    'never reach the guest\'s check-out invoice.',
                    method=method.name, type=account.account_type,
                ))
            if not account.reconcile:
                raise ValidationError(_(
                    'The Intermediary Account on "%s" must allow reconciliation '
                    'so the POS debit and the folio invoice credit can be matched off.'
                ) % method.name)

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ['is_hotel_folio']
