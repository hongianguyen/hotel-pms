# -*- coding: utf-8 -*-
{
    'name': 'Vietnam E-Invoice — hoadon30s',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'Issue Vietnamese VAT e-invoices (GDT) via hoadon30s.vn from invoices and POS',
    'description': """
Vietnamese VAT e-invoice integration with hoadon30s.vn:

* Issue VAT e-invoices (hoá đơn GTGT) from posted customer invoices —
  covers Hotel PMS folio invoices and any other customer invoice.
* Auto-issue cash-register e-invoices (hoá đơn GTGT máy tính tiền) from
  POS orders on payment.
* Retrieve all issued e-invoices from the provider (which syncs them with
  the General Department of Taxation) and auto-create the partners.
* Track GDT status (signed / sent / tax-authority code granted) per invoice.
    """,
    'author': 'Hotel PMS',
    'license': 'LGPL-3',
    'depends': ['account', 'point_of_sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/account_move_views.xml',
        'views/pos_order_views.xml',
        'views/hoadon30s_einvoice_views.xml',
        'wizards/einvoice_fetch_wizard_views.xml',
        'data/ir_cron.xml',
    ],
    'installable': True,
    'application': False,
}
