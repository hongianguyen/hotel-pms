# -*- coding: utf-8 -*-
{
    'name': 'Hotel Revenue Basic',
    'version': '19.0.1.0.0',
    'category': 'Hotel Management',
    'summary': 'Season pricing and rate engine',
    'author': 'Hotel PMS Team',
    'depends': ['hotel_core'],
    'data': [
        'security/ir.model.access.csv',
        'views/hotel_revenue_views.xml',
        'views/hotel_revenue_menu.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
    'sequence': 4,
}
