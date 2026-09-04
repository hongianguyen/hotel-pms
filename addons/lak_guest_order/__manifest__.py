# -*- coding: utf-8 -*-
{
    'name': "LAK Tented Camp - Guest Ordering API",
    'version': '19.0.1.0.0',
    'category': 'Sales/Point of Sale',
    'summary': 'Public menu + order API for the guest web page; orders land '
               'straight on the POS as unpaid orders',
    'description': """
Serves the guest page hosted on Cloudflare Pages:

    GET  /api/lak/menu     the live POS menu -- categories, prices, both names
    POST /api/lak/order    puts an UNPAID order on the till
    GET  /api/lak/rooms    the room codes the page's picker validates against

The order is created through Odoo's own self-order machinery
(``pos.order._check_pos_order`` + ``sync_from_ui``), which is what the
built-in QR menu uses, so it appears on the cashier's screen the moment it
lands and prices are recomputed server-side -- a tampered price in the request
body is ignored.

No new apps. `point_of_sale`, `pos_restaurant` and `pos_self_order` are
already installed on hotel_db; `sale` and `sale_management` are deliberately
NOT used.

The order is never paid, never confirmed and never touches a folio. The room
number is a claim typed by an anonymous person, not an authorisation --
reception checks it before charging anything.

Inert until `lak_guest_order.enabled` is set to 1.
""",
    'author': 'LAK Tented Camp',
    'depends': ['pos_self_order', 'pos_restaurant', 'hotel_core', 'mail'],
    'data': [
        'data/guest_order_data.xml',
        'views/pos_order_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
