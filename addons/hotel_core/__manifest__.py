# -*- coding: utf-8 -*-
{
    'name': 'Hotel Core',
    'version': '19.0.1.0.0',
    'category': 'Hotel Management',
    'summary': 'Core hotel management: rooms, room types, rate plans',
    'description': """
Hotel Core Module
=================
Foundation for Internal Hotel PMS.
- Room Types & Rooms (30 rooms, status tracking)
- Rate Plans (season / day-of-week)
- Security groups: Admin / Reception
    """,
    'author': 'Hotel PMS Team',
    'depends': ['base', 'mail', 'account'],
    'data': [
        'security/hotel_security.xml',
        'security/ir.model.access.csv',
        'data/hotel_sequence.xml',
        'data/hotel_demo_data.xml',
        'views/hotel_room_views.xml',
        'views/hotel_rate_plan_views.xml',
        'views/hotel_core_menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'sequence': 1,
}
