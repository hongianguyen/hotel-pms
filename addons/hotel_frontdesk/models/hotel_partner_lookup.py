# -*- coding: utf-8 -*-
"""Front-desk guest lookup: find the guest from the number they called on.

Reception rarely knows a guest's record — they know a phone number. This
search box turns one into the guest, filling the rest of the form from
what is already on file.

The behaviour is identical on a single reservation and on a group booking,
so it lives here once; both models name the field ``guest_id``, which is
what lets one mixin serve both. Companies are looked up by tax code on the
company form itself — see ``res_partner.py``.
"""
from odoo import models, fields, api, _


class HotelPartnerLookup(models.AbstractModel):
    _name = 'hotel.partner.lookup.mixin'
    _description = 'Find Guests by Phone'

    # The search box doubles as the display of the selected guest's number:
    # it shows their phone, and typing over it searches. It is stored rather
    # than computed-on-the-fly because an unstored compute re-runs and wipes
    # whatever reception has just typed; storing also keeps the number the
    # booking was actually taken on, even if the guest's own details are
    # edited later.
    guest_phone = fields.Char(
        'Phone', compute='_compute_guest_phone', readonly=False, store=True,
        help='Type a phone number to find a guest already on file. '
             'Formatting and the +84 country code are ignored.',
    )

    @api.depends('guest_id')
    def _compute_guest_phone(self):
        for rec in self:
            if rec.guest_id:
                rec.guest_phone = rec.guest_id.phone or False
            else:
                rec.guest_phone = rec.guest_phone or False

    # ── Individuals: search on phone ─────────────────────────────────────

    @api.onchange('guest_phone')
    def _onchange_guest_phone(self):
        """Fill the guest in from their phone number.

        Purely a search: it never creates or edits a partner, so retyping a
        number is always safe.
        """
        self.ensure_one()
        typed = self.guest_phone
        if not typed:
            return
        # Already showing this guest's own number — nothing was searched for.
        if self.guest_id and self.guest_id.phone == typed:
            return

        Partner = self.env['res.partner']
        if not Partner._vn_phone_key(typed):
            return

        matches = Partner._vn_find_by_phone(typed)
        if len(matches) == 1:
            self.guest_id = matches
        elif len(matches) > 1:
            # Picking one for them would silently attach the booking to the
            # wrong person, which surfaces much later and much worse.
            return {'warning': {
                'title': _('Several guests share this number'),
                'message': _(
                    '%(count)s guests are on file with this phone number '
                    '(%(names)s). Please pick the right one in the Guest '
                    'field.',
                    count=len(matches),
                    names=', '.join(matches.mapped('name')),
                ),
            }}
        elif self.guest_id:
            # A number that belongs to nobody on file is a new guest, not a
            # correction to the one already selected.
            self.guest_id = False
