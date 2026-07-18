# -*- coding: utf-8 -*-
import random

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class HotelGroupBookingWizard(models.TransientModel):
    _name = 'hotel.group.booking.wizard'
    _description = 'Group Booking Wizard'

    room_type_id = fields.Many2one('hotel.room.type', string='Room Type', required=True)
    is_roh = fields.Boolean(related='room_type_id.is_roh')
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

    def _room_type_domain(self):
        """ROH draws from every physical room type; normal types only
        from their own rooms."""
        if self.room_type_id.is_roh:
            return [('room_type_id.is_roh', '=', False)]
        return [('room_type_id', '=', self.room_type_id.id)]

    def _get_available_rooms(self):
        booked_ids = self.env['hotel.reservation'].search([
            ('state', 'in', ['confirmed', 'checked_in']),
            ('checkin_date', '<', self.checkout_date),
            ('checkout_date', '>', self.checkin_date),
        ]).mapped('room_id.id')

        return self.env['hotel.room'].search(self._room_type_domain() + [
            ('active', '=', True),
            ('status', 'not in', ['maintenance']),
            ('id', 'not in', booked_ids),
        ])

    def action_create_group_booking(self):
        self.ensure_one()
        # Row-lock all candidate rooms of this type so two concurrent group
        # bookings cannot both read the same "available" set and double-book.
        # The lock is held until this transaction commits/rolls back.
        candidate_ids = self.env['hotel.room'].search(
            self._room_type_domain() + [('active', '=', True)]
        ).ids
        if candidate_ids:
            self.env.cr.execute(
                "SELECT id FROM hotel_room WHERE id IN %s FOR UPDATE",
                [tuple(candidate_ids)],
            )

        available = self._get_available_rooms()
        if len(available) < self.num_rooms:
            raise UserError(
                _('Only %d room(s) available of type "%s" for the selected dates. Requested: %d.')
                % (len(available), self.room_type_id.name, self.num_rooms)
            )

        if self.room_type_id.is_roh:
            # ROH: rooms are assigned at random across all room types
            selected_ids = random.sample(available.ids, self.num_rooms)
        else:
            # Deterministic pick: first N in floor/name order keeps group rooms
            # adjacent where possible (available is already ordered by _order).
            selected_ids = available.ids[:self.num_rooms]

        # Create the group booking (it auto-creates its master folio).
        group = self.env['hotel.booking.group'].create({
            'guest_id': self.guest_id.id,
            'checkin_date': self.checkin_date,
            'checkout_date': self.checkout_date,
            'rate_plan_id': self.rate_plan_id.id if self.rate_plan_id else False,
            'source_id': self.source_id.id if self.source_id else False,
            'notes': self.notes or '',
        })

        # Create N bookings inside the group; each links to the master folio
        # automatically via hotel.reservation.create().
        for room_id in selected_ids:
            self.env['hotel.reservation'].create({
                'guest_id': self.guest_id.id,
                'room_id': room_id,
                'room_type_id': self.room_type_id.id,
                'checkin_date': self.checkin_date,
                'checkout_date': self.checkout_date,
                'rate_plan_id': self.rate_plan_id.id if self.rate_plan_id else False,
                'source_id': self.source_id.id if self.source_id else False,
                'notes': self.notes or '',
                'state': 'draft',
                'group_id': group.id,
            })

        # Open the group booking — book / cancel / amend from here
        return {
            'type': 'ir.actions.act_window',
            'name': _('Group Booking — %d Rooms') % self.num_rooms,
            'res_model': 'hotel.booking.group',
            'res_id': group.id,
            'view_mode': 'form',
            'target': 'current',
        }
