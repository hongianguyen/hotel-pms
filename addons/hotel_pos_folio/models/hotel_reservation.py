# -*- coding: utf-8 -*-
from odoo import models


class HotelReservation(models.Model):
    _inherit = 'hotel.reservation'

    # The POS customer list is driven by stored flags on res.partner, so they
    # have to be refreshed every time a guest's occupancy changes. Hooking the
    # state actions keeps that in one place rather than relying on a stored
    # compute that would have to depend backwards from partner to reservation.

    def action_check_in(self):
        res = super().action_check_in()
        self.mapped('guest_id')._recompute_hotel_pos_fields()
        return res

    def action_check_out(self):
        res = super().action_check_out()
        self.mapped('guest_id')._recompute_hotel_pos_fields()
        return res

    def action_cancel(self):
        res = super().action_cancel()
        self.mapped('guest_id')._recompute_hotel_pos_fields()
        return res


class HotelFolioInvoiceSync(models.Model):
    _inherit = 'hotel.folio'

    def action_create_invoice(self):
        """Once a folio is invoiced it can take no further charges, so the
        guest must drop out of the POS list even before check-out."""
        invoice = super().action_create_invoice()
        self.mapped('guest_id')._recompute_hotel_pos_fields()
        return invoice
