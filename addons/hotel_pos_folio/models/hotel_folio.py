# -*- coding: utf-8 -*-
from odoo import models, fields, api


class HotelFolio(models.Model):
    _inherit = 'hotel.folio'

    pos_order_ids = fields.One2many(
        'pos.order', 'hotel_folio_id', string='POS Orders', readonly=True,
    )
    pos_order_count = fields.Integer(
        'Restaurant Orders', compute='_compute_pos_order_count',
    )

    @api.depends('pos_order_ids')
    def _compute_pos_order_count(self):
        for folio in self:
            folio.pos_order_count = len(folio.pos_order_ids)

    def action_view_pos_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Restaurant Orders',
            'res_model': 'pos.order',
            'view_mode': 'list,form',
            'domain': [('hotel_folio_id', '=', self.id)],
        }


class HotelFolioLine(models.Model):
    _inherit = 'hotel.folio.line'

    pos_order_id = fields.Many2one(
        'pos.order', string='POS Order', readonly=True, copy=False,
        ondelete='set null',
        help='Restaurant order this charge came from.',
    )
