# -*- coding: utf-8 -*-
{
    'name': 'Hotel Reporting',
    'version': '19.0.1.0.0',
    'category': 'Hotel Management',
    'summary': 'Reception & Admin Dashboards, Gantt calendar, KPI reports',
    'author': 'Hotel PMS Team',
    'depends': ['hotel_frontdesk', 'hotel_services'],
    'data': [
        'security/ir.model.access.csv',
        'views/hotel_reporting_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hotel_reporting/static/src/css/hotel_dashboard.css',
            'hotel_reporting/static/src/js/reception_dashboard.js',
            'hotel_reporting/static/src/js/admin_dashboard.js',
            'hotel_reporting/static/src/xml/reception_dashboard.xml',
            'hotel_reporting/static/src/xml/admin_dashboard.xml',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
    'sequence': 6,
}
