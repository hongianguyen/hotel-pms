# -*- coding: utf-8 -*-
{
    'name': 'Hotel Channel Manager - Aiosell',
    'version': '19.0.1.0.0',
    'category': 'Hotel',
    'summary': 'Two-way sync of inventory, rates and reservations with the '
               'Aiosell channel manager',
    'description': """
Connects the PMS to Aiosell, which in turn distributes to the OTAs
(Booking.com, Agoda, Expedia, Airbnb, Goibibo/MMT ...).

Outbound (PMS -> Aiosell)
  * Availability per room type, per night
  * Rates per (room type, rate plan), per night
  * Restrictions (stop sell, min/max stay, CTA/CTD)
  * No-show marking

Inbound (Aiosell -> PMS)
  * OTA reservations arrive on a webhook this module exposes and become
    hotel.reservation records: book / modify / cancel.

The full upstream API contract this module implements is written down in
README.md, because Aiosell publishes it only from a JavaScript app whose
bundle URL changes on every docs deploy.
    """,
    'author': 'Hotel PMS',
    'depends': ['hotel_core', 'hotel_frontdesk'],
    'data': [
        'security/ir.model.access.csv',
        'data/aiosell_cron.xml',
        'views/aiosell_sync_log_views.xml',
        'views/aiosell_mapping_views.xml',
        'views/aiosell_config_views.xml',
        'views/hotel_reservation_views.xml',
        'views/aiosell_menu.xml',
    ],
    'sequence': 9,
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
