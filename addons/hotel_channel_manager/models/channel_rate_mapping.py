# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ChannelRatePlanMapping(models.Model):
    _name = 'channel.rate.plan.mapping'
    _description = 'Channel Rate Plan Mapping'

    config_id = fields.Many2one(
        'channel.manager.config', required=True, ondelete='cascade',
    )
    rate_plan_id = fields.Many2one(
        'hotel.rate.plan', required=True, ondelete='restrict',
        string='PMS Rate Plan',
    )
    channel_rate_plan_id = fields.Char(
        required=True, string='Channel Rate Plan ID',
    )
    channel_rate_plan_name = fields.Char(string='Channel Rate Plan Name')

    _mapping_uniq = models.Constraint(
        'UNIQUE(config_id, rate_plan_id)',
        'Each rate plan can only be mapped once per channel!',
    )

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(vals_list)
