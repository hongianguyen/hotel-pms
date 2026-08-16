# -*- coding: utf-8 -*-
{
    'name': 'Hotel Channel Manager',
    'version': '19.0.1.0.0',
    'category': 'Hotel',
    'summary': 'OTA Channel Manager - Booking.com & Agoda Integration',
    'description': """
Two-way real-time sync with OTA channels (Booking.com, Agoda).
- Push availability and rates to channels when PMS state changes
- Receive bookings from channels via webhooks
- Prevent overbooking across all channels
    """,
    'author': 'Hotel PMS',
    'depends': ['hotel_core', 'hotel_frontdesk', 'hotel_revenue_basic'],
    'data': [
        'security/hotel_channel_security.xml',
        'security/ir.model.access.csv',
        'data/channel_cron.xml',
        'views/channel_sync_log_views.xml',
        'views/channel_mapping_views.xml',
        'views/channel_config_views.xml',
        'views/channel_menu.xml',
        'wizards/channel_force_sync_wizard_views.xml',
    ],
    'demo': [
        'data/channel_demo_data.xml',
    ],
    'sequence': 8,
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
