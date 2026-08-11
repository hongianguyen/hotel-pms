# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class HotelBookingGroup(models.Model):
    _name = 'hotel.booking.group'
    _description = 'Hotel Group Booking'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'checkin_date desc, id desc'
    _rec_name = 'name'

    name = fields.Char('Group Booking #', readonly=True, copy=False, default='New')
    guest_id = fields.Many2one(
        'res.partner', string='Group Leader', required=True, tracking=True,
        domain="[('is_company', '=', False)]",
    )
    checkin_date = fields.Date('Check-in Date', required=True, tracking=True)
    checkout_date = fields.Date('Check-out Date', required=True, tracking=True)
    rate_plan_id = fields.Many2one('hotel.rate.plan', string='Rate Plan', tracking=True)
    source_id = fields.Many2one('hotel.booking.source', string='Booking Source', tracking=True)

    # ── Travel agent / corporate account billing ────────────────────────
    agency_id = fields.Many2one(
        'res.partner', string='Agency / Company', tracking=True,
        domain="[('is_hotel_agency', '=', True)]",
        help='Travel agency or corporate account that sent this group '
             'booking. The master folio is invoiced to this company and '
             'confirmation emails go to the booker.',
    )
    booker_id = fields.Many2one(
        'res.partner', string='Booker', tracking=True,
        domain="['|', ('id', '=', agency_id), ('parent_id', '=', agency_id)]",
        help='Contact at the agency/company who made the booking. '
             'Confirmation emails are sent to this person.',
    )
    booker_email = fields.Char(
        'Booker Email', compute='_compute_booker_email',
    )
    agency_credit_term = fields.Boolean(
        related='agency_id.hotel_credit_term', string='Credit Terms',
    )
    send_confirmation = fields.Boolean(
        'Send Confirmation Email', default=True,
        help='Send one group confirmation email to the group leader on '
             'confirm (individual per-room emails are skipped).',
    )
    notes = fields.Text('Notes')

    reservation_ids = fields.One2many(
        'hotel.reservation', 'group_id', string='Bookings',
    )
    master_folio_id = fields.Many2one(
        'hotel.folio', string='Master Folio', readonly=True, copy=False,
    )
    room_count = fields.Integer('Rooms', compute='_compute_room_count', store=True)
    total_amount = fields.Float(
        'Total Amount', compute='_compute_total_amount', store=True, digits=(16, 2),
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('checked_in', 'Checked In'),
        ('checked_out', 'Checked Out'),
        ('cancelled', 'Cancelled'),
    ], string='Status', compute='_compute_state', store=True, tracking=True)

    @api.depends('booker_id.email', 'agency_id.email')
    def _compute_booker_email(self):
        for group in self:
            group.booker_email = (group.booker_id.email
                                  or group.agency_id.email or False)

    @api.onchange('agency_id')
    def _onchange_agency_id(self):
        if self.agency_id:
            if (self.booker_id != self.agency_id
                    and self.booker_id.parent_id != self.agency_id):
                self.booker_id = self.agency_id
        else:
            self.booker_id = False

    @api.depends('reservation_ids')
    def _compute_room_count(self):
        for group in self:
            group.room_count = len(group.reservation_ids.filtered(
                lambda r: r.state not in ('cancelled', 'no_show')))

    @api.depends('reservation_ids.total_amount', 'reservation_ids.state')
    def _compute_total_amount(self):
        for group in self:
            group.total_amount = sum(group.reservation_ids.filtered(
                lambda r: r.state not in ('cancelled', 'no_show')
            ).mapped('total_amount'))

    @api.depends('reservation_ids.state')
    def _compute_state(self):
        """Group state mirrors the child reservations (same lifecycle as a
        normal booking): cancelled/no-show children are ignored unless the
        whole group is cancelled."""
        for group in self:
            states = group.reservation_ids.mapped('state')
            active = [s for s in states if s not in ('cancelled', 'no_show')]
            if not states:
                group.state = 'draft'
            elif not active:
                group.state = 'cancelled'
            elif any(s == 'checked_in' for s in active):
                group.state = 'checked_in'
            elif all(s == 'checked_out' for s in active):
                group.state = 'checked_out'
            elif any(s == 'draft' for s in active):
                group.state = 'draft'
            else:
                group.state = 'confirmed'

    # Belt & braces: same rule at DB level so no code path can bypass it
    _dates_order = models.Constraint(
        'CHECK(checkout_date > checkin_date)',
        'Check-in date must always be before check-out date!',
    )

    @api.constrains('checkin_date', 'checkout_date')
    def _check_dates(self):
        for group in self:
            if group.checkin_date and group.checkout_date:
                if group.checkout_date <= group.checkin_date:
                    raise ValidationError(_('Check-in date must always be before check-out date.'))

    # ── CRUD ──────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'hotel.booking.group') or 'New'
        groups = super().create(vals_list)
        # Every group booking owns a master folio from the start.
        # sudo: reception lacks folio create rights; see action_check_in.
        for group in groups:
            if not group.master_folio_id:
                group.master_folio_id = self.env['hotel.folio'].sudo().create({
                    'guest_id': group.guest_id.id,
                    'group_id': group.id,
                    'agency_id': group.agency_id.id,
                    # With an agency on the booking the master folio is the
                    # company folio; each room then opens its own guest folio
                    # for incidentals at check-in.
                    'folio_type': 'company' if group.agency_id else 'guest',
                })
        return groups

    def write(self, vals):
        res = super().write(vals)
        # Amend like a normal booking: date changes propagate to child
        # bookings that are not yet in-house / departed.
        date_vals = {k: vals[k] for k in ('checkin_date', 'checkout_date') if k in vals}
        if date_vals and not self.env.context.get('skip_group_propagation'):
            for group in self:
                amendable = group.reservation_ids.filtered(
                    lambda r: r.state in ('draft', 'confirmed'))
                if amendable:
                    amendable.write(date_vals)
        if 'guest_id' in vals:
            for group in self:
                if group.master_folio_id:
                    group.master_folio_id.guest_id = group.guest_id
        if 'agency_id' in vals or 'booker_id' in vals:
            # Billing follows the group: master folio invoices the agency,
            # child bookings mirror it while still amendable.
            for group in self:
                if 'agency_id' in vals and group.master_folio_id:
                    group.master_folio_id.sudo().write({
                        'agency_id': group.agency_id.id,
                        'folio_type': 'company' if group.agency_id else 'guest',
                    })
                amendable = group.reservation_ids.filtered(
                    lambda r: r.state in ('draft', 'confirmed'))
                if amendable:
                    amendable.write({
                        k: vals[k] for k in ('agency_id', 'booker_id')
                        if k in vals})
        return res

    def unlink(self):
        if self.reservation_ids.filtered(lambda r: r.state not in ('draft', 'cancelled')):
            raise UserError(_(
                'Cannot delete a group booking with confirmed or in-house '
                'bookings. Cancel it instead.'))
        return super().unlink()

    # ── Workflow (same actions as a normal booking, cascaded) ────────────

    def action_confirm(self):
        for group in self:
            todo = group.reservation_ids.filtered(lambda r: r.state == 'draft')
            if not todo:
                raise UserError(_('No draft bookings to confirm in this group.'))
            # One group-level confirmation email instead of one per room
            todo.with_context(skip_confirmation_email=True).action_confirm()
            if group.send_confirmation:
                group._send_confirmation_email()

    def _get_confirmation_template(self):
        """Confirmation template + recipient email for this group.

        Corporate/agency groups notify the booker at the sending company;
        direct groups notify the group leader.
        """
        self.ensure_one()
        if self.agency_id:
            return (
                self.env.ref(
                    'hotel_frontdesk.mail_template_group_booking_confirmation_corporate',
                    raise_if_not_found=False),
                self.booker_email,
            )
        return (
            self.env.ref(
                'hotel_frontdesk.mail_template_group_booking_confirmation',
                raise_if_not_found=False),
            self.guest_id.email,
        )

    def _send_confirmation_email(self):
        self.ensure_one()
        template, recipient = self._get_confirmation_template()
        if template and recipient:
            template.send_mail(self.id, force_send=True)

    def action_send_confirmation_email(self):
        for group in self:
            template, recipient = group._get_confirmation_template()
            if not recipient:
                if group.agency_id:
                    raise UserError(_(
                        'No email address set on the booker or agency %s.'
                    ) % group.agency_id.name)
                raise UserError(_('Group leader %s has no email address.')
                                % group.guest_id.name)
            group._send_confirmation_email()

    def action_check_in(self):
        for group in self:
            todo = group.reservation_ids.filtered(lambda r: r.state == 'confirmed')
            if not todo:
                raise UserError(_('No confirmed bookings to check in.'))
            todo.action_check_in()

    def action_check_out(self):
        for group in self:
            todo = group.reservation_ids.filtered(lambda r: r.state == 'checked_in')
            if not todo:
                raise UserError(_('No checked-in bookings to check out.'))
            todo.action_check_out()

    def action_cancel(self):
        for group in self:
            in_house = group.reservation_ids.filtered(lambda r: r.state == 'checked_in')
            if in_house:
                raise UserError(_(
                    'Group has checked-in rooms (%s). Check them out first, '
                    'then cancel the remaining bookings.'
                ) % ', '.join(in_house.mapped('reservation_number')))
            todo = group.reservation_ids.filtered(
                lambda r: r.state in ('draft', 'confirmed'))
            if not todo:
                raise UserError(_('Nothing to cancel in this group.'))
            todo.action_cancel()

    def action_exit(self):
        """Leave the group booking screen: back to the Reception Dashboard
        (falls back to the group bookings list if reporting is not installed)."""
        try:
            return self.env['ir.actions.actions']._for_xml_id(
                'hotel_reporting.action_reception_dashboard')
        except ValueError:
            return self.env['ir.actions.actions']._for_xml_id(
                'hotel_frontdesk.action_hotel_booking_group')

    def action_view_master_folio(self):
        self.ensure_one()
        if not self.master_folio_id:
            raise UserError(_('No master folio linked to this group booking.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.folio',
            'res_id': self.master_folio_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
