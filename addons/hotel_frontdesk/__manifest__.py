# -*- coding: utf-8 -*-
{
    'name': 'Hotel Front Desk',
    'version': '19.0.1.0.0',
    'category': 'Hotel Management',
    'summary': 'Reservations, check-in/out, folios, invoicing',
    'description': """
Hotel Front Desk
================
Core PMS operations:
- Reservation management with full state machine
- Folio creation & charge tracking
- Check-in / Check-out workflows
- Invoice generation (account.move)
- Email confirmation templates
    """,
    'author': 'Hotel PMS Team',
    'depends': ['hotel_core', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'data/hotel_frontdesk_sequence.xml',
        'data/hotel_mail_template.xml',
        'wizards/hotel_add_charge_wizard_views.xml',
        'views/hotel_reservation_views.xml',
        'views/hotel_folio_views.xml',
        'views/hotel_frontdesk_menu.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
    'sequence': 2,
}
