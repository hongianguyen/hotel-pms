# -*- coding: utf-8 -*-
"""A website booking waiting for its money.

The guest picks an offer on the website, gives a name and an email, and gets
a hold: the rooms are booked as DRAFT reservations with concrete rooms
assigned, so every seller (website, Aiosell, reception's board) sees them as
taken, and the guest is told how to pay.

Bank transfer is confirmed by hand: MB Bank tells Odoo nothing, so reception
checks the bank app for the hold's reference and clicks Confirm Payment. That
confirms the reservations, opens their folios and records the money on them.
An unpaid hold is released by the expiry cron after ``hold_hours``.

The quote token the website sends back is only a pointer to what was shown.
Availability and price are worked out again here, under a lock, and the
amount asked for is the total of the reservations actually saved.
"""
import logging
import re
import secrets
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import formatLang

from .booking_quote import BookingInputError, MAX_ROOMS

_logger = logging.getLogger(__name__)

# No 0/O or 1/I/L: a reference is copied into a bank memo by hand and read
# back off a bank statement by eye.
REF_ALPHABET = '23456789ABCDEFGHJKMNPQRSTUVWXYZ'
REF_PREFIX = 'LAK'
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
PHONE_RE = re.compile(r'^\+?[0-9 ().-]{6,20}$')


