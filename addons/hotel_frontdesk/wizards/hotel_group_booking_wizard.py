# -*- coding: utf-8 -*-
import random
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class HotelGroupBookingWizard(models.TransientModel):
    _name = 'hotel.group.booking.wizard'
    _description = 'Group Booking Wizard'

    room_type_id = fields.Many2one('hotel.room.type', string='Room Type', required=True)
    num_rooms = fields.Integer('Number of Rooms', default=1, required=True)
    checkin_date = fields.Date('Check-in Date', required=True)
    checkout_date = fields.Date('Check-out Date', required=True)
    guest_id = fields.Many2one(
        'res.partner', string='Primary Guest', required=True,
        domain="[('is_company', '=', False)]",
    )
    rate_plan_id = fields.Many2one('hotel.rate.plan', string='Rate Plan')
    source_id = fields.Many2one('hotel.booking.source', string='Booking Source')
    notes = fields.Text('Notes')
    available_count = fields.Integer(
        string='Available Rooms', compute='_compute_available_count',
    )

    @api.depends('room_type_id', 'checkin_date', 'checkout_date')
    def _compute_available_count(self):
        for rec in self:
            if rec.room_type_id and rec.checkin_date and rec.checkout_date:
                rec.available_count = len(rec._get_available_rooms())
            else:
                rec.available_count = 0

    @api.constrains('checkin_date', 'checkout_date')
    def _check_dates(self):
        for rec in self:
            if rec.checkin_date and rec.checkout_date:
                if rec.checkout_date <= rec.checkin_date:
                    raise ValidationError(_('Check-out date must be after check-in date.'))

    @api.constrains('num_rooms')
    def _check_num_rooms(self):
        for rec in self:
            if rec.num_rooms < 1:
                raise ValidationError(_('Number of rooms must be at least 1.'))

    def _get_available_rooms(self):
        booked_ids = self.env['hotel.reservation'].search([
            ('state', 'in', ['confirmed', 'checked_in']),
            ('checkin_date', '<', self.checkout_date),
            ('checkout_date', '>', self.checkin_date),
        ]).mapped('room_id.id')

        return self.env['hotel.room'].search([
            ('room_type_id', '=', self.room_type_id.id),
            ('active', '=', True),
            ('status', 'not in', ['maintenance']),
            ('id', 'not in', booked_ids),
        ])

    def action_create_group_booking(self):
        self.ensure_one()
        available = self._get_available_rooms()
        if len(available) < self.num_rooms:
            raise UserError(
                _('Only %d room(s) available of type "%s" for the selected dates. Requested: %d.')
                % (len(available), self.room_type_id.name, self.num_rooms)
            )

        selected_ids = random.sample(available.ids, self.num_rooms)
        created = self.env['hotel.reservation']
        for room_id in selected_ids:
            res = self.env['hotel.reservation'].create({
                'guest_id': self.guest_id.id,
                'room_id': room_id,
                'room_type_id': self.room_type_id.id,
                'checkin_date': self.checkin_date,
                'checkout_date': self.checkout_date,
                'rate_plan_id': self.rate_plan_id.id if self.rate_plan_id else False,
                'source_id': self.source_id.id if self.source_id else False,
                'notes': self.notes or '',
                'state': 'confirmed',
            })
            created |= res

        return {
            'type': 'ir.actions.act_window',
            'name': _('Group Booking — %d Reservations') % self.num_rooms,
            'res_model': 'hotel.reservation',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created.ids)],
            'target': 'current',
        }
