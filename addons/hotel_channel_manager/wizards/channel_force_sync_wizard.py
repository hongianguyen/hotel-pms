# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ChannelForceSyncWizard(models.TransientModel):
    _name = 'channel.force.sync.wizard'
    _description = 'Force Channel Sync Wizard'

    config_id = fields.Many2one(
        'channel.manager.config', required=True, string='Channel',
    )
    sync_availability = fields.Boolean(default=True, string='Sync Availability')
    sync_rates = fields.Boolean(default=True, string='Sync Rates')
    sync_restrictions = fields.Boolean(default=False, string='Sync Restrictions')

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(vals_list)

    def action_force_sync(self):
        """Create sync log entries for a full sync of this channel."""
        self.ensure_one()
        SyncLog = self.env['channel.sync.log']
        config = self.config_id
        created = 0

        if self.sync_availability:
            for mapping in config.room_mapping_ids:
                SyncLog.create({
                    'config_id': config.id,
                    'direction': 'outbound',
                    'sync_type': 'availability',
                    'room_type_id': mapping.room_type_id.id,
                    'state': 'pending',
                })
                created += 1

        if self.sync_rates:
            for mapping in config.rate_mapping_ids:
                SyncLog.create({
                    'config_id': config.id,
                    'direction': 'outbound',
                    'sync_type': 'rate',
                    'room_type_id': mapping.rate_plan_id.room_type_id.id
                    if mapping.rate_plan_id.room_type_id else False,
                    'state': 'pending',
                })
                created += 1

        if self.sync_restrictions:
            SyncLog.create({
                'config_id': config.id,
                'direction': 'outbound',
                'sync_type': 'restriction',
                'state': 'pending',
            })
            created += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Sync Queued',
                'message': f'{created} sync tasks queued for processing.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
