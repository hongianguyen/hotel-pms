# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Stored rather than computed: the POS load domain and the cashier's search
    # both need to filter on these in SQL, and the value only changes on
    # check-in / check-out, which we hook explicitly.
    hotel_in_house = fields.Boolean(
        'In House', readonly=True, copy=False, index=True,
        help='Guest is currently checked in with a folio still open for charges.',
    )
    hotel_room_number = fields.Char(
        'Room', readonly=True, copy=False, index=True,
        help='Room this guest currently occupies. Cleared at check-out.',
    )
    hotel_folio_id = fields.Many2one(
        'hotel.folio', string='Open Folio', readonly=True, copy=False,
        help='Folio that POS room charges are posted to.',
    )

    def _hotel_open_folio(self):
        """Return this partner's folio that can still accept charges, if any.

        A folio qualifies when the guest is checked in and the folio has not
        been invoiced yet — once `invoice_id` is set, `action_create_invoice`
        refuses to bill again and a new line would never reach the guest.
        """
        self.ensure_one()
        reservation = self.env['hotel.reservation'].sudo().search([
            ('guest_id', '=', self.id),
            ('state', '=', 'checked_in'),
            ('folio_id', '!=', False),
        ], order='checkin_date desc', limit=1)
        folio = reservation.folio_id
        if folio and not folio.invoice_id:
            return reservation, folio
        return reservation, self.env['hotel.folio']

    def _recompute_hotel_pos_fields(self):
        """Refresh the POS-facing in-house flags from current reservations."""
        for partner in self:
            reservation, folio = partner._hotel_open_folio()
            partner.sudo().write({
                'hotel_in_house': bool(folio),
                'hotel_room_number': reservation.room_id.name if folio else False,
                'hotel_folio_id': folio.id if folio else False,
            })

    # ── POS data loading ─────────────────────────────────────────────────────

    @api.model
    def _load_pos_data_domain(self, data, config):
        """Restrict the POS customer list to in-house guests when configured.

        Walk-ins do not need a customer on the order, so an in-house-only list
        is not a restriction on ordinary cash sales — but it does mean a
        walk-in cannot be invoiced from POS. Hence the per-POS toggle.
        """
        if config.limit_partners_to_in_house:
            return [('hotel_in_house', '=', True)]
        return super()._load_pos_data_domain(data, config)

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + [
            'hotel_in_house', 'hotel_room_number',
        ]

    @api.model
    def get_new_partner(self, config_id, domain, offset):
        """Cashier-side search: keep it inside the in-house set, and let the
        typed term match a room number as well as the standard fields."""
        config = self.env['pos.config'].browse(config_id)
        if config.limit_partners_to_in_house:
            room_domain = []
            term = self._extract_search_term(domain)
            if term:
                # OR the room number in alongside whatever POS already searches
                room_domain = ['|', ('hotel_room_number', 'ilike', term)]
            domain = [('hotel_in_house', '=', True)] + room_domain + list(domain)
        return super().get_new_partner(config_id, domain, offset)

    @api.model
    def _extract_search_term(self, domain):
        """Recover the query string POS built its OR-domain from."""
        for leaf in domain:
            if isinstance(leaf, (list, tuple)) and len(leaf) == 3:
                return leaf[2]
        return None
