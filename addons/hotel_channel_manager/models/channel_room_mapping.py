# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ChannelRoomTypeMapping(models.Model):
    _name = 'channel.room.type.mapping'
    _description = 'Channel Room Type Mapping'

    config_id = fields.Many2one(
        'channel.manager.config', required=True, ondelete='cascade',
    )
    room_type_id = fields.Many2one(
        'hotel.room.type', required=True, ondelete='restrict',
        string='PMS Room Type',
    )
    channel_room_type_id = fields.Char(
        required=True, string='Channel Room Type ID',
    )
    channel_room_type_name = fields.Char(string='Channel Room Type Name')
    max_allotment = fields.Integer(
        default=0,
        string='Max Allotment',
        help='Maximum rooms to sell on this channel (0 = all available).',
    )

    _mapping_uniq = models.Constraint(
        'UNIQUE(config_id, room_type_id)',
        'Each room type can only be mapped once per channel!',
    )

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(vals_list)
