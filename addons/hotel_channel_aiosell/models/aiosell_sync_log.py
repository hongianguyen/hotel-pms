# -*- coding: utf-8 -*-
from odoo import fields, models


class AiosellSyncLog(models.Model):
    _name = 'aiosell.sync.log'
    _description = 'Aiosell Sync Log'
    _order = 'create_date desc, id desc'
    _rec_name = 'operation'

    config_id = fields.Many2one(
        'aiosell.config', required=True, ondelete='cascade', index=True,
    )
    direction = fields.Selection([
        ('outbound', 'PMS → Aiosell'),
        ('inbound', 'Aiosell → PMS'),
    ], required=True, index=True)
    operation = fields.Char(required=True)
    endpoint = fields.Char()
    http_status = fields.Integer('HTTP Status')
    state = fields.Selection([
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('error', 'Error'),
        ('refused', 'Refused'),
    ], default='pending', required=True, index=True)
    request_body = fields.Text()
    response_body = fields.Text()
    reservation_id = fields.Many2one('hotel.reservation', ondelete='set null')
    booking_id = fields.Char('OTA Booking ID', index=True)
    note = fields.Char()

    def _gc(self, days=90):
        """Drop logs older than `days`; payload bodies are bulky."""
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        self.search([('create_date', '<', cutoff)]).unlink()
