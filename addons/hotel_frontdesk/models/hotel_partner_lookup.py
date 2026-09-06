# -*- coding: utf-8 -*-
"""Front-desk partner lookup: find the customer from what the caller says.

Reception rarely knows a customer's record — they know a phone number or a
tax code. These two search boxes turn either into the partner, filling the
rest of the form from what is already on file. Companies additionally fall
through to the Vietnamese business registry when the hotel has never dealt
with them before.

The behaviour is identical on a single reservation and on a group booking,
so it lives here once; both models name their fields ``guest_id`` and
``agency_id``, which is what lets one mixin serve both.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HotelPartnerLookup(models.AbstractModel):
    _name = 'hotel.partner.lookup.mixin'
    _description = 'Find Guests by Phone and Companies by Tax Code'

    # Both search boxes double as the display of what is already selected:
    # they show the chosen partner's number/code, and typing over them
    # searches. They are stored rather than computed-on-the-fly because an
    # unstored compute re-runs and wipes whatever reception has just typed;
    # storing also keeps the number the booking was actually taken on, even
    # if the partner's own details are edited later.
    guest_phone = fields.Char(
        'Phone', compute='_compute_guest_phone', readonly=False, store=True,
        help='Type a phone number to find a guest already on file. '
             'Formatting and the +84 country code are ignored.',
    )
    agency_vat = fields.Char(
        'Tax Code', compute='_compute_agency_vat', readonly=False, store=True,
        help='Type a tax code to find the company. If the hotel has never '
             'dealt with it, the Vietnamese business registry is searched.',
    )

    # Preview of a registry hit for a company we do not have on file. Held
    # only for the life of the form: nothing is created until reception says
    # so, so a discarded reservation leaves no stray company behind.
    vn_registry_name = fields.Char('Registered Name', readonly=True, store=False)
    vn_registry_address = fields.Char('Registered Address', readonly=True, store=False)
    vn_registry_status = fields.Char('Tax Status', readonly=True, store=False)
    vn_registry_found = fields.Boolean(readonly=True, store=False)

    # Once a partner is selected the box mirrors that partner, blank phone
    # and all: keeping a typed number against a guest who does not have it
    # would leave the form showing a phone number the guest record denies.
    # Only while nothing is selected does the box hold what was typed, so
    # that a search in progress is not erased.

    @api.depends('guest_id')
    def _compute_guest_phone(self):
        for rec in self:
            if rec.guest_id:
                rec.guest_phone = rec.guest_id.phone or False
            else:
                rec.guest_phone = rec.guest_phone or False

    @api.depends('agency_id')
    def _compute_agency_vat(self):
        for rec in self:
            if rec.agency_id:
                rec.agency_vat = rec.agency_id.vat or False
            else:
                rec.agency_vat = rec.agency_vat or False

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

    # ── Companies: search on tax code, then the registry ─────────────────

    @api.onchange('agency_vat')
    def _onchange_agency_vat(self):
        """Fill the company in from its tax code.

        On file: selected outright. Not on file: looked up in the Vietnamese
        business registry and shown as a preview for reception to accept.
        """
        self.ensure_one()
        self._clear_registry_preview()
        typed = self.agency_vat
        if not typed:
            return
        if self.agency_id and self.agency_id.vat == typed:
            return

        Partner = self.env['res.partner']
        vat = Partner._vn_normalize_vat(typed)

        existing = Partner._vn_find_by_vat(vat)
        if existing:
            self.agency_id = existing
            return

        self.agency_id = False
        from .res_partner import VN_TAX_CODE_RE
        if not VN_TAX_CODE_RE.match(vat):
            # Half-typed code: say nothing rather than nag on every keystroke.
            return

        try:
            data = Partner._vn_lookup_tax_code(vat)
        except UserError as err:
            # The registry being unreachable must not block the booking.
            return {'warning': {
                'title': _('Tax registry lookup failed'),
                'message': err.args[0] if err.args else _('Unknown error.'),
            }}

        if not data:
            return {'warning': {
                'title': _('Tax code not found'),
                'message': _(
                    'Tax code %s is not on file here and the Vietnamese '
                    'business registry does not recognise it. Please check '
                    'the number, or create the company by hand.'
                ) % vat,
            }}

        self.vn_registry_found = True
        self.vn_registry_name = data.get('name')
        self.vn_registry_address = data.get('address')
        self.vn_registry_status = data.get('status')

    def _clear_registry_preview(self):
        self.vn_registry_found = False
        self.vn_registry_name = False
        self.vn_registry_address = False
        self.vn_registry_status = False

    def action_create_agency_from_registry(self):
        """Put the previewed registry company on file and select it.

        Creation is deliberate rather than automatic: an onchange that
        created partners would leave one behind every time reception
        mistyped a tax code and discarded the form.
        """
        self.ensure_one()
        Partner = self.env['res.partner']
        vat = Partner._vn_normalize_vat(self.agency_vat)
        if not vat:
            raise UserError(_('Enter a tax code first.'))

        # Re-check rather than trusting the preview: another user may have
        # created the company since the lookup ran.
        partner = Partner._vn_find_or_create_by_vat(vat, extra_vals={
            # Without these the new company fails the agency_id domain and
            # would not be selectable in the field it was created for.
            'is_hotel_agency': True,
            'hotel_agency_type': 'corporate',
        })
        if not partner:
            raise UserError(_(
                'Tax code %s is not in the Vietnamese business registry.'
            ) % vat)

        self.agency_id = partner
        self._clear_registry_preview()
        return True
