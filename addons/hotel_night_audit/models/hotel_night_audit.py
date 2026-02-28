# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import date, timedelta

_logger = logging.getLogger(__name__)


class HotelNightAudit(models.Model):
    _name = 'hotel.night.audit'
    _description = 'Hotel Night Audit Snapshot'
    _order = 'date desc'
    _rec_name = 'date'

    date = fields.Date('Audit Date', required=True, readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
        ('locked', 'Locked'),
    ], string='Status', default='draft', readonly=True)

    # KPI Snapshot
    total_rooms = fields.Integer('Total Rooms', readonly=True)
    occupied_rooms = fields.Integer('Occupied Rooms', readonly=True)
    occupancy_pct = fields.Float('Occupancy %', digits=(5, 1), readonly=True)
    total_revenue = fields.Float('Total Revenue', digits=(16, 2), readonly=True)
    room_revenue = fields.Float('Room Revenue', digits=(16, 2), readonly=True)
    fnb_revenue = fields.Float('F&B Revenue', digits=(16, 2), readonly=True)
    service_revenue = fields.Float('Service Revenue', digits=(16, 2), readonly=True)
    adr = fields.Float('ADR (Avg Daily Rate)', digits=(16, 2), readonly=True)
    revpar = fields.Float('RevPAR', digits=(16, 2), readonly=True)

    # Payment method split
    payment_cash = fields.Float('Cash Payments', digits=(16, 2), readonly=True)
    payment_card = fields.Float('Card Payments', digits=(16, 2), readonly=True)
    payment_bank = fields.Float('Bank Transfer', digits=(16, 2), readonly=True)

    # Flagged issues
    unpaid_folio_count = fields.Integer('Unpaid Folios', readonly=True)
    posted_invoice_count = fields.Integer('Invoices Posted', readonly=True)

    notes = fields.Text('Notes')

    _date_uniq = models.Constraint('UNIQUE(date)', 'Night audit already exists for this date!')

    # ═══════════════════════════════════════════════════════════════════
    # CRON ENTRY POINT — called by ir.cron at 02:00 AM daily
    # ═══════════════════════════════════════════════════════════════════

    @api.model
    def _cron_run_night_audit(self):
        """Automated night audit — runs daily at 02:00 AM."""
        audit_date = date.today() - timedelta(days=1)  # Audit yesterday
        _logger.info('Hotel Night Audit: Starting audit for %s', audit_date)

        # Check if already done
        existing = self.search([('date', '=', audit_date), ('state', '!=', 'draft')], limit=1)
        if existing:
            _logger.info('Night audit for %s already completed. Skipping.', audit_date)
            return

        try:
            # Step 1: Auto-post draft invoices from audit day
            posted_count = self._post_draft_invoices(audit_date)

            # Step 2: Flag unpaid folios
            unpaid_count = self._flag_unpaid_folios(audit_date)

            # Step 3: Calculate KPI snapshot
            snapshot = self._calculate_snapshot(audit_date)

            # Step 4: Create or update audit record
            audit = self.search([('date', '=', audit_date)], limit=1)
            vals = {
                'date': audit_date,
                'state': 'done',
                'posted_invoice_count': posted_count,
                'unpaid_folio_count': unpaid_count,
                **snapshot,
            }
            if audit:
                audit.write(vals)
            else:
                audit = self.create(vals)

            # Step 5: Lock previous day — prevent edits to older audits
            self._lock_previous_audits(audit_date)

            # Step 6: Send admin email summary
            self._send_admin_email(audit)

            _logger.info(
                'Night audit for %s completed: Occupancy=%.1f%%, Revenue=%s, Unpaid=%d',
                audit_date, snapshot['occupancy_pct'],
                snapshot['total_revenue'], unpaid_count
            )

        except Exception as e:
            _logger.error('Night audit failed for %s: %s', audit_date, str(e))
            raise

    # ═══════════════════════════════════════════════════════════════════
    # AUDIT SUB-STEPS
    # ═══════════════════════════════════════════════════════════════════

    @api.model
    def _post_draft_invoices(self, audit_date):
        """Find all draft invoices from audit_date and post them."""
        draft_invoices = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'draft'),
            ('invoice_date', '<=', audit_date),
        ])
        count = len(draft_invoices)
        if draft_invoices:
            draft_invoices.action_post()
            _logger.info('Posted %d draft invoices for %s', count, audit_date)
        return count

    @api.model
    def _flag_unpaid_folios(self, audit_date):
        """Count folios from audit_date that are still open (no payment)."""
        unpaid = self.env['hotel.folio'].search([
            ('payment_state', '=', 'open'),
            ('create_date', '<=', fields.Datetime.to_string(
                fields.Datetime.now().replace(
                    year=audit_date.year, month=audit_date.month,
                    day=audit_date.day, hour=23, minute=59, second=59
                )
            )),
        ])
        if unpaid:
            _logger.warning(
                'Night audit: %d unpaid folios detected for %s: %s',
                len(unpaid), audit_date,
                ', '.join(unpaid.mapped('name'))
            )
        return len(unpaid)

    @api.model
    def _calculate_snapshot(self, audit_date):
        """Calculate all KPI metrics for the audit date."""
        Room = self.env['hotel.room']
        Reservation = self.env['hotel.reservation']
        FolioLine = self.env['hotel.folio.line']

        total_rooms = Room.search_count([('active', '=', True)])

        # Rooms that were occupied on audit_date
        occupied_reservations = Reservation.search([
            ('state', 'in', ['checked_in', 'checked_out']),
            ('checkin_date', '<=', audit_date),
            ('checkout_date', '>', audit_date),
        ])
        occupied_rooms = len(set(occupied_reservations.mapped('room_id').ids))

        occupancy_pct = (occupied_rooms / total_rooms * 100) if total_rooms else 0

        # Revenue from folio lines on audit date
        next_day = audit_date + timedelta(days=1)
        day_start = fields.Datetime.to_string(
            fields.Datetime.now().replace(
                year=audit_date.year, month=audit_date.month,
                day=audit_date.day, hour=0, minute=0, second=0
            )
        )
        day_end = fields.Datetime.to_string(
            fields.Datetime.now().replace(
                year=next_day.year, month=next_day.month,
                day=next_day.day, hour=0, minute=0, second=0
            )
        )

        day_lines = FolioLine.search([
            ('create_date', '>=', day_start),
            ('create_date', '<', day_end),
        ])

        room_revenue = sum(day_lines.filtered(lambda l: l.charge_type == 'room').mapped('subtotal'))
        fnb_revenue = sum(day_lines.filtered(lambda l: l.charge_type == 'fnb').mapped('subtotal'))
        service_revenue = sum(day_lines.filtered(
            lambda l: l.charge_type in ('service', 'manual')
        ).mapped('subtotal'))
        total_revenue = room_revenue + fnb_revenue + service_revenue

        adr = (room_revenue / occupied_rooms) if occupied_rooms else 0
        revpar = (room_revenue / total_rooms) if total_rooms else 0

        # Payment method split from invoices
        payment_cash = 0
        payment_card = 0
        payment_bank = 0

        payments = self.env['account.payment'].search([
            ('date', '=', audit_date),
            ('state', '=', 'posted'),
        ])
        for payment in payments:
            journal = payment.journal_id
            if journal.type == 'cash':
                payment_cash += payment.amount
            elif journal.type == 'bank':
                # Try to distinguish card from bank based on journal name
                if 'card' in (journal.name or '').lower():
                    payment_card += payment.amount
                else:
                    payment_bank += payment.amount
            else:
                payment_bank += payment.amount

        return {
            'total_rooms': total_rooms,
            'occupied_rooms': occupied_rooms,
            'occupancy_pct': round(occupancy_pct, 1),
            'total_revenue': total_revenue,
            'room_revenue': room_revenue,
            'fnb_revenue': fnb_revenue,
            'service_revenue': service_revenue,
            'adr': round(adr, 0),
            'revpar': round(revpar, 0),
            'payment_cash': payment_cash,
            'payment_card': payment_card,
            'payment_bank': payment_bank,
        }

    @api.model
    def _lock_previous_audits(self, audit_date):
        """Lock all completed audits before audit_date."""
        old_audits = self.search([
            ('date', '<', audit_date),
            ('state', '=', 'done'),
        ])
        if old_audits:
            old_audits.write({'state': 'locked'})
            _logger.info('Locked %d previous audit records', len(old_audits))

    def _send_admin_email(self, audit):
        """Send the night audit summary email to all admin users."""
        template = self.env.ref(
            'hotel_night_audit.mail_template_night_audit_summary',
            raise_if_not_found=False,
        )
        if not template:
            _logger.warning('Night audit email template not found, skipping email.')
            return

        admin_group = self.env.ref('hotel_core.group_hotel_admin', raise_if_not_found=False)
        if not admin_group:
            return

        admin_users = admin_group.user_ids
        for user in admin_users:
            if user.partner_id.email:
                template.send_mail(audit.id, force_send=True,
                                   email_values={'email_to': user.partner_id.email})
                _logger.info('Night audit email sent to %s', user.partner_id.email)
