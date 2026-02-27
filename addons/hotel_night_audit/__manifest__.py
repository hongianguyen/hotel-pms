# -*- coding: utf-8 -*-
{
    'name': 'Hotel Night Audit',
    'version': '19.0.1.0.0',
    'category': 'Hotel Management',
    'summary': 'Automated nightly audit: post invoices, lock day, KPI snapshot, email admin',
    'author': 'Hotel PMS Team',
    'depends': ['hotel_frontdesk', 'hotel_services'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_night_audit.xml',
        'data/mail_template_night_audit.xml',
        'views/hotel_night_audit_views.xml',
        'views/hotel_night_audit_menu.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
    'sequence': 7,
}
