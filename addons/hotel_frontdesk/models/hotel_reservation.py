# -*- coding: utf-8 -*-
from odoo import models, fields, api, tools, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta


class HotelReservation(models.Model):
    _name = 'hotel.reservation'
    _description = 'Hotel Reservation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'checkin_date desc, id desc'
    _rec_name = 'reservation_number'

    reservation_number = fields.Char(
        'Reservation #', readonly=True, copy=False, default='New',
    )
    guest_id = fields.Many2one(
        'res.partner', string='Guest', required=True, tracking=True,
        domain="[('is_company', '=', False)]",
    )
    guest_phone = fields.Char(related='guest_id.phone', string='Phone')
    guest_email = fields.Char(related='guest_id.email', string='Email')

    room_type_id = fields.Many2one(
        'hotel.room.type', string='Room Type', tracking=True,
    )
    is_roh = fields.Boolean(related='room_type_id.is_roh', string='Run of House')
    # ROH bookings may hold a room of any physical type; the domain below
    # widens accordingly via this computed helper.
    allowed_room_type_ids = fields.Many2many(
        'hotel.room.type', compute='_compute_allowed_room_type_ids',
    )
    room_id = fields.Many2one(
        'hotel.room', string='Room', tracking=True,
        domain="[('room_type_id', 'in', allowed_room_type_ids), ('active', '=', True)]",
    )
    rate_plan_id = fields.Many2one(
        'hotel.rate.plan', string='Rate Plan', tracking=True,
    )
    combo_id = fields.Many2one(
        'hotel.combo', string='Combo Package', tracking=True,
        help='Package of accommodation + services. Selecting a combo books '
             'the accommodation and adds the included services to the folio '
             'at check-in.',
    )

    checkin_date = fields.Date('Check-in Date', required=True, tracking=True,
                               index=True)
    checkout_date = fields.Date('Check-out Date', required=True, tracking=True,
                                index=True)
    nights = fields.Integer('Nights', compute='_compute_nights', store=True)

    nightly_rate = fields.Float('Nightly Rate', digits=(16, 2), compute='_compute_nightly_rate', store=True)
    total_amount = fields.Float('Total Amount', digits=(16, 2), compute='_compute_total_amount', store=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('checked_in', 'Checked In'),
        ('checked_out', 'Checked Out'),
        ('no_show', 'No Show'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True,
        index=True)

    folio_id = fields.Many2one('hotel.folio', string='Folio', readonly=True, copy=False)
    group_id = fields.Many2one(
        'hotel.booking.group', string='Group Booking', ondelete='set null',
        index=True, tracking=True, copy=False,
    )
    source_id = fields.Many2one('hotel.booking.source', string='Booking Source', tracking=True)

    # ── Travel agent / corporate account billing ────────────────────────
    agency_id = fields.Many2one(
        'res.partner', string='Agency / Company', tracking=True,
        domain="[('is_hotel_agency', '=', True)]",
        help='Travel agency or corporate account that sent this booking. '
             'The invoice is issued to this company instead of the guest, '
             'and confirmation emails go to the booker.',
    )
    booker_id = fields.Many2one(
        'res.partner', string='Booker', tracking=True,
        domain="['|', ('id', '=', agency_id), ('parent_id', '=', agency_id)]",
        help='Contact at the agency/company who made the booking. '
             'Confirmation emails are sent to this person.',
    )
    booker_email = fields.Char(
        'Booker Email', compute='_compute_booker_email',
    )
    agency_credit_term = fields.Boolean(
        related='agency_id.hotel_credit_term', string='Credit Terms',
    )
    bill_to_id = fields.Many2one(
        'res.partner', string='Bill To', compute='_compute_bill_to_id',
        store=True,
        help='Party the invoice is issued to: the agency/company for '
             'corporate bookings, otherwise the guest.',
    )
    payment_required = fields.Boolean(
        'Prepayment Required', tracking=True,
        help='Block check-in until prepayment is marked as received '
             '(e.g. non-refundable OTA rates).',
    )
    prepaid = fields.Boolean(
        'Prepayment Received', tracking=True,
        help='Tick when the required prepayment has been received.',
    )
    send_confirmation = fields.Boolean('Send Confirmation Email', default=True)
    notes = fields.Text('Notes')
    color = fields.Integer('Color', compute='_compute_color')

    adults = fields.Integer('Adults', default=1)
    children = fields.Integer('Children', default=0)

    # ── Pax (guest names staying in this room) ──────────────────────────
    pax_ids = fields.One2many(
        'hotel.reservation.pax', 'reservation_id', string='Guests (Pax)',
        copy=True,
    )
    pax_count = fields.Integer('Pax Count', compute='_compute_pax', store=True)
    pax_names = fields.Char(
        'Pax Names', compute='_compute_pax', store=True,
        help='Comma-separated guest names for lists, folio and dashboards.',
    )

    # ── Services booked with the reservation (from draft onwards) ───────
    service_line_ids = fields.One2many(
        'hotel.reservation.service', 'reservation_id', string='Services',
        copy=True,
    )
    services_total = fields.Float(
        'Services Total', compute='_compute_services_total', store=True,
        digits=(16, 2),
    )

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
    )

    # ── Computed Fields ─────────────────────────────────────────────────

    @api.depends('checkin_date', 'checkout_date')
    def _compute_nights(self):
        for rec in self:
            if rec.checkin_date and rec.checkout_date:
                delta = rec.checkout_date - rec.checkin_date
                rec.nights = max(delta.days, 0)
            else:
                rec.nights = 0

    @api.depends('room_type_id')
    def _compute_allowed_room_type_ids(self):
        physical_types = self.env['hotel.room.type'].search([('is_roh', '=', False)])
        for rec in self:
            if rec.room_type_id.is_roh:
                rec.allowed_room_type_ids = physical_types
            else:
                rec.allowed_room_type_ids = rec.room_type_id

    # Rates quoted once the guest has arrived (or left) are agreed prices,
    # and their room charges are already posted to the folio — a later
    # price-list edit must not rewrite them. Only these states track the
    # current price list.
    _RATE_FOLLOWS_PRICE_LIST = ('draft', 'confirmed')

    @api.depends('rate_plan_id', 'rate_plan_id.base_rate',
                 'room_id', 'room_id.base_rate',
                 'room_type_id', 'room_type_id.is_roh',
                 'room_type_id.base_rate',
                 'combo_id', 'combo_id.nightly_rate',
                 'state')
    def _compute_nightly_rate(self):
        # Read the persisted rate directly: for records whose price is
        # already locked in we re-assign what is on disk rather than
        # recomputing (a stored compute must assign every record in self).
        locked = self.filtered(
            lambda r: r.state not in self._RATE_FOLLOWS_PRICE_LIST
            and isinstance(r.id, int))
        stored = {}
        if locked:
            self.env.cr.execute(
                'SELECT id, nightly_rate FROM hotel_reservation WHERE id IN %s',
                (tuple(locked.ids),))
            stored = dict(self.env.cr.fetchall())

        for rec in self:
            if rec.id in stored:
                rec.nightly_rate = stored[rec.id] or 0.0
            elif rec.combo_id:
                rec.nightly_rate = rec.combo_id.nightly_rate
            elif rec.rate_plan_id and rec.rate_plan_id.base_rate:
                rec.nightly_rate = rec.rate_plan_id.base_rate
            elif rec.room_type_id and rec.room_type_id.is_roh:
                # ROH: flat rate regardless of the room actually assigned
                rec.nightly_rate = rec.room_type_id.base_rate
            elif rec.room_id:
                rec.nightly_rate = rec.room_id.base_rate
            elif rec.room_type_id:
                rec.nightly_rate = rec.room_type_id.base_rate
            else:
                rec.nightly_rate = 0.0

    @api.depends('booker_id.email', 'agency_id.email')
    def _compute_booker_email(self):
        for rec in self:
            rec.booker_email = rec.booker_id.email or rec.agency_id.email or False

    @api.depends('agency_id', 'guest_id')
    def _compute_bill_to_id(self):
        for rec in self:
            rec.bill_to_id = rec.agency_id or rec.guest_id

    @api.depends('pax_ids.name')
    def _compute_pax(self):
        for rec in self:
            names = [p.name for p in rec.pax_ids if p.name]
            rec.pax_count = len(names)
            rec.pax_names = ', '.join(names)

    @api.depends('service_line_ids.subtotal')
    def _compute_services_total(self):
        for rec in self:
            rec.services_total = sum(rec.service_line_ids.mapped('subtotal'))

    @api.depends('nights', 'nightly_rate', 'rate_plan_id', 'combo_id',
                 'checkin_date', 'checkout_date', 'services_total')
    def _compute_total_amount(self):
        """Sum per-night rates so the quoted total matches the folio.

        Uses the same per-date rate-plan/season logic as
        hotel.folio._generate_room_charges; falls back to the flat
        nightly_rate for dates the plan does not cover. Combo bookings
        use the combo's fixed accommodation rate (rate plans ignored)
        plus the combo's included services.
        """
        for rec in self:
            if not (rec.checkin_date and rec.checkout_date and rec.nights > 0):
                rec.total_amount = 0.0
                continue
            total = 0.0
            current = rec.checkin_date
            while current < rec.checkout_date:
                day_rate = rec.nightly_rate
                if rec.rate_plan_id and not rec.combo_id:
                    plan_rate = rec.rate_plan_id.get_rate_for_date(current)
                    if plan_rate:
                        day_rate = plan_rate
                total += day_rate
                current += timedelta(days=1)
            # Combo services are materialized as service lines, so they
            # are already covered by services_total.
            total += rec.services_total
            rec.total_amount = total

    @api.depends('state')
    def _compute_color(self):
        color_map = {
            'draft': 0,
            'confirmed': 4,     # light blue
            'checked_in': 10,   # green
            'checked_out': 1,   # red/grey
            'cancelled': 6,     # dark
        }
        for rec in self:
            rec.color = color_map.get(rec.state, 0)

    # ── Constraints ──────────────────────────────────────────────────────

    # Belt & braces: same rule at DB level so no code path can bypass it
    _dates_order = models.Constraint(
        'CHECK(checkout_date > checkin_date)',
        'Check-in date must always be before check-out date!',
    )

    @api.constrains('checkin_date', 'checkout_date')
    def _check_dates(self):
        for rec in self:
            if rec.checkin_date and rec.checkout_date:
                if rec.checkout_date <= rec.checkin_date:
                    raise ValidationError(_('Check-in date must always be before check-out date.'))

    @api.constrains('room_type_id', 'group_id')
    def _check_roh_group_only(self):
        for rec in self:
            if rec.room_type_id.is_roh and not rec.group_id:
                raise ValidationError(_(
                    'Room type "%s" is Run of House (ROH) and is only '
                    'available for group bookings.') % rec.room_type_id.name)

    # ── Combo → service lines ────────────────────────────────────────────

    def _combo_service_line_vals(self):
        """Service-line values for every component of the selected combo."""
        self.ensure_one()
        return [{
            'service_id': line.service_id.id,
            'quantity': line.quantity,
            'price_unit': line.price_unit,
            'combo_id': self.combo_id.id,
        } for line in self.combo_id.line_ids]

    def _sync_combo_services(self):
        """Mirror the selected combo's components into the service lines.

        Idempotent: drops un-charged lines of a previously selected combo
        and adds the current combo's components unless they are already
        present (e.g. saved by the form after the onchange preview).
        """
        for rec in self:
            stale = rec.service_line_ids.filtered(
                lambda l: l.combo_id and l.combo_id != rec.combo_id
                and not l.folio_line_id)
            stale.unlink()
            if rec.combo_id and not rec.service_line_ids.filtered(
                    lambda l: l.combo_id == rec.combo_id):
                self.env['hotel.reservation.service'].create([
                    dict(vals, reservation_id=rec.id)
                    for vals in rec._combo_service_line_vals()])

    # ── Onchanges ─────────────────────────────────────────────────────────

    @api.onchange('agency_id')
    def _onchange_agency_id(self):
        if self.agency_id:
            # Keep the booker only if it belongs to the selected company
            if (self.booker_id != self.agency_id
                    and self.booker_id.parent_id != self.agency_id):
                self.booker_id = self.agency_id
            # No credit terms → the company must prepay before check-in;
            # with credit terms the invoice is settled on account later.
            self.payment_required = not self.agency_id.hotel_credit_term
        else:
            self.booker_id = False

    @api.onchange('combo_id')
    def _onchange_combo_id(self):
        if self.combo_id:
            self.room_type_id = self.combo_id.room_type_id
            self.rate_plan_id = False
            if self.checkin_date:
                self.checkout_date = self.checkin_date + timedelta(
                    days=self.combo_id.nights)
        # Live preview: swap combo-originated service lines so the guest
        # sees every component of the package before confirming.
        stale = self.service_line_ids.filtered(
            lambda l: l.combo_id and l.combo_id != self.combo_id
            and not l.folio_line_id)
        self.service_line_ids -= stale
        if self.combo_id and not self.service_line_ids.filtered(
                lambda l: l.combo_id == self.combo_id):
            self.service_line_ids = [
                (0, 0, vals) for vals in self._combo_service_line_vals()]

    @api.onchange('checkin_date')
    def _onchange_checkin_date_combo(self):
        if self.combo_id and self.checkin_date:
            self.checkout_date = self.checkin_date + timedelta(
                days=self.combo_id.nights)

    @api.constrains('room_id', 'checkin_date', 'checkout_date', 'state')
    def _check_room_availability(self):
        for rec in self:
            if rec.room_id and rec.state in ('confirmed', 'checked_in'):
                overlap = self.search([
                    ('id', '!=', rec.id),
                    ('room_id', '=', rec.room_id.id),
                    ('state', 'in', ['confirmed', 'checked_in']),
                    ('checkin_date', '<', rec.checkout_date),
                    ('checkout_date', '>', rec.checkin_date),
                ], limit=1)
                if overlap:
                    raise ValidationError(
                        _('Room %s is already booked from %s to %s (Reservation %s).')
                        % (rec.room_id.name, overlap.checkin_date,
                           overlap.checkout_date, overlap.reservation_number)
                    )

    # ── CRUD ──────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reservation_number', 'New') == 'New':
                vals['reservation_number'] = self.env['ir.sequence'].next_by_code(
                    'hotel.reservation') or 'New'
            # Bookings inside a group charge to the group's master folio
            if vals.get('group_id') and not vals.get('folio_id'):
                group = self.env['hotel.booking.group'].browse(vals['group_id'])
                if group.master_folio_id:
                    vals['folio_id'] = group.master_folio_id.id
            # Prepayment rule for non-credit agencies. The form onchange sets
            # this, but the group wizard and programmatic creates bypass
            # onchanges — derive it here so no path skips the rule.
            if vals.get('agency_id') and 'payment_required' not in vals:
                agency = self.env['res.partner'].browse(vals['agency_id'])
                vals['payment_required'] = not agency.hotel_credit_term
        records = super().create(vals_list)
        # Keep the folio's primary-reservation convention (room/dates display)
        for rec in records:
            if rec.group_id and rec.folio_id and not rec.folio_id.reservation_id:
                rec.folio_id.reservation_id = rec.id
        # Combo picked programmatically (wizard/import): materialize services
        records.filtered('combo_id')._sync_combo_services()
        return records

    # ── Workflow Buttons ─────────────────────────────────────────────────

    def action_confirm(self):
        """Draft → Confirmed. Send confirmation email."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft reservations can be confirmed.'))
            if not rec.room_id:
                raise UserError(_('Please assign a room before confirming.'))
            rec.state = 'confirmed'
            # Group confirm sends one group-level email instead
            if rec.send_confirmation and not self.env.context.get('skip_confirmation_email'):
                template, recipient = rec._get_confirmation_template()
                if template and recipient:
                    template.send_mail(rec.id, force_send=True)

    def _get_confirmation_template(self):
        """Confirmation template + recipient email for this reservation.

        Corporate/agency bookings notify the booker at the sending company;
        direct bookings notify the guest.
        """
        self.ensure_one()
        if self.agency_id:
            return (
                self.env.ref(
                    'hotel_frontdesk.mail_template_reservation_confirmation_corporate',
                    raise_if_not_found=False),
                self.booker_email,
            )
        return (
            self.env.ref(
                'hotel_frontdesk.mail_template_reservation_confirmation',
                raise_if_not_found=False),
            self.guest_id.email,
        )

    # ── Folios & routing instructions ────────────────────────────────────

    # Charge types the company takes when routing is "Room & Tax only".
    _COMPANY_ROUTED_TYPES = ('room',)

    def _effective_agency(self):
        """Agency billing this stay, falling back to the group's.

        A room inside a corporate group booking is a corporate booking even
        when the child record was created without its own agency_id.
        """
        self.ensure_one()
        return self.agency_id or self.group_id.agency_id

    def _routing(self):
        """Effective routing instruction for this reservation."""
        self.ensure_one()
        agency = self._effective_agency()
        if not agency:
            return 'none'
        return agency.hotel_routing or 'room'

    def _ensure_folios(self):
        """Open the folios this reservation needs, idempotently.

        Direct bookings keep a single guest folio. Agency/corporate bookings
        get the SOP pair: a guest folio for incidentals the guest settles on
        departure, and a company folio (city ledger) for the charges routed
        to the sending company.
        """
        self.ensure_one()
        Folio = self.env['hotel.folio'].sudo()
        routing = self._routing()
        current = self.folio_id
        group_master = self.group_id.master_folio_id

        # Find this reservation's guest folio. folio_id may still point at a
        # group master (shared by every room), so fall back to a lookup by
        # reservation rather than trusting it blindly.
        if current and current.folio_type == 'guest':
            guest_folio = current
        else:
            guest_folio = Folio.search([
                ('reservation_id', '=', self.id),
                ('folio_type', '=', 'guest'),
            ], limit=1)

        # Find the company folio: a group's master folio doubles as it, and a
        # single booking's is already linked from the guest folio. Locating it
        # before creating is what keeps this method idempotent.
        company_folio = Folio.browse()
        if routing != 'none':
            if group_master:
                if group_master.folio_type != 'company':
                    group_master.write({'folio_type': 'company'})
                company_folio = group_master
            elif guest_folio.linked_folio_id.folio_type == 'company':
                company_folio = guest_folio.linked_folio_id
            elif current.folio_type == 'company':
                company_folio = current

        if not guest_folio:
            guest_folio = Folio.create({
                'reservation_id': self.id,
                'guest_id': self.guest_id.id,
                'folio_type': 'guest',
            })

        if routing != 'none' and not company_folio:
            company_folio = Folio.create({
                'reservation_id': self.id,
                'guest_id': self.guest_id.id,
                'agency_id': self._effective_agency().id,
                'folio_type': 'company',
            })

        if company_folio:
            # The guest folio bills the guest even on a corporate booking:
            # the agency only pays what routing sends to the company folio.
            guest_folio.write({'linked_folio_id': company_folio.id})
            if not company_folio.linked_folio_id:
                company_folio.write({'linked_folio_id': guest_folio.id})
            agency = self._effective_agency()
            if company_folio.agency_id != agency:
                company_folio.write({'agency_id': agency.id})

        if self.folio_id != guest_folio:
            self.folio_id = guest_folio.id
        return guest_folio, company_folio

    def _folio_for_charge_type(self, charge_type):
        """Folio a charge of this type belongs on, per routing instructions.

        Single resolver for every charge producer — room charges, booked
        services, POS postings and manual charges — so routing cannot drift
        between them.
        """
        self.ensure_one()
        guest_folio = self.folio_id
        company_folio = guest_folio.linked_folio_id.filtered(
            lambda f: f.folio_type == 'company'
        )
        if not company_folio:
            return guest_folio

        routing = self._routing()
        if routing == 'all':
            return company_folio
        if routing == 'room' and charge_type in self._COMPANY_ROUTED_TYPES:
            return company_folio
        return guest_folio

    def action_check_in(self):
        """Confirmed → Checked In. Create folio (or reuse group folio), set room occupied."""
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('Only confirmed reservations can be checked in.'))
            if rec.checkin_date > fields.Date.context_today(rec):
                raise UserError(_(
                    'Reservation %(number)s cannot be checked in before its '
                    'check-in date (%(date)s).',
                    number=rec.reservation_number,
                    date=rec.checkin_date.strftime('%d/%m/%Y'),
                ))
            if rec.payment_required and not rec.prepaid:
                raise UserError(_(
                    'Reservation %s requires prepayment before check-in. '
                    'Mark "Prepayment Received" once payment arrives.'
                ) % rec.reservation_number)
            if rec.room_id.status == 'maintenance':
                raise UserError(_('Room %s is under maintenance.') % rec.room_id.name)
            if rec.room_id.status not in ('available', 'cleaning'):
                raise UserError(
                    _('Room %s is not available (current status: %s).')
                    % (rec.room_id.name, rec.room_id.status)
                )

            # Open (or reuse) this reservation's folios, then post the room
            # charges to whichever folio routing sends them to.
            rec._ensure_folios()
            rec._folio_for_charge_type('room')._generate_room_charges(rec)

            # Services booked with the reservation (incl. combo components)
            # hit the folio at check-in. Sync first so pre-upgrade combo
            # bookings without materialized lines still get charged.
            rec._sync_combo_services()
            rec.service_line_ids._post_to_folio()

            rec.state = 'checked_in'
            rec.room_id.action_set_occupied()

    def _late_checkout_line_vals(self):
        """Folio line values for each night stayed past the checkout date.

        Returned rather than written so the caller can quote the amount to
        reception before deciding whether the departure may go ahead.
        """
        self.ensure_one()
        today = fields.Date.context_today(self)
        if (today - self.checkout_date).days <= 0:
            return []
        vals = []
        current = self.checkout_date
        room_name = self.room_id.name or 'Room'
        while current < today:
            vals.append({
                'name': _('Late checkout — Room %s — %s') % (
                    room_name, current.strftime('%d/%m/%Y')),
                'charge_type': 'room',
                'quantity': 1,
                'amount': self.nightly_rate,
                'date': current,
                'account_id': self.room_id.room_type_id.revenue_account_id.id or False,
            })
            current += timedelta(days=1)
        return vals

    def _folios_settling_on_departure(self):
        """Folios of this stay that this departure closes out.

        Both sides of the guest/company pair are in scope, but a folio is
        only judged once no other room that can still charge it is in house:
        on a group, the master folio is settled by the last departure, not
        the first.
        """
        self.ensure_one()
        folios = self.env['hotel.folio']
        for folio in (self.folio_id | self.folio_id.linked_folio_id):
            if not folio:
                continue
            if folio._pending_reservations() - self:
                continue
            folios |= folio
        return folios

    def _check_folio_balanced(self, extra_folio=None, extra_charges=0.0):
        """Block the departure while the guest still owes money.

        ``extra_folio`` / ``extra_charges`` describe a charge check-out is
        about to raise (late check-out nights), so it is counted as due even
        though it is not on the folio yet.

        A Hotel Administrator can override with the Check Out Anyway button,
        which sets ``force_unbalanced_checkout``; the override is recorded on
        the folio's chatter.
        """
        self.ensure_one()
        if self.env.context.get('force_unbalanced_checkout'):
            return
        blocking = []
        for folio in self._folios_settling_on_departure():
            extra = extra_charges if folio == extra_folio else 0.0
            due = folio.amount_due_at_checkout(extra)
            currency = folio.currency_id or self.env.company.currency_id
            if currency.compare_amounts(due, 0) > 0:
                blocking.append((folio, due, currency))
        if not blocking:
            return
        details = '\n'.join(
            '  • %s: %s' % (folio.name, self._format_money(due, currency))
            for folio, due, currency in blocking
        )
        raise UserError(_(
            'Cannot check out %(reservation)s — the folio is not balanced.\n\n'
            'Still to collect:\n%(details)s\n\n'
            'Take the payment on the folio with Register Payment, then check '
            'out. If the balance is genuinely to be carried (a company '
            'account on credit terms, or a disputed charge), a Hotel '
            'Administrator can use Check Out Anyway.'
        ) % {
            'reservation': self.reservation_number,
            'details': details,
        })

    @api.model
    def _format_money(self, amount, currency):
        """Amount rendered in the folio's currency for user-facing messages."""
        return tools.format_amount(self.env, amount, currency)

    def action_print_folio(self):
        """Print this stay's folio(s) for the guest to check and sign."""
        folios = self.mapped('folio_id') | self.mapped('folio_id.linked_folio_id')
        if not folios:
            raise UserError(_(
                'No folio to print yet — a folio opens when the guest '
                'checks in.'
            ))
        return folios.action_print_folio()

    def action_force_check_out(self):
        """Check out despite an unbalanced folio (Hotel Administrator only).

        The escape hatch for balances the desk cannot clear — a legacy folio
        imported without its payments, a write-off, a company account being
        moved to the city ledger by hand. Always leaves a trace.
        """
        if not self.env.su and not self.env.user.has_group(
                'hotel_core.group_hotel_admin'):
            raise UserError(_(
                'Only a Hotel Administrator can check out a reservation '
                'whose folio is not balanced.'
            ))
        # Which folios this departure closes has to be read before the state
        # changes, but the amount is read after: check-out may still raise a
        # late-checkout charge, and the trace has to record the debt actually
        # left behind rather than the one showing beforehand.
        folios_by_res = {
            rec.id: rec._folios_settling_on_departure() for rec in self
        }
        res = self.with_context(
            force_unbalanced_checkout=True).action_check_out()

        for rec in self:
            for folio in folios_by_res[rec.id]:
                folio.invalidate_recordset(['balance'])
                currency = folio.currency_id or self.env.company.currency_id
                due = folio.amount_due_at_checkout()
                if currency.compare_amounts(due, 0) <= 0:
                    continue
                folio.message_post(body=_(
                    'Check-out of %(reservation)s forced by %(user)s with '
                    '%(amount)s still outstanding on this folio.'
                ) % {
                    'reservation': rec.reservation_number,
                    'user': self.env.user.name,
                    'amount': self._format_money(due, currency),
                })
        return res

    def action_check_out(self):
        """Checked In → Checked Out. Generate invoice (only when last room checks out), room → dirty."""
        for rec in self:
            if rec.state != 'checked_in':
                raise UserError(_('Only checked-in reservations can be checked out.'))
            if not rec.folio_id:
                raise UserError(_('No folio found for this reservation.'))

            # Late checkout: auto-charge each night past the scheduled
            # checkout date at the reservation's nightly rate (spec §16).
            # Late-checkout nights are room revenue: same routing.
            late_vals = rec._late_checkout_line_vals()
            late_folio = (rec._folio_for_charge_type('room') if late_vals
                          else self.env['hotel.folio'])

            # Departure is barred while money is still owed. The late-checkout
            # nights are quoted as part of that amount but only written once
            # the folio clears, so a blocked check-out leaves no phantom
            # charge behind and the figure reception is told to collect is the
            # figure the folio will show.
            rec._check_folio_balanced(late_folio, sum(
                v['quantity'] * v['amount'] for v in late_vals))

            if late_vals:
                late_folio.sudo().write({
                    'line_ids': [(0, 0, v) for v in late_vals],
                })

            rec.write({'state': 'checked_out'})
            rec.room_id.write({'last_used_at': fields.Datetime.now()})
            rec.room_id.action_set_dirty()

            # Settle both sides of the pair. Each folio is invoiced only once
            # no room that can still charge it is in house — for a group's
            # company folio that means the last departure, not the first.
            for folio in (rec.folio_id | rec.folio_id.linked_folio_id):
                # Guard on the invoice, not the payment state: a folio the
                # guest already settled at the desk still needs its invoice.
                if not folio or folio.invoice_id or not folio.line_ids:
                    continue
                still_in = folio._pending_reservations() - rec
                if not still_in:
                    folio.action_create_invoice()

    def action_cancel(self):
        """Cancel reservation. Free room if it was confirmed."""
        for rec in self:
            if rec.state == 'checked_out':
                raise UserError(_('Cannot cancel a checked-out reservation.'))
            if rec.state == 'checked_in':
                raise UserError(_(
                    'Reservation %s is checked in. Check the guest out '
                    '(which settles the folio) instead of cancelling, '
                    'otherwise the folio charges would be left dangling.'
                ) % rec.reservation_number)
            old_state = rec.state
            rec.state = 'cancelled'
            if old_state == 'confirmed' and rec.room_id:
                if rec.room_id.status == 'occupied':
                    rec.room_id.action_set_dirty()

    def action_reset_draft(self):
        """Reset cancelled / no-show back to draft."""
        for rec in self:
            if rec.state not in ('cancelled', 'no_show'):
                raise UserError(_('Only cancelled or no-show reservations can be reset to draft.'))
            rec.state = 'draft'

    def action_exit(self):
        """Leave the booking screen: back to the Reception Dashboard
        (falls back to the reservations list if reporting is not installed)."""
        try:
            return self.env['ir.actions.actions']._for_xml_id(
                'hotel_reporting.action_reception_dashboard')
        except ValueError:
            return self.env['ir.actions.actions']._for_xml_id(
                'hotel_frontdesk.action_hotel_reservation')

    # ── Write guard (spec §3.1: cannot modify CHECKED_OUT) ──────────────
    _PROTECTED_AFTER_CHECKOUT = (
        'room_id', 'room_type_id', 'checkin_date', 'checkout_date',
        'nightly_rate', 'rate_plan_id', 'guest_id',
    )

    # Fields whose amendment changes what the folio's room charges should be.
    _ROOM_CHARGE_FIELDS = (
        'checkin_date', 'checkout_date', 'room_id', 'room_type_id',
        'rate_plan_id', 'combo_id', 'nightly_rate',
    )

    def write(self, vals):
        protected = set(vals) & set(self._PROTECTED_AFTER_CHECKOUT)
        if protected and not self.env.context.get('bypass_checkout_guard'):
            locked = self.filtered(lambda r: r.state == 'checked_out')
            if locked:
                raise UserError(_(
                    'Reservation(s) %s are checked out and can no longer be '
                    'modified (fields: %s).'
                ) % (', '.join(locked.mapped('reservation_number')),
                     ', '.join(sorted(protected))))
        # Snapshot in-house reservations before the write: the resync needs
        # the OLD room name to catch legacy lines with no reservation_id.
        resync = self.browse()
        old_rooms = {}
        if set(vals) & set(self._ROOM_CHARGE_FIELDS):
            resync = self.filtered(lambda r: r.state == 'checked_in')
            old_rooms = {r.id: r.room_id.name for r in resync}
        res = super().write(vals)
        if 'combo_id' in vals:
            self._sync_combo_services()
        for rec in resync:
            rec._resync_room_charges(old_room_name=old_rooms.get(rec.id))
        return res

    def _resync_room_charges(self, old_room_name=None):
        """Regenerate the folio's room-charge lines after an amendment.

        Dates, room or rate of a checked-in reservation changed: without
        this, the folio keeps the charges posted at check-in and the
        check-out balance guard clears departure on a stale total.

        Runs with sudo, like every other folio side-effect reception
        triggers from a record it may write to.
        """
        self.ensure_one()
        folio = self._folio_for_charge_type('room').sudo()
        if not folio:
            return
        if folio.invoice_id:
            # An invoiced folio must not be rewritten silently — leave the
            # lines and put a loud note in the chatter instead.
            self.message_post(body=_(
                'Reservation amended after its folio %s was invoiced: room '
                'charges were NOT resynced. Adjust the invoice manually.'
            ) % folio.name)
            return
        own_lines = folio.line_ids.filtered(
            lambda l: l.charge_type == 'room' and (
                l.reservation_id == self
                # Legacy lines (posted before reservation_id existed):
                or (not l.reservation_id and folio.reservation_id == self)
                or (not l.reservation_id and not folio.reservation_id
                    and old_room_name
                    and l.name.startswith('Room %s — ' % old_room_name))
            ))
        own_lines.unlink()
        folio._generate_room_charges(self)
        self.message_post(body=_(
            'Stay amended while checked in: room charges regenerated '
            '(%(nights)s night(s), room %(room)s, %(ci)s → %(co)s).',
            nights=(self.checkout_date - self.checkin_date).days,
            room=self.room_id.name,
            ci=self.checkin_date.strftime('%d/%m/%Y'),
            co=self.checkout_date.strftime('%d/%m/%Y'),
        ))

    # ── No-show cron (spec §6.1) ─────────────────────────────────────────
    @api.model
    def _cron_mark_no_shows(self):
        """Mark confirmed reservations as NO_SHOW after the grace period.

        Grace = end of the check-in day in the company timezone: a guest
        who has not checked in by midnight after their arrival date is a
        no-show. Runs hourly; idempotent.
        """
        today = fields.Date.context_today(self)
        stale = self.search([
            ('state', '=', 'confirmed'),
            ('checkin_date', '<', today),
        ])
        for rec in stale:
            rec.state = 'no_show'
            rec.message_post(body=_(
                'Automatically marked as No Show: guest did not check in '
                'by end of %s.') % rec.checkin_date)
        return len(stale)

    # ── Pre-arrival reminder cron (spec §6.3) ───────────────────────────
    @api.model
    def _cron_send_prearrival_reminders(self):
        """Email tomorrow's confirmed arrivals a pre-arrival reminder."""
        template = self.env.ref(
            'hotel_frontdesk.mail_template_prearrival_reminder',
            raise_if_not_found=False,
        )
        if not template:
            return 0
        tomorrow = fields.Date.context_today(self) + timedelta(days=1)
        arrivals = self.search([
            ('state', '=', 'confirmed'),
            ('checkin_date', '=', tomorrow),
        ])
        sent = 0
        for rec in arrivals:
            if rec.guest_id.email:
                template.send_mail(rec.id)
                sent += 1
        return sent

    def action_send_confirmation_email(self):
        """Open custom email wizard pre-filled with confirmation template for preview/edit before sending."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Confirmation Email'),
            'res_model': 'hotel.reservation.email.wizard',
            'views': [(False, 'form')],
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_reservation_id': self.id},
        }

    def action_edit_confirmation_template(self):
        """Navigate to the confirmation email template for customization."""
        self.ensure_one()
        template = self.env.ref(
            'hotel_frontdesk.mail_template_reservation_confirmation',
            raise_if_not_found=False,
        )
        if not template:
            raise UserError(_('Confirmation email template not found.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mail.template',
            'res_id': template.id,
            'views': [(False, 'form')],
            'view_mode': 'form',
            'target': 'current',
        }


class HotelReservationPax(models.Model):
    """One line per guest name staying in the room of a reservation.

    Since each reservation maps to exactly one room, this gives a
    room-by-room record of every client name (pax) in the property,
    including for group bookings where each room is its own reservation.
    """
    _name = 'hotel.reservation.pax'
    _description = 'Reservation Guest (Pax)'
    _order = 'sequence, id'

    reservation_id = fields.Many2one(
        'hotel.reservation', string='Reservation',
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    name = fields.Char('Guest Name', required=True)
    pax_type = fields.Selection([
        ('adult', 'Adult'),
        ('child', 'Child'),
    ], string='Type', default='adult', required=True)
    id_number = fields.Char('ID / Passport #')
    nationality_id = fields.Many2one('res.country', string='Nationality')
    note = fields.Char('Note')

    room_id = fields.Many2one(
        related='reservation_id.room_id', string='Room', store=True,
    )
    checkin_date = fields.Date(
        related='reservation_id.checkin_date', store=True,
    )
    checkout_date = fields.Date(
        related='reservation_id.checkout_date', store=True,
    )
