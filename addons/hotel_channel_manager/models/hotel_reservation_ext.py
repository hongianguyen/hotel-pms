# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Fields that trigger availability push when changed on a reservation
_AVAILABILITY_TRIGGER_FIELDS = {
    'state', 'checkin_date', 'checkout_date', 'room_id', 'room_type_id',
}


class HotelReservation(models.Model):
    _inherit = 'hotel.reservation'

    channel_config_id = fields.Many2one(
        'channel.manager.config',
        string='Channel',
        readonly=True,
        copy=False,
        tracking=True,
    )
    channel_booking_id = fields.Char(
        string='Channel Booking ID',
        readonly=True,
        copy=False,
        index=True,
    )
    channel_synced = fields.Boolean(
        default=False,
        string='Synced to Channel',
        readonly=True,
        copy=False,
    )

    def write(self, vals):
        """Override write to trigger channel availability push on relevant changes."""
        result = super().write(vals)
        if not self.env.context.get('skip_channel_sync'):
            if _AVAILABILITY_TRIGGER_FIELDS & set(vals.keys()):
                self._trigger_availability_push()
        return result

    def action_cancel(self):
        """Override cancel to push cancellation + availability to channels."""
        # Capture room types before cancel changes state
        room_types = self.mapped('room_type_id')
        origin_channels = {
            r: r.channel_config_id for r in self if r.channel_config_id
        }
        result = super().action_cancel()

        if not self.env.context.get('skip_channel_sync'):
            SyncLog = self.env['channel.sync.log']
            # Push cancellation to origin channel
            for reservation, config in origin_channels.items():
                if reservation.channel_booking_id:
                    SyncLog.create({
                        'config_id': config.id,
                        'direction': 'outbound',
                        'sync_type': 'cancellation',
                        'reservation_id': reservation.id,
                        'state': 'pending',
                    })
            # Push availability to all channels
            self._trigger_availability_push_for_room_types(room_types)
        return result

    def _trigger_availability_push(self):
        """Create pending sync logs for availability push to all channels."""
        room_types = self.mapped('room_type_id')
        self._trigger_availability_push_for_room_types(room_types)

    def _trigger_availability_push_for_room_types(self, room_types):
        """Push availability for given room types to all active channels."""
        if not room_types:
            return
        SyncLog = self.env['channel.sync.log']
        configs = self.env['channel.manager.config'].search([
            ('active', '=', True),
            ('sync_availability', '=', True),
        ])
        for config in configs:
            for rt in room_types:
                mapping = self.env['channel.room.type.mapping'].search([
                    ('config_id', '=', config.id),
                    ('room_type_id', '=', rt.id),
                ], limit=1)
                if mapping:
                    SyncLog.create({
                        'config_id': config.id,
                        'direction': 'outbound',
                        'sync_type': 'availability',
                        'room_type_id': rt.id,
                        'state': 'pending',
                    })
