# -*- coding: utf-8 -*-
from odoo import api, models

# Writing any of these can change who is in-house, which room they hold, or
# whether the folio still takes charges.
POS_FLAG_TRIGGERS = ('state', 'room_id', 'guest_id', 'folio_id')


class HotelReservation(models.Model):
    _inherit = 'hotel.reservation'

    # The POS customer list is driven by stored flags on res.partner, so they
    # have to be refreshed every time a guest's occupancy changes. Hooking
    # create/write rather than the state actions catches every path into
    # `checked_in` — imports and data fixes included, which is how the migrated
    # bookings ended up checked in with no flags set.

    @api.model_create_multi
    def create(self, vals_list):
        reservations = super().create(vals_list)
        occupying = reservations.filtered(lambda r: r.state == 'checked_in')
        occupying.mapped('guest_id')._recompute_hotel_pos_fields()
        return reservations

    def write(self, vals):
        touches_occupancy = any(field in vals for field in POS_FLAG_TRIGGERS)
        # The guest may be swapped out by this very write, and the one losing
        # the reservation has to be cleared too.
        previous_guests = self.mapped('guest_id') if touches_occupancy else None
        res = super().write(vals)
        if touches_occupancy:
            (previous_guests | self.mapped('guest_id'))._recompute_hotel_pos_fields()
        return res


class HotelFolioInvoiceSync(models.Model):
    _inherit = 'hotel.folio'

    def action_create_invoice(self):
        """Once a folio is invoiced it can take no further charges, so the
        guest must drop out of the POS list even before check-out."""
        invoice = super().action_create_invoice()
        self.mapped('guest_id')._recompute_hotel_pos_fields()
        return invoice
