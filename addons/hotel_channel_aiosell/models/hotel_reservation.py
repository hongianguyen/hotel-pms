# -*- coding: utf-8 -*-
"""PMS-side fields the Aiosell link needs.

Kept deliberately small: the link stores where a booking came from and never
changes how reservations behave otherwise. There is no write() override that
fires a sync — pushes are batched by the cron, because an inline push per write
would put an HTTP round trip inside every reception save.
"""
from datetime import date, timedelta

from odoo import api, fields, models


class HotelRoom(models.Model):
    _inherit = 'hotel.room'

    def _aiosell_out_of_service(self, day):
        """True when this room cannot be sold on `day`.

        Maintenance is held two ways in this PMS: a current status, and an
        optional date window. A window is authoritative when present; a bare
        'maintenance' status with no window is treated as out for the whole
        horizon, which is the safe reading.
        """
        self.ensure_one()
        start, stop = self.maintenance_date_from, self.maintenance_date_to
        if start or stop:
            if (start or date.min) <= day <= (stop or date.max):
                return True
            return False
        return self.status == 'maintenance'


class HotelReservation(models.Model):
    _inherit = 'hotel.reservation'

    aiosell_config_id = fields.Many2one(
        'aiosell.config', string='Aiosell Connection', readonly=True,
        ondelete='set null', copy=False,
    )
    aiosell_booking_id = fields.Char(
        'OTA Booking ID', readonly=True, index=True, copy=False,
        help='Booking reference issued by the OTA, as forwarded by Aiosell.',
    )
    aiosell_cm_booking_id = fields.Char(
        'Channel Manager Booking ID', readonly=True, copy=False,
    )
    aiosell_channel = fields.Char('OTA Channel', readonly=True, copy=False)
    aiosell_payload = fields.Text(
        'Last Aiosell Payload', readonly=True, copy=False,
        help='Raw JSON as received, kept so a disputed booking can be '
             'checked against what the channel actually sent.',
    )
    ota_nightly_rate = fields.Float(
        'OTA Nightly Rate', digits=(16, 2), readonly=True, copy=False,
        help='Rate the channel actually sold this room at, averaged over the '
             'stay. It overrides the PMS price list, because the OTA rate is '
             'what the guest agreed to pay and what the folio must charge.',
    )

    # The parent computes nightly_rate from the price list while a booking is
    # still draft or confirmed, and freezes it afterwards. An OTA booking has
    # no local price to compute: the channel already sold it at an agreed
    # rate. So the override wins for exactly as long as the parent would
    # otherwise keep recomputing.
    #
    # NOTE: Odoo takes a computed field's dependencies from the last
    # definition of the compute method, so the parent's @api.depends list has
    # to be repeated here in full. If hotel_frontdesk gains a new dependency,
    # add it here too.
    @api.depends('rate_plan_id', 'rate_plan_id.base_rate',
                 'room_id', 'room_id.base_rate',
                 'room_type_id', 'room_type_id.is_roh',
                 'room_type_id.base_rate',
                 'combo_id', 'combo_id.nightly_rate',
                 'state', 'ota_nightly_rate')
    def _compute_nightly_rate(self):
        super()._compute_nightly_rate()
        for rec in self:
            if rec.ota_nightly_rate and rec.state in self._RATE_FOLLOWS_PRICE_LIST:
                rec.nightly_rate = rec.ota_nightly_rate

    def action_aiosell_mark_no_show(self):
        """Tell the channel about a no-show so the OTA can bill it."""
        self.ensure_one()
        if not (self.aiosell_config_id and self.aiosell_booking_id):
            return False
        return self.aiosell_config_id.mark_no_show(
            self.aiosell_booking_id, self.aiosell_channel or '',
        )
