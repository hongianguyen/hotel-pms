# -*- coding: utf-8 -*-
{
    'name': 'Hotel Housekeeping',
    'version': '19.0.1.1.0',
    'category': 'Hotel Management',
    'summary': 'Room status board, cleaning tasks with SLA, auto-task on checkout',
    'author': 'Hotel PMS Team',
    'depends': ['hotel_core', 'hotel_frontdesk'],
    'data': [
        'security/ir.model.access.csv',
        'views/hotel_housekeeping_views.xml',
        'views/hotel_housekeeping_task_views.xml',
        'views/hotel_housekeeping_menu.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
    'sequence': 3,
}
