# -*- coding: utf-8 -*-
"""Shared fixtures for the Hotel PMS regression suite.

This suite exists to answer one question quickly after an Odoo major-version
upgrade: *did the reservation state machine and the money path still work?*
It is deliberately narrow — it covers the transitions and the totals, not the
UI. See UPGRADE_READINESS.md.
"""
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class HotelCommon(AccountTestInvoicingCommon):
    """Chart of accounts + a minimal but realistic property.

    Inherits AccountTestInvoicingCommon so that a sales journal and a usable
    chart exist regardless of what the target database has installed — folio
    invoicing needs both.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # AccountTestInvoicingCommon logs in as an accounting manager, who has
        # no hotel rights at all. Give the test user the hotel admin group so
        # the fixtures below exercise the real ACLs rather than running sudo.
        cls.env.user.group_ids |= cls.env.ref('hotel_core.group_hotel_admin')

        # The hotel sequences are bound to the live company, but this suite runs
        # in the throwaway company AccountTestInvoicingCommon builds. Without
        # this, next_by_code returns nothing and every record is numbered 'New'.
        cls.env['ir.sequence'].sudo().search([
            ('code', 'in', ['hotel.reservation', 'hotel.folio',
                            'hotel.booking.group', 'hotel.room']),
        ]).company_id = False

        cls.guest = cls.env['res.partner'].create({
            'name': 'Test Guest',
            'email': 'guest@example.com',
        })

        cls.room_type = cls.env['hotel.room.type'].create({
            'name': 'Test Lake View Tent',
            'capacity': 3,
            'base_rate': 1000000.0,
        })
        cls.room = cls.env['hotel.room'].create({
            'name': 'TEST01',
            'room_type_id': cls.room_type.id,
            'status': 'available',
        })
        cls.room_2 = cls.env['hotel.room'].create({
            'name': 'TEST02',
            'room_type_id': cls.room_type.id,
            'status': 'available',
        })

    @classmethod
    def _make_reservation(cls, checkin, checkout, room=None, **vals):
        """A draft reservation on `room` (defaults to the first test room)."""
        base = {
            'guest_id': cls.guest.id,
            'room_type_id': cls.room_type.id,
            'room_id': (room or cls.room).id,
            'checkin_date': checkin,
            'checkout_date': checkout,
            'send_confirmation': False,
        }
        base.update(vals)
        return cls.env['hotel.reservation'].create(base)
