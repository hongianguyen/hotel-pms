# -*- coding: utf-8 -*-
{
    'name': 'Hotel Services',
    'version': '19.0.1.0.0',
    'category': 'Hotel Management',
    'summary': 'Extra charges, tours, POS bridge to folio',
    'author': 'Hotel PMS Team',
    'depends': ['hotel_frontdesk'],
    'data': [
        'security/ir.model.access.csv',
        'data/hotel_service_demo.xml',
        'views/hotel_service_views.xml',
        'views/hotel_service_menu.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
    'sequence': 5,
}
