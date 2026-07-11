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

    checkin_date = fields.Date('Check-in Date', required=True, tracking=True,
                               index=True)
    checkout_date = fields.Date('Check-out Date', required=True, tracking=True,
                                index=True)
    nights = fields.Integer('Nights', compute='_compute_nights', store=True)

    nightly_rate = fields.Float('Nightly Rate', digits=(16, 2), compute='_compute_nightly_rate', store=True)
    total_amount = fields.Float('Total Amount', digits=(16, 2), compute='_compute_total_amount', store=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('checked_in', 'Checked In'),
        ('checked_out', 'Checked Out'),
        ('no_show', 'No Show'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True,
        index=True)

    folio_id = fields.Many2one('hotel.folio', string='Folio', readonly=True, copy=False)
    group_id = fields.Many2one(
        'hotel.booking.group', string='Group Booking', ondelete='set null',
        index=True, tracking=True, copy=False,
    )
    source_id = fields.Many2one('hotel.booking.source', string='Booking Source', tracking=True)
    payment_required = fields.Boolean(
        'Prepayment Required', tracking=True,
        help='Block check-in until prepayment is marked as received '
             '(e.g. non-refundable OTA rates).',
    )
    prepaid = fields.Boolean(
        'Prepayment Received', tracking=True,
        help='Tick when the required prepayment has been received.',
    )
    send_confirmation = fields.Boolean('Send Confirmation Email', default=True)
    notes = fields.Text('Notes')
    color = fields.Integer('Color', compute='_compute_color')

    adults = fields.Integer('Adults', default=1)
    children = fields.Integer('Children', default=0)

    # ── Pax (guest names staying in this room) ──────────────────────────
    pax_ids = fields.One2many(
        'hotel.reservation.pax', 'reservation_id', string='Guests (Pax)',
        copy=True,
    )
    pax_count = fields.Integer('Pax Count', compute='_compute_pax', store=True)
    pax_names = fields.Char(
        'Pax Names', compute='_compute_pax', store=True,
        help='Comma-separated guest names for lists, folio and dashboards.',
    )

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

    @api.depends('pax_ids.name')
    def _compute_pax(self):
        for rec in self:
            names = [p.name for p in rec.pax_ids if p.name]
            rec.pax_count = len(names)
            rec.pax_names = ', '.join(names)

    @api.depends('nights', 'nightly_rate', 'rate_plan_id',
                 'checkin_date', 'checkout_date')
    def _compute_total_amount(self):
        """Sum per-night rates so the quoted total matches the folio.

        Uses the same per-date rate-plan/season logic as
        hotel.folio._generate_room_charges; falls back to the flat
        nightly_rate for dates the plan does not cover.
        """
        for rec in self:
            if not (rec.checkin_date and rec.checkout_date and rec.nights > 0):
                rec.total_amount = 0.0
                continue
            total = 0.0
            current = rec.checkin_date
            while current < rec.checkout_date:
                day_rate = rec.nightly_rate
                if rec.rate_plan_id:
                    plan_rate = rec.rate_plan_id.get_rate_for_date(current)
                    if plan_rate:
                        day_rate = plan_rate
                total += day_rate
                current += timedelta(days=1)
            rec.total_amount = total

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
            # Bookings inside a group charge to the group's master folio
            if vals.get('group_id') and not vals.get('folio_id'):
                group = self.env['hotel.booking.group'].browse(vals['group_id'])
                if group.master_folio_id:
                    vals['folio_id'] = group.master_folio_id.id
        records = super().create(vals_list)
        # Keep the folio's primary-reservation convention (room/dates display)
        for rec in records:
            if rec.group_id and rec.folio_id and not rec.folio_id.reservation_id:
                rec.folio_id.reservation_id = rec.id
        return records

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
        """Confirmed → Checked In. Create folio (or reuse group folio), set room occupied."""
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('Only confirmed reservations can be checked in.'))
            if rec.payment_required and not rec.prepaid:
                raise UserError(_(
                    'Reservation %s requires prepayment before check-in. '
                    'Mark "Prepayment Received" once payment arrives.'
                ) % rec.reservation_number)
            if rec.room_id.status == 'maintenance':
                raise UserError(_('Room %s is under maintenance.') % rec.room_id.name)
            if rec.room_id.status not in ('available', 'cleaning'):
                raise UserError(
                    _('Room %s is not available (current status: %s).')
                    % (rec.room_id.name, rec.room_id.status)
                )

            if rec.folio_id:
                # Group booking: folio already exists — just add room charges
                rec.folio_id._generate_room_charges(rec)
            else:
                # Single booking: create a new folio.
                # sudo: reception has folio read/write but not create; folio
                # creation is an internal side-effect of check-in, values are
                # fully derived from this reservation.
                folio = self.env['hotel.folio'].sudo().create({
                    'reservation_id': rec.id,
                    'guest_id': rec.guest_id.id,
                })
                folio._generate_room_charges(rec)
                rec.folio_id = folio.id

            rec.state = 'checked_in'
            rec.room_id.action_set_occupied()

    def action_check_out(self):
        """Checked In → Checked Out. Generate invoice (only when last room checks out), room → dirty."""
        for rec in self:
            if rec.state != 'checked_in':
                raise UserError(_('Only checked-in reservations can be checked out.'))
            if not rec.folio_id:
                raise UserError(_('No folio found for this reservation.'))

            # Late checkout: auto-charge each night past the scheduled
            # checkout date at the reservation's nightly rate (spec §16).
            today = fields.Date.context_today(rec)
            extra = today - rec.checkout_date
            if extra.days > 0:
                lines = []
                current = rec.checkout_date
                room_name = rec.room_id.name or 'Room'
                while current < today:
                    lines.append((0, 0, {
                        'name': _('Late checkout — Room %s — %s') % (
                            room_name, current.strftime('%d/%m/%Y')),
                        'charge_type': 'room',
                        'quantity': 1,
                        'amount': rec.nightly_rate,
                        'date': current,
                        'account_id': rec.room_id.room_type_id.revenue_account_id.id or False,
                    }))
                    current += timedelta(days=1)
                rec.folio_id.write({'line_ids': lines})

            rec.write({'state': 'checked_out'})
            rec.room_id.write({'last_used_at': fields.Datetime.now()})
            rec.room_id.action_set_dirty()

            # For group folios: only invoice when the last room checks out
            other_still_in = self.env['hotel.reservation'].search([
                ('folio_id', '=', rec.folio_id.id),
                ('id', '!=', rec.id),
                ('state', '=', 'checked_in'),
            ], limit=1)
            if not other_still_in and rec.folio_id.payment_state == 'open':
                rec.folio_id.action_create_invoice()

    def action_cancel(self):
        """Cancel reservation. Free room if it was confirmed."""
        for rec in self:
            if rec.state == 'checked_out':
                raise UserError(_('Cannot cancel a checked-out reservation.'))
            if rec.state == 'checked_in':
                raise UserError(_(
                    'Reservation %s is checked in. Check the guest out '
                    '(which settles the folio) instead of cancelling, '
                    'otherwise the folio charges would be left dangling.'
                ) % rec.reservation_number)
            old_state = rec.state
            rec.state = 'cancelled'
            if old_state == 'confirmed' and rec.room_id:
                if rec.room_id.status == 'occupied':
                    rec.room_id.action_set_dirty()

    def action_reset_draft(self):
        """Reset cancelled / no-show back to draft."""
        for rec in self:
            if rec.state not in ('cancelled', 'no_show'):
                raise UserError(_('Only cancelled or no-show reservations can be reset to draft.'))
            rec.state = 'draft'

    # ── Write guard (spec §3.1: cannot modify CHECKED_OUT) ──────────────
    _PROTECTED_AFTER_CHECKOUT = (
        'room_id', 'room_type_id', 'checkin_date', 'checkout_date',
        'nightly_rate', 'rate_plan_id', 'guest_id',
    )

    def write(self, vals):
        protected = set(vals) & set(self._PROTECTED_AFTER_CHECKOUT)
        if protected and not self.env.context.get('bypass_checkout_guard'):
            locked = self.filtered(lambda r: r.state == 'checked_out')
            if locked:
                raise UserError(_(
                    'Reservation(s) %s are checked out and can no longer be '
                    'modified (fields: %s).'
                ) % (', '.join(locked.mapped('reservation_number')),
                     ', '.join(sorted(protected))))
        return super().write(vals)

    # ── No-show cron (spec §6.1) ─────────────────────────────────────────
    @api.model
    def _cron_mark_no_shows(self):
        """Mark confirmed reservations as NO_SHOW after the grace period.

        Grace = end of the check-in day in the company timezone: a guest
        who has not checked in by midnight after their arrival date is a
        no-show. Runs hourly; idempotent.
        """
        today = fields.Date.context_today(self)
        stale = self.search([
            ('state', '=', 'confirmed'),
            ('checkin_date', '<', today),
        ])
        for rec in stale:
            rec.state = 'no_show'
            rec.message_post(body=_(
                'Automatically marked as No Show: guest did not check in '
                'by end of %s.') % rec.checkin_date)
        return len(stale)

    # ── Pre-arrival reminder cron (spec §6.3) ───────────────────────────
    @api.model
    def _cron_send_prearrival_reminders(self):
        """Email tomorrow's confirmed arrivals a pre-arrival reminder."""
        template = self.env.ref(
            'hotel_frontdesk.mail_template_prearrival_reminder',
            raise_if_not_found=False,
        )
        if not template:
            return 0
        tomorrow = fields.Date.context_today(self) + timedelta(days=1)
        arrivals = self.search([
            ('state', '=', 'confirmed'),
            ('checkin_date', '=', tomorrow),
        ])
        sent = 0
        for rec in arrivals:
            if rec.guest_id.email:
                template.send_mail(rec.id)
                sent += 1
        return sent

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


class HotelReservationPax(models.Model):
    """One line per guest name staying in the room of a reservation.

    Since each reservation maps to exactly one room, this gives a
    room-by-room record of every client name (pax) in the property,
    including for group bookings where each room is its own reservation.
    """
    _name = 'hotel.reservation.pax'
    _description = 'Reservation Guest (Pax)'
    _order = 'sequence, id'

    reservation_id = fields.Many2one(
        'hotel.reservation', string='Reservation',
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    name = fields.Char('Guest Name', required=True)
    pax_type = fields.Selection([
        ('adult', 'Adult'),
        ('child', 'Child'),
    ], string='Type', default='adult', required=True)
    id_number = fields.Char('ID / Passport #')
    nationality_id = fields.Many2one('res.country', string='Nationality')
    note = fields.Char('Note')

    room_id = fields.Many2one(
        related='reservation_id.room_id', string='Room', store=True,
    )
    checkin_date = fields.Date(
        related='reservation_id.checkin_date', store=True,
    )
    checkout_date = fields.Date(
        related='reservation_id.checkout_date', store=True,
    )
