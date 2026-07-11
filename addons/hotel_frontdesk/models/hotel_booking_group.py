# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


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

    @api.constrains('checkin_date', 'checkout_date')
    def _check_dates(self):
        for group in self:
            if group.checkin_date and group.checkout_date:
                if group.checkout_date <= group.checkin_date:
                    raise UserError(_('Check-out date must be after check-in date.'))

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
            todo.action_confirm()

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
