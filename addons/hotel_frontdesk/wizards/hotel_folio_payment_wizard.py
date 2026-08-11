# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import formatLang


class HotelFolioPaymentWizard(models.TransientModel):
    _name = 'hotel.folio.payment.wizard'
    _description = 'Register a Payment on a Folio'

    folio_id = fields.Many2one(
        'hotel.folio', string='Folio', required=True, ondelete='cascade',
    )
    # Not required at DB level: the NOT NULL constraint fires before the
    # compute has run on create. The view marks it required instead.
    partner_id = fields.Many2one(
        'res.partner', string='Received From',
        compute='_compute_partner_id', store=True, readonly=False,
        help='Defaults to the party the folio is billed to: the guest on a '
             'guest folio, the company on a company folio.',
    )
    payment_date = fields.Date(
        'Payment Date', required=True, default=fields.Date.context_today,
    )
    amount = fields.Float('Amount', required=True, digits=(16, 2))
    balance = fields.Float(
        'Balance Due', related='folio_id.balance', readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency', related='folio_id.currency_id', readonly=True,
    )
    journal_id = fields.Many2one(
        'account.journal', string='Payment Method',
        domain="[('type', 'in', ('bank', 'cash'))]", required=True,
        help='Cash drawer or bank/card journal the money lands in.',
    )
    communication = fields.Char('Memo')

    @api.depends('folio_id')
    def _compute_partner_id(self):
        for wizard in self:
            folio = wizard.folio_id
            wizard.partner_id = folio.bill_to_id or folio.guest_id

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if 'journal_id' in fields_list and not vals.get('journal_id'):
            # sudo: reception has no accounting access but must be able to
            # take money at the desk; this only picks the default journal.
            journal = self.env['account.journal'].sudo().search([
                ('type', 'in', ('bank', 'cash')),
                ('company_id', '=', self.env.company.id),
            ], limit=1)
            vals['journal_id'] = journal.id
        return vals

    def action_register_payment(self):
        """Create and post an account.payment against this folio."""
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        if currency.compare_amounts(self.amount, 0) <= 0:
            raise UserError(_('Payment amount must be positive.'))

        # sudo: reception drives check-in/out and takes payment at the desk
        # but holds no accounting rights. Values are derived from this folio,
        # so this does not widen what reception can reach.
        payment = self.env['account.payment'].sudo().create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner_id.id,
            'amount': self.amount,
            'date': self.payment_date,
            'journal_id': self.journal_id.id,
            'memo': self.communication or self.folio_id.name,
            'hotel_folio_id': self.folio_id.id,
        })
        payment.action_post()

        # Settling after the invoice exists: match it straight away so the
        # invoice does not stay open in the receivable ledger.
        if self.folio_id.invoice_id:
            self.folio_id._reconcile_folio_payments(self.folio_id.invoice_id)

        self.folio_id.message_post(body=_(
            'Payment of %(amount)s registered (%(journal)s).',
            amount=formatLang(self.env, self.amount, currency_obj=currency),
            journal=self.journal_id.name,
        ))
        return {'type': 'ir.actions.act_window_close'}
