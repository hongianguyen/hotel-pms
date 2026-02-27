# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class HotelRoomType(models.Model):
    _name = 'hotel.room.type'
    _description = 'Hotel Room Type'
    _order = 'name'
    _inherit = ['mail.thread']

    name = fields.Char('Name', required=True, translate=True, tracking=True)
    capacity = fields.Integer('Capacity (persons)', default=2, required=True)
    base_rate = fields.Float('Base Rate / Night', required=True, digits=(16, 2), tracking=True)
    description = fields.Text('Description', translate=True)
    active = fields.Boolean('Active', default=True)
    color = fields.Integer('Color', default=0)

    revenue_account_id = fields.Many2one(
        'account.account',
        string='Revenue Account',
        help='GL account for room revenue (e.g. 4000 Room Revenue)',
    )

    room_ids = fields.One2many('hotel.room', 'room_type_id', string='Rooms')
    room_count = fields.Integer('Room Count', compute='_compute_room_count', store=True)

    @api.depends('room_ids')
    def _compute_room_count(self):
        for rec in self:
            rec.room_count = len(rec.room_ids)

    _name_uniq = models.Constraint('UNIQUE(name)', 'Room type name must be unique!')
    _base_rate_positive = models.Constraint('CHECK(base_rate >= 0)', 'Base rate cannot be negative!')
    _capacity_positive = models.Constraint('CHECK(capacity > 0)', 'Capacity must be at least 1!')


class HotelRoom(models.Model):
    _name = 'hotel.room'
    _description = 'Hotel Room'
    _inherit = ['mail.thread']
    _rec_name = 'display_name'
    _order = 'floor, name'

    name = fields.Char('Room Number', required=True, tracking=True)
    room_type_id = fields.Many2one(
        'hotel.room.type', string='Room Type', required=True,
        ondelete='restrict', tracking=True,
    )
    base_rate = fields.Float(
        'Rate / Night', related='room_type_id.base_rate', store=True,
    )
    capacity = fields.Integer(
        'Capacity', related='room_type_id.capacity', store=True,
    )
    status = fields.Selection([
        ('available', 'Available'),
        ('occupied', 'Occupied'),
        ('dirty', 'Dirty'),
        ('cleaning', 'Cleaning'),
        ('maintenance', 'Maintenance'),
    ], string='Status', default='available', required=True, tracking=True)

    floor = fields.Integer('Floor', default=1)
    active = fields.Boolean('Active', default=True)
    notes = fields.Text('Internal Notes')
    color = fields.Integer('Color Index', compute='_compute_color', store=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('name', 'room_type_id.name')
    def _compute_display_name(self):
        for room in self:
            type_name = room.room_type_id.name or ''
            room.display_name = f"{room.name} ({type_name})" if type_name else room.name

    @api.depends('status')
    def _compute_color(self):
        color_map = {
            'available': 10,    # green
            'occupied': 1,      # red
            'dirty': 3,         # orange
            'cleaning': 4,      # light blue
            'maintenance': 6,   # dark grey
        }
        for room in self:
            room.color = color_map.get(room.status, 0)

    # ── Status Actions ──────────────────────────────────────────────────
    def action_set_available(self):
        for room in self:
            room._check_no_active_checkin()
        self.write({'status': 'available'})

    def action_set_dirty(self):
        self.write({'status': 'dirty'})

    def action_set_cleaning(self):
        self.write({'status': 'cleaning'})

    def action_set_maintenance(self):
        self.write({'status': 'maintenance'})

    def action_set_occupied(self):
        self.write({'status': 'occupied'})

    def _check_no_active_checkin(self):
        """Prevent marking as available if guest is still checked in."""
        for room in self:
            active_res = self.env['hotel.reservation'].search([
                ('room_id', '=', room.id),
                ('state', '=', 'checked_in'),
            ], limit=1)
            if active_res:
                raise ValidationError(
                    _('Room %s has an active check-in (%s). Check out first.')
                    % (room.name, active_res.reservation_number)
                )

    # ── Availability Helper ─────────────────────────────────────────────
    @api.model
    def get_available_rooms(self, checkin_date, checkout_date, room_type_id=None):
        """Return rooms available in the given date range."""
        domain = [('active', '=', True), ('status', 'not in', ['maintenance'])]
        if room_type_id:
            domain.append(('room_type_id', '=', room_type_id))
        all_rooms = self.search(domain)
        overlapping = self.env['hotel.reservation'].search([
            ('state', 'in', ['confirmed', 'checked_in']),
            ('checkin_date', '<', checkout_date),
            ('checkout_date', '>', checkin_date),
        ])
        booked_ids = overlapping.mapped('room_id').ids
        return all_rooms.filtered(lambda r: r.id not in booked_ids)

    _name_uniq = models.Constraint('UNIQUE(name)', 'Room number must be unique!')
