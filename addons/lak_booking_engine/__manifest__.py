# -*- coding: utf-8 -*-
{
    'name': "LAK Tented Camp - Website Booking Engine",
    'version': '19.0.2.0.0',
    'category': 'Hotel Management',
    'summary': 'Public availability & price search for the camp website, '
               'answered from the PMS itself',
    'description': """
Phase 1 of the direct booking engine: a read-only search API.

    GET /api/book/search?checkin=YYYY-MM-DD&checkout=YYYY-MM-DD&adults=2&children=0[&lang=vi]

returns, per sellable room type, whether the party fits, how many rooms of
that type it needs, the price of every night and the total in VND -- priced
by building the exact reservation the booking step will create and reading
its ``total_amount``, so the quote cannot drift from what the folio charges.

Inventory is counted by ``hotel.availability``, which treats drafts as held
(website holds will be drafts), subtracts room-less bookings from their room
type, spreads unassigned Run-of-House bookings over the roomiest type, and
honours maintenance windows.

Phase 2 (bank transfer): ``POST /api/book/hold`` turns an accepted quote into
draft reservations with rooms assigned, held for ``hold_hours`` while the guest
transfers the money to the MB Bank account. Reception confirms the payment by
hand (Front Desk > Website Bookings), which confirms the stay and records one
payment per room on its folio. ``/book`` is a plain test page for the flow.

Odoo stays the only inventory.

Inert until `lak_booking_engine.enabled` is set to 1.
""",
    'author': 'LAK Tented Camp',
    'depends': ['hotel_core', 'hotel_frontdesk', 'mail', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'data/booking_engine_data.xml',
        'data/mail_templates.xml',
        'data/booking_cron.xml',
        'views/hotel_room_type_views.xml',
        'views/booking_hold_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
