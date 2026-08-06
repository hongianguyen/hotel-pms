# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    hotel_folio_id = fields.Many2one(
        'hotel.folio', string='Charged to Folio', readonly=True, copy=False,
        help='Folio this order was charged to via a "Charge to Room" payment.',
    )
    hotel_folio_line_id = fields.Many2one(
        'hotel.folio.line', string='Folio Charge Line', readonly=True, copy=False,
        ondelete='set null',
    )

    # States in which the order is settled and the charge should exist.
    _HOTEL_POSTABLE_STATES = ('paid', 'done', 'invoiced')

    @api.model
    def _process_order(self, order, existing_order):
        order_id = super()._process_order(order, existing_order)
        if order_id:
            self.browse(order_id)._post_hotel_folio_charge()
        return order_id

    def _hotel_folio_payments(self):
        """Payments on this order made with a Charge to Room method."""
        self.ensure_one()
        return self.payment_ids.filtered(
            lambda p: p.payment_method_id.is_hotel_folio
        )

    def _post_hotel_folio_charge(self):
        """Post an F&B line onto the guest's folio for room-charged payments.

        Amount posted is the payment total, i.e. tax inclusive. POS books the
        revenue and tax at session close and debits the clearing account with
        that same gross figure; the folio line carries the clearing account so
        the check-out invoice credits it back to zero.
        """
        for order in self:
            payments = order._hotel_folio_payments()
            if not payments:
                continue
            if order.state not in order._HOTEL_POSTABLE_STATES:
                continue
            if order.hotel_folio_line_id:
                continue  # already charged — sync can replay the same order

            partner = order.partner_id
            if not partner:
                raise UserError(_(
                    'Order %s is being charged to a room but has no customer. '
                    'Select the in-house guest before paying with "Charge to Room".'
                ) % (order.pos_reference or order.name))

            reservation, folio = partner._hotel_open_folio()
            if not folio:
                raise UserError(_(
                    'Cannot charge order %(order)s to the room: %(guest)s is not '
                    'currently checked in, or their folio has already been '
                    'invoiced. Please take payment another way and tell reception.',
                    order=order.pos_reference or order.name,
                    guest=partner.name,
                ))

            amount = sum(payments.mapped('amount'))
            account = payments[0].payment_method_id.receivable_account_id

            room = reservation.room_id.name or _('Room')
            outlet = order.config_id.name or _('Restaurant')
            description = _(
                '%(outlet)s — %(ref)s (Room %(room)s)',
                outlet=outlet, ref=order.pos_reference or order.name, room=room,
            )

            # sudo mirrors hotel_reservation_service._post_to_folio: the cashier
            # has no folio write access, and every value here is derived from
            # this order and the guest's own reservation.
            folio_line = self.env['hotel.folio.line'].sudo().create({
                'folio_id': folio.id,
                'name': description,
                'charge_type': 'fnb',
                'quantity': 1.0,
                'amount': amount,
                'date': fields.Date.context_today(order, order.date_order),
                'account_id': account.id if account else False,
                'pos_order_id': order.id,
            })
            order.sudo().write({
                'hotel_folio_id': folio.id,
                'hotel_folio_line_id': folio_line.id,
            })
            _logger.info(
                'POS order %s charged %s to folio %s (room %s)',
                order.pos_reference or order.name, amount, folio.name, room,
            )
