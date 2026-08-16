# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_RATE_TRIGGER_FIELDS = {
    'base_rate', 'min_stay', 'stop_sell', 'date_from', 'date_to',
    'day_monday', 'day_tuesday', 'day_wednesday', 'day_thursday',
    'day_friday', 'day_saturday', 'day_sunday',
}


class HotelRatePlan(models.Model):
    _inherit = 'hotel.rate.plan'

    def write(self, vals):
        """Override write to trigger rate push on price/restriction changes."""
        result = super().write(vals)
        if not self.env.context.get('skip_channel_sync'):
            if _RATE_TRIGGER_FIELDS & set(vals.keys()):
                self._trigger_rate_push()
        return result

    def _trigger_rate_push(self):
        """Create pending sync logs for rate push to all channels."""
        SyncLog = self.env['channel.sync.log']
        configs = self.env['channel.manager.config'].search([
            ('active', '=', True),
            ('sync_rates', '=', True),
        ])
        for config in configs:
            for plan in self:
                mapping = self.env['channel.rate.plan.mapping'].search([
                    ('config_id', '=', config.id),
                    ('rate_plan_id', '=', plan.id),
                ], limit=1)
                if mapping:
                    SyncLog.create({
                        'config_id': config.id,
                        'direction': 'outbound',
                        'sync_type': 'rate',
                        'room_type_id': plan.room_type_id.id
                        if plan.room_type_id else False,
                        'state': 'pending',
                    })
