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
    reservation_id = fields.Many2one(
        'hotel.reservation', string='Primary Reservation',
        ondelete='set null',
    )
    # All reservations sharing this folio (single or group)
    reservation_ids = fields.One2many(
        'hotel.reservation', 'folio_id', string='Reservations',
    )
    is_group = fields.Boolean('Group Folio', compute='_compute_is_group', store=True)
    guest_id = fields.Many2one('res.partner', string='Guest', required=True)
    room_id = fields.Many2one(
        'hotel.room', related='reservation_id.room_id',
        string='Room', store=True,
    )
    checkin_date = fields.Date(related='reservation_id.checkin_date', store=True)
    checkout_date = fields.Date(related='reservation_id.checkout_date', store=True)

    line_ids = fields.One2many('hotel.folio.line', 'folio_id', string='Charges')
    total_amount = fields.Float(
        'Total Amount', compute='_compute_total', store=True, digits=(16, 2),
    )

    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True, copy=False)
    payment_state = fields.Selection([
        ('open', 'Open'),
        ('invoiced', 'Invoiced'),
        ('paid', 'Paid'),
    ], string='Payment Status', default='open', tracking=True)

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
    )

    @api.depends('reservation_ids')
    def _compute_is_group(self):
        for folio in self:
            folio.is_group = len(folio.reservation_ids) > 1

    @api.depends('line_ids.subtotal')
    def _compute_total(self):
        for folio in self:
            folio.total_amount = sum(folio.line_ids.mapped('subtotal'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('hotel.folio') or 'New'
        return super().create(vals_list)

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

        lines = []
        while current < res.checkout_date:
            # Check rate plan for per-day rate if available
            day_rate = rate
            if res.rate_plan_id:
                plan_rate = res.rate_plan_id.get_rate_for_date(current)
                if plan_rate:
                    day_rate = plan_rate

            lines.append((0, 0, {
                'name': _('Room %s — %s') % (room_name, current.strftime('%d/%m/%Y')),
                'charge_type': 'room',
                'quantity': 1,
                'amount': day_rate,
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

        journal = self.env['account.journal'].search([
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

        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.guest_id.id,
            'journal_id': journal.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': invoice_lines,
            'ref': self.name,
        })

        self.write({
            'invoice_id': invoice.id,
            'payment_state': 'invoiced',
        })
        return invoice

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
