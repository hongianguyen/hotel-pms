# -*- coding: utf-8 -*-
{
    'name': 'Hotel Housekeeping',
    'version': '19.0.1.0.0',
    'category': 'Hotel Management',
    'summary': 'Room status board and housekeeping workflow',
    'author': 'Hotel PMS Team',
    'depends': ['hotel_core'],
    'data': [
        'views/hotel_housekeeping_views.xml',
        'views/hotel_housekeeping_menu.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
    'sequence': 3,
}
