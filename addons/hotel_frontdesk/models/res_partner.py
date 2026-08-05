# -*- coding: utf-8 -*-
from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_hotel_agency = fields.Boolean(
        'Travel Agency / Corporate Account',
        help='This company sends bookings to the hotel. Invoices for its '
             'bookings are issued to the company, not to the staying guests.',
    )
    hotel_agency_type = fields.Selection([
        ('travel_agent', 'Travel Agent'),
        ('corporate', 'Corporate'),
    ], string='Account Type', default='travel_agent')
    hotel_credit_term = fields.Boolean(
        'Credit Terms',
        help='The hotel extends credit to this account: its bookings can '
             'check in without prepayment and the invoice is payable per the '
             'payment terms set on this partner. Without credit terms, '
             'prepayment is required before check-in.',
    )

    hotel_total_stays = fields.Integer(
        'Total Stays', compute='_compute_hotel_stats',
        help='Number of completed (checked-out) stays.',
    )
    hotel_total_spent = fields.Float(
        'Total Spent', compute='_compute_hotel_stats', digits=(16, 2),
        help='Sum of all folio totals for this guest.',
    )

    def _compute_hotel_stats(self):
        Reservation = self.env['hotel.reservation']
        Folio = self.env['hotel.folio']
        stays = Reservation.read_group(
            [('guest_id', 'in', self.ids), ('state', '=', 'checked_out')],
            ['guest_id'], ['guest_id'],
        )
        stay_map = {g['guest_id'][0]: g['guest_id_count'] for g in stays}
        spent = Folio.read_group(
            [('guest_id', 'in', self.ids)],
            ['guest_id', 'total_amount'], ['guest_id'],
        )
        spent_map = {g['guest_id'][0]: g['total_amount'] for g in spent}
        for partner in self:
            partner.hotel_total_stays = stay_map.get(partner.id, 0)
            partner.hotel_total_spent = spent_map.get(partner.id, 0.0)
