# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta


class HotelReservation(models.Model):
    _name = 'hotel.reservation'
    _description = 'Hotel Reservation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'checkin_date desc, id desc'
    _rec_name = 'reservation_number'

    reservation_number = fields.Char(
        'Reservation #', readonly=True, copy=False, default='New',
    )
    guest_id = fields.Many2one(
        'res.partner', string='Guest', required=True, tracking=True,
        domain="[('is_company', '=', False)]",
    )
    guest_phone = fields.Char(related='guest_id.phone', string='Phone')
    guest_email = fields.Char(related='guest_id.email', string='Email')

    room_type_id = fields.Many2one(
        'hotel.room.type', string='Room Type', tracking=True,
    )
    room_id = fields.Many2one(
        'hotel.room', string='Room', tracking=True,
        domain="[('room_type_id', '=', room_type_id), ('active', '=', True)]",
    )
    rate_plan_id = fields.Many2one(
        'hotel.rate.plan', string='Rate Plan', tracking=True,
    )

    checkin_date = fields.Date('Check-in Date', required=True, tracking=True)
    checkout_date = fields.Date('Check-out Date', required=True, tracking=True)
    nights = fields.Integer('Nights', compute='_compute_nights', store=True)

    nightly_rate = fields.Float('Nightly Rate', digits=(16, 2), compute='_compute_nightly_rate', store=True)
    total_amount = fields.Float('Total Amount', digits=(16, 2), compute='_compute_total_amount', store=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('checked_in', 'Checked In'),
        ('checked_out', 'Checked Out'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)

    folio_id = fields.Many2one('hotel.folio', string='Folio', readonly=True, copy=False)
    source_id = fields.Many2one('hotel.booking.source', string='Booking Source', tracking=True)
    send_confirmation = fields.Boolean('Send Confirmation Email', default=True)
    notes = fields.Text('Notes')
    color = fields.Integer('Color', compute='_compute_color')

    adults = fields.Integer('Adults', default=1)
    children = fields.Integer('Children', default=0)

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
    )

    # ── Computed Fields ─────────────────────────────────────────────────

    @api.depends('checkin_date', 'checkout_date')
    def _compute_nights(self):
        for rec in self:
            if rec.checkin_date and rec.checkout_date:
                delta = rec.checkout_date - rec.checkin_date
                rec.nights = max(delta.days, 0)
            else:
                rec.nights = 0

    @api.depends('rate_plan_id', 'room_id', 'room_type_id')
    def _compute_nightly_rate(self):
        for rec in self:
            if rec.rate_plan_id and rec.rate_plan_id.base_rate:
                rec.nightly_rate = rec.rate_plan_id.base_rate
            elif rec.room_id:
                rec.nightly_rate = rec.room_id.base_rate
            elif rec.room_type_id:
                rec.nightly_rate = rec.room_type_id.base_rate
            else:
                rec.nightly_rate = 0.0

    @api.depends('nights', 'nightly_rate')
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = rec.nights * rec.nightly_rate

    @api.depends('state')
    def _compute_color(self):
        color_map = {
            'draft': 0,
            'confirmed': 4,     # light blue
            'checked_in': 10,   # green
            'checked_out': 1,   # red/grey
            'cancelled': 6,     # dark
        }
        for rec in self:
            rec.color = color_map.get(rec.state, 0)

    # ── Constraints ──────────────────────────────────────────────────────

    @api.constrains('checkin_date', 'checkout_date')
    def _check_dates(self):
        for rec in self:
            if rec.checkin_date and rec.checkout_date:
                if rec.checkout_date <= rec.checkin_date:
                    raise ValidationError(_('Check-out date must be after check-in date.'))

    @api.constrains('room_id', 'checkin_date', 'checkout_date', 'state')
    def _check_room_availability(self):
        for rec in self:
            if rec.room_id and rec.state in ('confirmed', 'checked_in'):
                overlap = self.search([
                    ('id', '!=', rec.id),
                    ('room_id', '=', rec.room_id.id),
                    ('state', 'in', ['confirmed', 'checked_in']),
                    ('checkin_date', '<', rec.checkout_date),
                    ('checkout_date', '>', rec.checkin_date),
                ], limit=1)
                if overlap:
                    raise ValidationError(
                        _('Room %s is already booked from %s to %s (Reservation %s).')
                        % (rec.room_id.name, overlap.checkin_date,
                           overlap.checkout_date, overlap.reservation_number)
                    )

    # ── CRUD ──────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reservation_number', 'New') == 'New':
                vals['reservation_number'] = self.env['ir.sequence'].next_by_code(
                    'hotel.reservation') or 'New'
        return super().create(vals_list)

    # ── Workflow Buttons ─────────────────────────────────────────────────

    def action_confirm(self):
        """Draft → Confirmed. Send confirmation email."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft reservations can be confirmed.'))
            if not rec.room_id:
                raise UserError(_('Please assign a room before confirming.'))
            rec.state = 'confirmed'
            if rec.send_confirmation:
                template = self.env.ref(
                    'hotel_frontdesk.mail_template_reservation_confirmation',
                    raise_if_not_found=False,
                )
                if template and rec.guest_id.email:
                    template.send_mail(rec.id, force_send=True)

    def action_check_in(self):
        """Confirmed → Checked In. Create folio, set room occupied."""
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('Only confirmed reservations can be checked in.'))
            if rec.room_id.status == 'maintenance':
                raise UserError(_('Room %s is under maintenance.') % rec.room_id.name)
            if rec.room_id.status not in ('available', 'cleaning'):
                raise UserError(
                    _('Room %s is not available (current status: %s).')
                    % (rec.room_id.name, rec.room_id.status)
                )

            # Create folio
            folio = self.env['hotel.folio'].create({
                'reservation_id': rec.id,
                'guest_id': rec.guest_id.id,
            })
            # Add room charge lines
            folio._generate_room_charges()

            rec.write({
                'state': 'checked_in',
                'folio_id': folio.id,
            })
            rec.room_id.action_set_occupied()

    def action_check_out(self):
        """Checked In → Checked Out. Generate invoice, room → dirty."""
        for rec in self:
            if rec.state != 'checked_in':
                raise UserError(_('Only checked-in reservations can be checked out.'))
            if not rec.folio_id:
                raise UserError(_('No folio found for this reservation.'))

            # Generate invoice from folio
            rec.folio_id.action_create_invoice()

            rec.write({'state': 'checked_out'})
            rec.room_id.action_set_dirty()

    def action_cancel(self):
        """Cancel reservation. Free room if was confirmed/checked_in."""
        for rec in self:
            if rec.state in ('checked_out',):
                raise UserError(_('Cannot cancel a checked-out reservation.'))
            old_state = rec.state
            rec.state = 'cancelled'
            if old_state in ('confirmed', 'checked_in') and rec.room_id:
                if rec.room_id.status == 'occupied':
                    rec.room_id.action_set_dirty()

    def action_reset_draft(self):
        """Reset cancelled back to draft."""
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('Only cancelled reservations can be reset to draft.'))
            rec.state = 'draft'

    def action_send_confirmation_email(self):
        """Open custom email wizard pre-filled with confirmation template for preview/edit before sending."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Confirmation Email'),
            'res_model': 'hotel.reservation.email.wizard',
            'views': [(False, 'form')],
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_reservation_id': self.id},
        }

    def action_edit_confirmation_template(self):
        """Navigate to the confirmation email template for customization."""
        self.ensure_one()
        template = self.env.ref(
            'hotel_frontdesk.mail_template_reservation_confirmation',
            raise_if_not_found=False,
        )
        if not template:
            raise UserError(_('Confirmation email template not found.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mail.template',
            'res_id': template.id,
            'views': [(False, 'form')],
            'view_mode': 'form',
            'target': 'current',
        }
