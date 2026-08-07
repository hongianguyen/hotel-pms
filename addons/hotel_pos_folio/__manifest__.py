# -*- coding: utf-8 -*-
{
    'name': 'Hotel PMS — POS Room Charge',
    'version': '19.0.1.1.0',
    'category': 'Hotel',
    'summary': 'Charge restaurant POS orders to an in-house guest folio',
    'description': """
Link Point of Sale to the Hotel PMS folio
=========================================
- Adds a "Charge to Room" POS payment method
- The POS customer list shows only currently checked-in guests (per POS toggle)
- Each guest line shows the room they occupy, so the ticket can be matched to a folio
- Guests are searchable by room number as well as name
- A charged order posts an F&B line straight onto the guest's folio
- Revenue is recognised once, in POS. The folio line carries the same
  clearing account POS debited, so the checkout invoice clears it to zero.
    """,
    'author': 'Lak Tented Camp',
    'depends': [
        'hotel_frontdesk',
        'point_of_sale',
    ],
    'data': [
        'views/pos_payment_method_views.xml',
        'views/pos_config_views.xml',
        'views/hotel_folio_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'hotel_pos_folio/static/src/**/*',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