class LakBookingHold(models.Model):
    _name = 'lak.booking.hold'
    _description = 'Website Booking (awaiting payment)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char('Reference', required=True, readonly=True, copy=False, index=True)
    access_token = fields.Char(readonly=True, copy=False, groups='base.group_system')
    state = fields.Selection([
        ('pending', 'Awaiting Payment'),
        ('confirmed', 'Confirmed'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ], default='pending', required=True, readonly=True, tracking=True, index=True)
    payment_method = fields.Selection([
        ('bank', 'Bank Transfer'),
        ('paypal', 'PayPal'),
    ], default='bank', required=True, readonly=True)

    guest_id = fields.Many2one('res.partner', 'Guest', readonly=True, required=True)
    guest_name = fields.Char('Name Given', readonly=True)
    guest_email = fields.Char('Email Given', readonly=True)
    guest_phone = fields.Char('Phone Given', readonly=True)
    note = fields.Text('Guest Note', readonly=True)
    lang = fields.Char(readonly=True)

    room_type_id = fields.Many2one('hotel.room.type', 'Room Type', readonly=True, required=True)
    checkin_date = fields.Date('Check-in', readonly=True, required=True)
    checkout_date = fields.Date('Check-out', readonly=True, required=True)
    adults = fields.Integer(readonly=True)
    children = fields.Integer(readonly=True)
    room_count = fields.Integer('Rooms', readonly=True)
    reservation_ids = fields.One2many('hotel.reservation', 'lak_hold_id', 'Reservations', readonly=True)

    amount = fields.Float('Amount Due', digits=(16, 2), readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True,
                                  default=lambda self: self.env.company.currency_id)
    expires_at = fields.Datetime('Hold Expires', readonly=True, index=True)
    confirmed_at = fields.Datetime(readonly=True)
    confirmed_by = fields.Many2one('res.users', readonly=True)
    client_ip = fields.Char('Client IP', readonly=True)

    amount_display = fields.Char(compute='_compute_display')
    qr_url = fields.Char('VietQR Image', compute='_compute_display')
    expires_display = fields.Char(compute='_compute_display')
    expiring_soon = fields.Boolean(compute='_compute_expiring_soon', search='_search_expiring_soon')

    _name_uniq = models.Constraint('UNIQUE(name)', 'Booking reference must be unique.')

    # ── Settings ───────────────────────────────────────────────────────
    @api.model
    def _param(self, key, default=''):
        return (self.env['ir.config_parameter'].sudo()
                .get_param('lak_booking_engine.%s' % key) or default).strip()

    @api.model
    def _int_param(self, key, default):
        try:
            return int(self._param(key, str(default)))
        except ValueError:
            return default

    @api.model
    def bank_details(self):
        """What the guest is told to pay into. The account holder and bank
        come from the account recorded in Odoo, so they cannot disagree with
        the books; only the number is a setting."""
        number = self._param('bank_account')
        bank = self.env['res.partner.bank'].sudo().search(
            [('acc_number', '=', number)], limit=1)
        return {
            'bank_name': bank.bank_id.name or self._param('bank_name', 'MB Bank'),
            'bank_bin': self._param('bank_bin', '970422'),
            'account_number': number,
            'account_holder': bank.acc_holder_name or bank.partner_id.name
                              or self.env.company.name,
            'swift': bank.bank_id.bic or '',
        }

    @api.model
    def _bank_journal(self):
        number = self._param('bank_account')
        Journal = self.env['account.journal'].sudo()
        journal = Journal.search([
            ('type', '=', 'bank'),
            ('bank_account_id.acc_number', '=', number),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not journal:
            raise UserError(_(
                'No bank journal is linked to account %s. Set the bank account '
                'on the journal the transfers land in.', number))
        return journal

    # ── Display ────────────────────────────────────────────────────────
    @api.depends('amount', 'name', 'expires_at')
    def _compute_display(self):
        bank = self.bank_details()
        holder = _ascii_upper(bank['account_holder'])
        for hold in self:
            currency = hold.currency_id or self.env.company.currency_id
            hold.amount_display = formatLang(self.env, hold.amount, currency_obj=currency)
            hold.qr_url = (
                'https://img.vietqr.io/image/%s-%s-compact2.png?amount=%d&addInfo=%s&accountName=%s'
                % (bank['bank_bin'], bank['account_number'], round(hold.amount),
                   hold.name, _urlquote(holder))
            ) if hold.name and bank['account_number'] else False
            if hold.expires_at:
                local = fields.Datetime.context_timestamp(
                    hold.with_context(tz='Asia/Ho_Chi_Minh'), hold.expires_at)
                hold.expires_display = local.strftime('%d/%m/%Y %H:%M') + ' (GMT+7)'
            else:
                hold.expires_display = False

    def _soon_limit(self):
        return fields.Datetime.now() + timedelta(hours=4)

    @api.depends('state', 'expires_at')
    def _compute_expiring_soon(self):
        limit = self._soon_limit()
        for hold in self:
            hold.expiring_soon = bool(
                hold.state == 'pending' and hold.expires_at and hold.expires_at <= limit)

    def _search_expiring_soon(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_('Unsupported search.'))
        domain = [('state', '=', 'pending'), ('expires_at', '<=', self._soon_limit())]
        positive = (operator == '=') == value
        return domain if positive else ['!', '&'] + domain

    # ── Creation from the website ──────────────────────────────────────
    @api.model
    def _new_ref(self):
        for _i in range(20):
            ref = REF_PREFIX + ''.join(secrets.choice(REF_ALPHABET) for _j in range(6))
            if not self.sudo().search_count([('name', '=', ref)]):
                return ref
        raise UserError(_('Could not allocate a booking reference.'))

    @api.model
    def _clean_guest(self, guest):
        guest = guest if isinstance(guest, dict) else {}
        name = ' '.join(str(guest.get('name') or '').split())[:100]
        email = str(guest.get('email') or '').strip().lower()[:120]
        phone = str(guest.get('phone') or '').strip()[:30]
        note = str(guest.get('note') or '').strip()[:1000]
        if len(name) < 2:
            raise BookingInputError('bad_guest', 'Please give the guest\'s full name.')
        if not EMAIL_RE.match(email):
            raise BookingInputError('bad_guest', 'Please give a valid email address.')
        if phone and not PHONE_RE.match(phone):
            raise BookingInputError('bad_guest', 'Please give a valid phone number.')
        return name, email, phone, note

    @api.model
    def _guest_partner(self, name, email, phone):
        """An existing person with this email, else a new one. What the web
        form says is never written onto an existing partner: anyone can type
        anyone's email address."""
        Partner = self.env['res.partner'].sudo()
        partner = Partner.search([
            ('email', '=ilike', email), ('is_company', '=', False),
        ], order='id', limit=1)
        if partner:
            return partner
        return Partner.create({'name': name, 'email': email, 'phone': phone or False})

    @api.model
    def _website_source(self):
        Source = self.env['hotel.booking.source'].sudo()
        return Source.search([('name', '=ilike', 'Website direct')], limit=1) \
            or Source.create({'name': 'Website direct'})

    @api.model
    def _check_caps(self, email, ip, rooms):
        """Holds take no money, so without caps a script could tie up the
        whole camp for a day. Counted before the lock is taken."""
        pending = self.sudo().search([('state', '=', 'pending')])
        if len(pending.filtered(lambda h: h.guest_email == email)) >= self._int_param('max_pending_per_email', 2):
            raise BookingInputError('too_many_holds', 'You already have bookings awaiting payment. '
                                    'Please pay or contact us before booking again.')
        if ip and len(pending.filtered(lambda h: h.client_ip == ip)) >= self._int_param('max_pending_per_ip', 3):
            raise BookingInputError('too_many_holds', 'Too many unpaid bookings from this connection. '
                                    'Please contact us.')
        if sum(pending.mapped('room_count')) + rooms > self._int_param('max_pending_rooms', 10):
            raise BookingInputError('busy', 'Online booking is very busy right now. '
                                    'Please contact us to book.')

    @api.model
    def _lock_and_pick_rooms(self, room_type, checkin, checkout, rooms_needed):
        """Concrete free rooms of `room_type` for the whole stay, picked while
        every room row is locked.

        All rooms, not just this type's: Run-of-House bookings without a room
        are charged against whichever type has most left, so another type's
        hold can change this type's count. Locked in id order, the same order
        hotel.reservation's own check uses, so the two cannot deadlock.
        Reservation's constraint ignores drafts, so without this lock two
        holds could both be given the same room.
        """
        self.env.cr.execute(
            'SELECT id FROM hotel_room WHERE active ORDER BY id FOR UPDATE')
        Availability = self.env['hotel.availability']
        free = Availability.free_for_stay(checkin, checkout, draft_holds=True)
        if free.get(room_type.id, 0) < rooms_needed:
            return None
        taken = self.env['hotel.reservation'].sudo().search([
            ('room_id', '!=', False),
            ('state', 'in', ('draft', 'confirmed', 'checked_in')),
            ('checkin_date', '<', checkout),
            ('checkout_date', '>', checkin),
        ]).room_id
        candidates = self.env['hotel.room'].sudo().search([
            ('room_type_id', '=', room_type.id), ('active', '=', True),
        ], order='name, id') - taken
        nights = []
        day = checkin
        while day < checkout:
            nights.append(day)
            day += timedelta(days=1)
        usable = candidates.filtered(lambda r: not any(
            Availability._room_out_of_service(r, d) for d in nights))
        if len(usable) < rooms_needed:
            return None
        return usable[:rooms_needed]

    @api.model
    def create_from_web(self, payload, client_ip=None, lang=None):
        """Turn a quote the guest accepted into a hold. Returns the public
        view of the hold, or raises BookingInputError."""
        payload = payload if isinstance(payload, dict) else {}
        Quote = self.env['lak.booking.quote']
        token = Quote.read_quote_token(payload.get('quote'))
        if not token:
            raise BookingInputError('quote_expired', 'This offer has expired. Please search again.')
        method = payload.get('payment_method') or 'bank'
        if method != 'bank':
            raise BookingInputError('bad_method', 'This payment method is not available yet.')
        name, email, phone, note = self._clean_guest(payload.get('guest'))

        checkin, checkout, _nights, adults, children = Quote._parse_stay(
            token.get('checkin'), token.get('checkout'),
            token.get('adults'), token.get('children'))
        room_type = self.env['hotel.room.type'].sudo().browse(int(token.get('room_type_id') or 0)).exists()
        rooms_needed = int(token.get('rooms') or 0)
        if (not room_type or not room_type.active or room_type.is_roh
                or not room_type.website_bookable or not 1 <= rooms_needed <= MAX_ROOMS):
            raise BookingInputError('not_available', 'This room is no longer available. Please search again.')
        split = Quote._party_split(adults, children, rooms_needed)
        if not split:
            raise BookingInputError('bad_party', 'Each room needs at least one adult.')

        self._check_caps(email, client_ip, rooms_needed)

        rooms = self._lock_and_pick_rooms(room_type, checkin, checkout, rooms_needed)
        if not rooms:
            raise BookingInputError('not_available', 'Sorry, this room was just taken. Please search again.')

        guest = self._guest_partner(name, email, phone)
        source = self._website_source()
        ref = self._new_ref()
        Reservation = self.env['hotel.reservation'].sudo()
        vals_list = []
        for room, (a, c) in zip(rooms, split):
            vals = Quote._reservation_vals(room_type, checkin, checkout, a, c)
            vals.update({
                'guest_id': guest.id,
                'room_id': room.id,
                'source_id': source.id,
                'payment_required': True,
                'send_confirmation': False,
                'notes': _('Website booking %(ref)s, awaiting bank transfer.%(note)s',
                           ref=ref, note=('\n' + note) if note else ''),
            })
            vals_list.append(vals)
        reservations = Reservation.create(vals_list)

        # The amount asked for is what was saved, never what the token says;
        # if the two differ the price moved since the search.
        amount = sum(reservations.mapped('total_amount'))
        currency = self.env.company.currency_id
        if amount <= 0 or currency.compare_amounts(amount, float(token.get('total') or 0)) != 0:
            raise BookingInputError('price_changed', 'The price of this room has changed. Please search again.')

        hold = self.sudo().create({
            'name': ref,
            'access_token': secrets.token_urlsafe(24),
            'payment_method': method,
            'guest_id': guest.id,
            'guest_name': name,
            'guest_email': email,
            'guest_phone': phone,
            'note': note,
            'lang': lang or 'en_US',
            'room_type_id': room_type.id,
            'checkin_date': checkin,
            'checkout_date': checkout,
            'adults': adults,
            'children': children,
            'room_count': rooms_needed,
            'amount': amount,
            'currency_id': currency.id,
            'expires_at': fields.Datetime.now() + timedelta(hours=self._int_param('hold_hours', 24)),
            'client_ip': client_ip,
        })
        reservations.write({'lak_hold_id': hold.id})
        hold._send('mail_template_hold_instructions')
        hold._notify_reception()
        return hold.public_view()

    def public_view(self):
        """All the guest's page may know about a hold."""
        self.ensure_one()
        bank = self.bank_details()
        return {
            'reference': self.name,
            'token': self.sudo().access_token,
            'state': self.state,
            'payment_method': self.payment_method,
            'room_type': self.room_type_id.with_context(lang=self.lang or 'en_US').name,
            'rooms': self.room_count,
            'checkin': self.checkin_date.isoformat(),
            'checkout': self.checkout_date.isoformat(),
            'adults': self.adults,
            'children': self.children,
            'amount': self.amount,
            'currency': self.currency_id.name,
            'expires_at': fields.Datetime.to_string(self.expires_at) + 'Z',
            'expires_display': self.expires_display,
            'bank': dict(bank, transfer_note=self.name),
            'qr_url': self.qr_url,
        }

    @api.model
    def find_public(self, ref, token):
        hold = self.sudo().search([('name', '=', (ref or '').strip().upper())], limit=1)
        if not hold or not token or not secrets.compare_digest(hold.access_token or '', str(token)):
            return None
        return hold

    # ── Messages ───────────────────────────────────────────────────────
    def _send(self, xmlid):
        template = self.env.ref('lak_booking_engine.%s' % xmlid, raise_if_not_found=False)
        for hold in self:
            if template and hold.guest_email:
                template.sudo().with_context(lang=hold.lang or 'en_US').send_mail(
                    hold.id, force_send=True)

    def _notify_reception(self):
        """A to-do for reception: watch the bank app for this reference."""
        group = self.env.ref('hotel_core.group_hotel_reception', raise_if_not_found=False)
        user = (group.user_ids.filtered(lambda u: u.active and not u.share)[:1]
                if group else self.env['res.users']) or self.env.ref('base.user_admin')
        for hold in self:
            hold.sudo().activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=fields.Date.context_today(hold),
                summary=_('Check bank for %(ref)s: %(amount)s', ref=hold.name, amount=hold.amount_display),
                note=_('Website booking awaiting bank transfer to MB %(acct)s with note %(ref)s. '
                       'When the money is in, open the booking and click Confirm Payment.',
                       acct=hold.bank_details()['account_number'], ref=hold.name),
                user_id=user.id,
            )

    # ── Reception ──────────────────────────────────────────────────────
    def action_confirm_payment(self):
        """The money is in the bank: confirm the stay and record it."""
        Wizard = self.env['hotel.folio.payment.wizard']
        journal = self._bank_journal()
        for hold in self:
            if hold.state != 'pending':
                raise UserError(_('Only bookings awaiting payment can be confirmed.'))
            reservations = hold.reservation_ids
            if not reservations or any(r.state != 'draft' for r in reservations):
                raise UserError(_(
                    'The reservations of %s are no longer drafts. Open them and '
                    'confirm or record the payment there.', hold.name))
            reservations.with_context(skip_confirmation_email=True).action_confirm()
            # One payment per room, on that room's own folio: check-in judges
            # each reservation by its own folios, so a lump sum on the first
            # folio would leave the other rooms barred at the desk.
            for res in reservations:
                Wizard.create({
                    'folio_id': res.folio_id.id,
                    'partner_id': res.folio_id.bill_to_id.id or res.guest_id.id,
                    'amount': res.total_amount,
                    'journal_id': journal.id,
                    'communication': '%s %s' % (hold.name, res.reservation_number),
                }).action_register_payment()
            hold.write({
                'state': 'confirmed',
                'confirmed_at': fields.Datetime.now(),
                'confirmed_by': self.env.user.id,
            })
            hold.activity_feedback(['mail.mail_activity_data_todo'],
                                   feedback=_('Payment received, booking confirmed.'))
            hold._send('mail_template_hold_confirmed')
        return True

    def action_cancel(self):
        for hold in self:
            if hold.state != 'pending':
                raise UserError(_('Only bookings awaiting payment can be cancelled here.'))
            hold._release()
            hold.state = 'cancelled'
            hold.activity_unlink(['mail.mail_activity_data_todo'])
        return True

    def action_view_reservations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reservations'),
            'res_model': 'hotel.reservation',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.reservation_ids.ids)],
        }

    def _release(self):
        """Cancel the hold's drafts. Never touches a reservation reception
        has already confirmed, or one with money on its folio."""
        for res in self.reservation_ids:
            if res.state == 'draft' and not res.folio_id.payment_ids:
                res.sudo().action_cancel()

    @api.model
    def _cron_expire_holds(self):
        holds = self.sudo().search([
            ('state', '=', 'pending'),
            ('expires_at', '<', fields.Datetime.now()),
        ])
        for hold in holds:
            live = hold.reservation_ids.filtered(lambda r: r.state != 'cancelled')
            if live and all(r.state != 'draft' for r in live):
                # Reception confirmed the rooms the ordinary way.
                hold.state = 'confirmed'
                continue
            hold._release()
            hold.state = 'expired'
            hold.activity_unlink(['mail.mail_activity_data_todo'])
            hold.message_post(body=_('No payment received in time: the rooms were released.'))
            hold._send('mail_template_hold_expired')
        return True


def _ascii_upper(text):
    import unicodedata
    text = (text or '').replace('Đ', 'D').replace('đ', 'd')
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    return ' '.join(text.upper().split())


def _urlquote(text):
    from urllib.parse import quote
    return quote(text, safe='')
