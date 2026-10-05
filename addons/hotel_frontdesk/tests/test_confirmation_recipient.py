# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestConfirmationRecipient(TransactionCase):
    """Who the confirmation email goes to.

    Agency/corporate bookings notify the booker, but only when the booker
    has a usable address; everything else falls back to the guest.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env['hotel.reservation'])

        cls.room_type = cls.env['hotel.room.type'].create({
            'name': 'ZZ Mail Type',
            'capacity': 2,
            'base_rate': 1000000.0,
        })
        cls.room = cls.env['hotel.room'].create({
            'name': 'ZZ-M01',
            'room_type_id': cls.room_type.id,
            'status': 'available',
        })
        cls.guest = cls.env['res.partner'].create({
            'name': 'ZZ Mail Guest',
            'email': 'guest@example.com',
        })
        cls.agency = cls.env['res.partner'].create({
            'name': 'ZZ Mail Corp',
            'is_company': True,
            'is_hotel_agency': True,
            'hotel_account_type_id': cls.env.ref('hotel_frontdesk.account_type_corporate').id,
            'hotel_routing': 'room',
        })
        cls.booker = cls.env['res.partner'].create({
            'name': 'ZZ Booker',
            'parent_id': cls.agency.id,
            'email': 'booker@example.com',
        })

        cls.tmpl_direct = cls.env.ref(
            'hotel_frontdesk.mail_template_reservation_confirmation')
        cls.tmpl_corporate = cls.env.ref(
            'hotel_frontdesk.mail_template_reservation_confirmation_corporate')
        cls.tmpl_group_direct = cls.env.ref(
            'hotel_frontdesk.mail_template_group_booking_confirmation')
        cls.tmpl_group_corporate = cls.env.ref(
            'hotel_frontdesk.mail_template_group_booking_confirmation_corporate')

    def _make_reservation(self, **overrides):
        vals = {
            'guest_id': self.guest.id,
            'room_id': self.room.id,
            'room_type_id': self.room_type.id,
            'checkin_date': self.today,
            'checkout_date': self.today + timedelta(days=2),
            'nightly_rate': 1000000.0,
            'send_confirmation': False,
        }
        vals.update(overrides)
        return self.env['hotel.reservation'].create(vals)

    def _make_group(self, **overrides):
        vals = {
            'guest_id': self.guest.id,
            'checkin_date': self.today,
            'checkout_date': self.today + timedelta(days=2),
            'send_confirmation': False,
        }
        vals.update(overrides)
        return self.env['hotel.booking.group'].create(vals)

    # ── Reservations ─────────────────────────────────────────────────────

    def test_direct_booking_emails_the_guest(self):
        res = self._make_reservation()
        template, recipient = res._get_confirmation_template()

        self.assertEqual(template, self.tmpl_direct)
        self.assertEqual(recipient, 'guest@example.com')

    def test_agency_booking_with_valid_booker_email_goes_to_the_booker(self):
        res = self._make_reservation(
            agency_id=self.agency.id, booker_id=self.booker.id)
        template, recipient = res._get_confirmation_template()

        self.assertEqual(template, self.tmpl_corporate)
        self.assertEqual(recipient, 'booker@example.com')

    def test_agency_booking_without_booker_email_falls_back_to_the_guest(self):
        """No address anywhere on the agency side: the guest is notified."""
        silent = self.env['res.partner'].create({
            'name': 'ZZ Silent Booker', 'parent_id': self.agency.id,
        })
        res = self._make_reservation(
            agency_id=self.agency.id, booker_id=silent.id)
        self.assertFalse(res.booker_email)

        template, recipient = res._get_confirmation_template()
        self.assertEqual(template, self.tmpl_direct)
        self.assertEqual(recipient, 'guest@example.com')

    def test_agency_booking_with_malformed_booker_email_falls_back(self):
        """A booker address that is not an address is not a recipient."""
        bad = self.env['res.partner'].create({
            'name': 'ZZ Bad Booker', 'parent_id': self.agency.id,
            'email': 'not an email',
        })
        res = self._make_reservation(
            agency_id=self.agency.id, booker_id=bad.id)

        template, recipient = res._get_confirmation_template()
        self.assertEqual(template, self.tmpl_direct)
        self.assertEqual(recipient, 'guest@example.com')

    def test_agency_email_stands_in_when_no_booker_is_named(self):
        """booker_email already falls back to the agency's own address."""
        self.agency.email = 'reservations@corp.example.com'
        res = self._make_reservation(agency_id=self.agency.id)

        template, recipient = res._get_confirmation_template()
        self.assertEqual(template, self.tmpl_corporate)
        self.assertEqual(recipient, 'reservations@corp.example.com')

    def test_confirming_an_agency_booking_mails_the_booker(self):
        """End to end: the mail actually leaves addressed to the booker."""
        res = self._make_reservation(
            agency_id=self.agency.id, booker_id=self.booker.id,
            send_confirmation=True)
        before = self.env['mail.mail'].search([])
        res.action_confirm()
        sent = self.env['mail.mail'].search([]) - before

        self.assertTrue(sent, 'no confirmation mail was created')
        self.assertIn('booker@example.com', sent[0].email_to)

    def test_confirming_falls_back_to_the_guest_address(self):
        silent = self.env['res.partner'].create({
            'name': 'ZZ Silent Booker 2', 'parent_id': self.agency.id,
        })
        res = self._make_reservation(
            agency_id=self.agency.id, booker_id=silent.id,
            send_confirmation=True)
        before = self.env['mail.mail'].search([])
        res.action_confirm()
        sent = self.env['mail.mail'].search([]) - before

        self.assertTrue(sent, 'no confirmation mail was created')
        self.assertIn('guest@example.com', sent[0].email_to)

    def test_email_wizard_prefills_the_chosen_recipient(self):
        res = self._make_reservation(
            agency_id=self.agency.id, booker_id=self.booker.id)
        wizard = self.env['hotel.reservation.email.wizard'].with_context(
            default_reservation_id=res.id).create({'reservation_id': res.id})
        self.assertEqual(wizard.email_to, 'booker@example.com')

    # ── Group bookings ───────────────────────────────────────────────────

    def test_direct_group_emails_the_leader(self):
        group = self._make_group()
        template, recipient = group._get_confirmation_template()

        self.assertEqual(template, self.tmpl_group_direct)
        self.assertEqual(recipient, 'guest@example.com')

    def test_agency_group_with_valid_booker_email_goes_to_the_booker(self):
        group = self._make_group(
            agency_id=self.agency.id, booker_id=self.booker.id)
        template, recipient = group._get_confirmation_template()

        self.assertEqual(template, self.tmpl_group_corporate)
        self.assertEqual(recipient, 'booker@example.com')

    def test_agency_group_without_booker_email_falls_back_to_the_leader(self):
        silent = self.env['res.partner'].create({
            'name': 'ZZ Silent Group Booker', 'parent_id': self.agency.id,
        })
        group = self._make_group(
            agency_id=self.agency.id, booker_id=silent.id)

        template, recipient = group._get_confirmation_template()
        self.assertEqual(template, self.tmpl_group_direct)
        self.assertEqual(recipient, 'guest@example.com')

    def test_manual_group_send_only_complains_when_nobody_has_an_address(self):
        mute = self.env['res.partner'].create({'name': 'ZZ Mute Leader'})
        silent = self.env['res.partner'].create({
            'name': 'ZZ Silent Group Booker 2', 'parent_id': self.agency.id,
        })
        group = self._make_group(
            guest_id=mute.id, agency_id=self.agency.id, booker_id=silent.id)

        with self.assertRaises(UserError):
            group.action_send_confirmation_email()
