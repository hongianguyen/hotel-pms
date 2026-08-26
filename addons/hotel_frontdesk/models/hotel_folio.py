# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import timedelta


class HotelFolio(models.Model):
    _name = 'hotel.folio'
    _description = 'Hotel Folio'
    _inherit = ['mail.thread']
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char('Folio #', readonly=True, copy=False, default='New')
    folio_type = fields.Selection([
        ('guest', 'Guest Folio'),
        ('company', 'Company Folio (City Ledger)'),
    ], string='Folio Type', default='guest', required=True, index=True,
        help='Guest folio: charges the staying guest settles on departure '
             '(guest ledger).\n'
             'Company folio: charges routed to a travel agency or corporate '
             'account, invoiced to that company and — with credit terms — '
             'carried in the city ledger until it is paid.')
    linked_folio_id = fields.Many2one(
        'hotel.folio', string='Linked Folio', copy=False, ondelete='set null',
        help='The counterpart folio for this stay: the company folio of a '
             'guest folio, or vice versa.',
    )
    reservation_id = fields.Many2one(
        'hotel.reservation', string='Primary Reservation',
        ondelete='set null',
    )
    # All reservations sharing this folio (single or group)
    reservation_ids = fields.One2many(
        'hotel.reservation', 'folio_id', string='Reservations',
    )
    is_group = fields.Boolean('Group Folio', compute='_compute_is_group', store=True)
    group_id = fields.Many2one(
        'hotel.booking.group', string='Group Booking', readonly=True,
        ondelete='set null', copy=False,
        help='Set when this folio is the master folio of a group booking.',
    )
    guest_id = fields.Many2one('res.partner', string='Guest', required=True)
    agency_id = fields.Many2one(
        'res.partner', string='Agency / Company',
        domain="[('is_hotel_agency', '=', True)]",
        help='Travel agency or corporate account this booking came from. '
             'When set, the invoice is issued to this company instead of '
             'the guest.',
    )
    agency_credit_term = fields.Boolean(
        related='agency_id.hotel_credit_term', string='Credit Terms',
    )
    bill_to_id = fields.Many2one(
        'res.partner', string='Bill To', compute='_compute_bill_to_id',
        store=True,
        help='Party the invoice is issued to: the agency/company for '
             'corporate bookings, otherwise the guest.',
    )
    room_id = fields.Many2one(
        'hotel.room', related='reservation_id.room_id',
        string='Room', store=True,
    )
    checkin_date = fields.Date(
        'Check-in', compute='_compute_folio_dates', store=True,
        help='Earliest check-in across all reservations on this folio.',
    )
    checkout_date = fields.Date(
        'Check-out', compute='_compute_folio_dates', store=True,
        help='Latest check-out across all reservations on this folio.',
    )

    line_ids = fields.One2many('hotel.folio.line', 'folio_id', string='Charges')
    total_amount = fields.Float(
        'Total Amount', compute='_compute_total', store=True, digits=(16, 2),
    )

    payment_ids = fields.One2many(
        'account.payment', 'hotel_folio_id', string='Payments',
        help='Deposits and settlements recorded against this folio.',
    )
    amount_paid = fields.Float(
        'Paid', compute='_compute_amount_paid', store=True, digits=(16, 2),
        help='Total of posted payments recorded on this folio.',
    )
    balance = fields.Float(
        'Balance Due', compute='_compute_amount_paid', store=True,
        digits=(16, 2), help='Charges less payments still outstanding.',
    )

    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True, copy=False)
    payment_state = fields.Selection([
        ('open', 'Open'),
        ('invoiced', 'Invoiced'),
        ('paid', 'Paid'),
    ], string='Payment Status', compute='_compute_payment_state', store=True,
        default='open', tracking=True)

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        related='company_id.currency_id', readonly=True,
    )

    # Payment states in which the hotel actually holds the money. Posting a
    # payment lands it in 'in_process'; it only reaches 'paid' once matched,
    # so counting 'paid' alone would ignore every deposit taken at the desk.
    _SETTLED_PAYMENT_STATES = ('in_process', 'paid')

    @api.depends('reservation_ids', 'group_id')
    def _compute_is_group(self):
        for folio in self:
            # A company folio carries no reservation_ids of its own (the
            # children point their folio_id at their guest folios), so fall
            # back to the group link.
            folio.is_group = len(folio.reservation_ids) > 1 or bool(folio.group_id)

    @api.depends('reservation_ids.checkin_date', 'reservation_ids.checkout_date',
                 'reservation_id.checkin_date', 'reservation_id.checkout_date')
    def _compute_folio_dates(self):
        for folio in self:
            reservations = folio.reservation_ids or folio.reservation_id
            checkins = [d for d in reservations.mapped('checkin_date') if d]
            checkouts = [d for d in reservations.mapped('checkout_date') if d]
            folio.checkin_date = min(checkins) if checkins else False
            folio.checkout_date = max(checkouts) if checkouts else False

    @api.depends('agency_id', 'guest_id')
    def _compute_bill_to_id(self):
        for folio in self:
            folio.bill_to_id = folio.agency_id or folio.guest_id

    @api.depends('line_ids.subtotal')
    def _compute_total(self):
        for folio in self:
            folio.total_amount = sum(folio.line_ids.mapped('subtotal'))

    @api.depends('payment_ids.state', 'payment_ids.amount', 'total_amount')
    def _compute_amount_paid(self):
        for folio in self:
            paid = sum(
                folio.payment_ids.filtered(
                    lambda p: p.state in self._SETTLED_PAYMENT_STATES
                ).mapped('amount')
            )
            folio.amount_paid = paid
            folio.balance = folio.total_amount - paid

    @api.depends('balance', 'total_amount', 'amount_paid', 'invoice_id')
    def _compute_payment_state(self):
        for folio in self:
            currency = folio.currency_id or self.env.company.currency_id
            settled = (
                folio.amount_paid
                and currency.compare_amounts(folio.balance, 0) <= 0
            )
            if settled:
                folio.payment_state = 'paid'
            elif folio.invoice_id:
                folio.payment_state = 'invoiced'
            else:
                folio.payment_state = 'open'

    # ── Folio pair (guest ledger / city ledger) ──────────────────────────

    def _guest_folios(self):
        """Guest folios routed to this company folio."""
        return self.search([('linked_folio_id', 'in', self.ids),
                            ('folio_type', '=', 'guest')])

    def settled_payments(self):
        """Payments the hotel actually holds — what the printed folio shows."""
        self.ensure_one()
        return self.payment_ids.filtered(
            lambda p: p.state in self._SETTLED_PAYMENT_STATES
        )

    def action_print_folio(self):
        """Print the folio for the guest to check and sign at departure."""
        return self.env.ref(
            'hotel_frontdesk.action_report_hotel_folio'
        ).report_action(self)

    def is_credit_ledger(self):
        """True when this folio is not expected to be settled at departure.

        A company folio held on the agency's payment terms is carried in the
        city ledger and collected later against its invoice, so its balance
        must not block the guest's departure. Every other folio — including
        an agency folio without credit terms, which prepays — is a
        departure-time settlement.
        """
        self.ensure_one()
        return self.folio_type == 'company' and bool(self.agency_credit_term)

    def amount_due_at_checkout(self, extra_charges=0.0):
        """Amount the guest still has to settle before they may depart.

        ``extra_charges`` covers charges that check-out is about to raise but
        has not written yet (late check-out nights), so the figure quoted to
        reception is the full amount to collect rather than the stale folio
        balance. A credit-ledger folio is never due at the desk, and an
        overpaid folio returns a negative amount (a refund the hotel owes)
        rather than blocking departure.
        """
        self.ensure_one()
        if self.is_credit_ledger():
            return 0.0
        return self.balance + extra_charges

    def _pending_reservations(self):
        """Reservations still checked in that can still charge this folio.

        Covers both directions of the pair: a guest folio has its own
        reservation, while a company folio collects routed charges from every
        guest folio linked to it (a group's rooms, typically).
        """
        self.ensure_one()
        folios = self | self.linked_folio_id | self._guest_folios()
        return self.env['hotel.reservation'].sudo().search([
            ('folio_id', 'in', folios.ids),
            ('state', '=', 'checked_in'),
        ])

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('hotel.folio') or 'New'
        folios = super().create(vals_list)
        # Keep the pair symmetric when one side is created pointing at the
        # other, so either folio can find its counterpart.
        for folio in folios:
            counterpart = folio.linked_folio_id
            if counterpart and counterpart.linked_folio_id != folio:
                counterpart.linked_folio_id = folio.id
        return folios

    def _generate_room_charges(self, reservation=None):
        """Generate one folio line per night of room charges.

        For group bookings, pass the specific reservation explicitly since
        the folio may have no single reservation_id.
        """
        self.ensure_one()
        res = reservation or self.reservation_id
        if not res:
            return
        current = res.checkin_date
        rate = res.nightly_rate
        room_name = res.room_id.name or 'Room'
        # ROH/combo bookings: revenue account of the booked (virtual) type
        # wins over the physical room's type.
        account = (res.room_type_id.revenue_account_id
                   or res.room_id.room_type_id.revenue_account_id)

        lines = []
        while current < res.checkout_date:
            # Check rate plan for per-day rate if available
            # (combo bookings use the combo's fixed rate instead)
            day_rate = rate
            if res.rate_plan_id and not res.combo_id:
                plan_rate = res.rate_plan_id.get_rate_for_date(current)
                if plan_rate:
                    day_rate = plan_rate

            lines.append((0, 0, {
                'name': _('Room %s — %s') % (room_name, current.strftime('%d/%m/%Y')),
                'charge_type': 'room',
                'quantity': 1,
                'amount': day_rate,
                'date': current,
                'account_id': account.id or False,
            }))
            current += timedelta(days=1)

        if lines:
            self.write({'line_ids': lines})

    def action_create_invoice(self):
        """Create account.move (customer invoice) from folio lines."""
        self.ensure_one()
        if self.invoice_id:
            raise UserError(_('Invoice already created for this folio.'))
        if not self.line_ids:
            raise UserError(_('No charges in this folio to invoice.'))

        # sudo: reception users have no accounting access, but check-out must
        # still be able to generate the guest invoice. Scope is limited to
        # this folio's own lines, so this does not widen data exposure.
        journal = self.env['account.journal'].sudo().search([
            ('type', '=', 'sale'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not journal:
            raise UserError(_('No sales journal found. Please configure one.'))

        invoice_lines = []
        for line in self.line_ids:
            account = line.account_id
            if not account:
                # Fallback to default income account
                account = journal.default_account_id
            invoice_lines.append((0, 0, {
                'name': line.name,
                'quantity': line.quantity,
                'price_unit': line.amount,
                'account_id': account.id if account else False,
            }))

        # Corporate/agency bookings: invoice the sending company, not the
        # staying guest. With credit terms the company pays on account per
        # its payment terms; the guest column stays for reference only.
        bill_to = self.bill_to_id or self.guest_id
        move_vals = {
            'move_type': 'out_invoice',
            'partner_id': bill_to.id,
            'journal_id': journal.id,
            'invoice_date': fields.Date.context_today(self),
            'invoice_line_ids': invoice_lines,
            'ref': self.name,
        }
        if self.agency_id and self.agency_id.hotel_credit_term:
            term = self.agency_id.sudo().property_payment_term_id
            if term:
                move_vals['invoice_payment_term_id'] = term.id
        invoice = self.env['account.move'].sudo().create(move_vals)

        self.write({'invoice_id': invoice.id})
        self._reconcile_folio_payments(invoice)
        return invoice

    def _reconcile_folio_payments(self, invoice):
        """Match deposits already taken on this folio against its invoice.

        Payments recorded before check-out sit as outstanding receipts; once
        the invoice exists they are reconciled against it so the folio's
        invoice shows only what is genuinely still due.
        """
        self.ensure_one()
        # sudo: same rationale as invoice creation above — reception drives
        # check-out but holds no accounting rights, and the scope is this
        # folio's own invoice and payments.
        payments = self.sudo().payment_ids.filtered(
            lambda p: p.state in self._SETTLED_PAYMENT_STATES
        )
        if not payments:
            return
        invoice = invoice.sudo()
        if invoice.state == 'draft':
            invoice.action_post()
        lines = (invoice.line_ids + payments.mapped('move_id.line_ids')).filtered(
            lambda l: l.account_id.account_type == 'asset_receivable'
            and not l.reconciled
        )
        if len(lines) > 1:
            lines.reconcile()

    def action_register_payment(self):
        """Open the folio payment wizard (deposit or settlement)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Register Payment'),
            'res_model': 'hotel.folio.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_folio_id': self.id,
                'default_amount': max(self.balance, 0.0),
            },
        }

    def action_view_payments(self):
        """List the payments recorded on this folio."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Folio Payments'),
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': [('hotel_folio_id', '=', self.id)],
            'context': {'create': False},
        }

    def action_view_linked_folio(self):
        """Jump to the counterpart folio of this stay."""
        self.ensure_one()
        if not self.linked_folio_id:
            raise UserError(_('This folio has no linked folio.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.folio',
            'res_id': self.linked_folio_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_invoice(self):
        """Open the related invoice."""
        self.ensure_one()
        if not self.invoice_id:
            raise UserError(_('No invoice linked to this folio.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


class HotelFolioLine(models.Model):
    _name = 'hotel.folio.line'
    _description = 'Hotel Folio Charge Line'
    _order = 'id'

    folio_id = fields.Many2one(
        'hotel.folio', string='Folio', required=True, ondelete='cascade',
    )
    name = fields.Char('Description', required=True)
    date = fields.Date(
        'Charge Date', required=True, index=True,
        default=fields.Date.context_today,
        help='Business date this charge belongs to (the hotel night for room '
             'charges). Revenue reports group by this date, not create_date.',
    )
    charge_type = fields.Selection([
        ('room', 'Room Charge'),
        ('fnb', 'Food & Beverage'),
        ('service', 'Service / Tour'),
        ('manual', 'Manual Charge'),
    ], string='Charge Type', default='manual', required=True)

    quantity = fields.Float('Quantity', default=1.0)
    amount = fields.Float('Unit Price', digits=(16, 2))
    subtotal = fields.Float('Subtotal', compute='_compute_subtotal', store=True)

    account_id = fields.Many2one(
        'account.account', string='Revenue Account',
        help='GL account for this charge line',
    )

    @api.depends('quantity', 'amount')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.amount
