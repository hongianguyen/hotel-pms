# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import timedelta


class HotelHousekeepingTask(models.Model):
    _name = 'hotel.housekeeping.task'
    _description = 'Housekeeping Task'
    _inherit = ['mail.thread']
    _order = 'priority desc, create_date'

    name = fields.Char('Task', required=True, default='Room cleaning')
    room_id = fields.Many2one(
        'hotel.room', string='Room', required=True, index=True,
        ondelete='cascade',
    )
    reservation_id = fields.Many2one(
        'hotel.reservation', string='Triggering Reservation',
        ondelete='set null',
        help='Checkout that generated this task, if any.',
    )
    status = fields.Selection([
        ('todo', 'To Do'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], default='todo', required=True, tracking=True, index=True)
    priority = fields.Selection([
        ('0', 'Normal'),
        ('1', 'High'),
    ], default='0', required=True, tracking=True,
        help='High = same-day turnover: another guest arrives today.')
    assigned_to = fields.Many2one(
        'res.users', string='Assigned To', tracking=True,
    )
    sla_minutes = fields.Integer(
        'SLA (minutes)', compute='_compute_sla', store=True,
        help='Target cleaning time, from the room type '
             '(spec: standard 30 min, villa 60 min).',
    )
    deadline = fields.Datetime(
        'SLA Deadline', compute='_compute_sla', store=True,
    )
    completed_at = fields.Datetime('Completed At', readonly=True)
    is_overdue = fields.Boolean(compute='_compute_is_overdue')
    notes = fields.Text('Notes')

    @api.depends('room_id.room_type_id.housekeeping_sla_minutes', 'create_date')
    def _compute_sla(self):
        for task in self:
            minutes = task.room_id.room_type_id.housekeeping_sla_minutes or 30
            task.sla_minutes = minutes
            base = task.create_date or fields.Datetime.now()
            task.deadline = base + timedelta(minutes=minutes)

    def _compute_is_overdue(self):
        now = fields.Datetime.now()
        for task in self:
            task.is_overdue = bool(
                task.status in ('todo', 'in_progress')
                and task.deadline and task.deadline < now
            )

    # ── Workflow ─────────────────────────────────────────────────────────
    def action_start(self):
        self.write({'status': 'in_progress'})
        self.mapped('room_id').action_set_cleaning()

    def action_done(self):
        """Complete the task: stamp times and release the room."""
        for task in self:
            task.write({
                'status': 'done',
                'completed_at': fields.Datetime.now(),
            })
            # Releases the room and stamps room.last_cleaned_at
            task.room_id.action_set_available()

    def action_cancel(self):
        self.write({'status': 'cancelled'})

    # ── Auto-creation hook (spec §9.1) ───────────────────────────────────
    @api.model
    def create_for_checkout(self, reservation):
        """Create a cleaning task when a guest checks out.

        Priority is High when another confirmed reservation for the same
        room arrives the same day (same-day turnover — the closest
        date-level equivalent of the spec's 'next check-in < 3h').
        """
        today = fields.Date.context_today(self)
        next_arrival = self.env['hotel.reservation'].search([
            ('room_id', '=', reservation.room_id.id),
            ('state', '=', 'confirmed'),
            ('checkin_date', '=', today),
        ], limit=1)
        return self.create({
            'name': _('Checkout cleaning — Room %s') % reservation.room_id.name,
            'room_id': reservation.room_id.id,
            'reservation_id': reservation.id,
            'priority': '1' if next_arrival else '0',
        })


class HotelReservationHousekeeping(models.Model):
    """Bridge: auto-create a housekeeping task on every checkout."""
    _inherit = 'hotel.reservation'

    def action_check_out(self):
        res = super().action_check_out()
        Task = self.env['hotel.housekeeping.task'].sudo()
        for rec in self:
            if rec.state == 'checked_out' and rec.room_id:
                Task.create_for_checkout(rec)
        return res
