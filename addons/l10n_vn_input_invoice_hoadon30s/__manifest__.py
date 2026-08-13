# -*- coding: utf-8 -*-
{
    'name': 'Vietnam Input VAT Invoices — hoadon30s',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'Download input (purchase) VAT e-invoices from the GDT portal '
               'via hoadon30s.vn and create draft vendor bills',
    'description': """
Vietnamese input VAT e-invoice (hoá đơn đầu vào) integration with hoadon30s.vn:

* Link the company's hoadondientu.gdt.gov.vn portal account once, through the
  provider's invoice-sync service.
* Download purchase e-invoices issued to the company — both regular VAT
  invoices and cash-register (máy tính tiền) ones.
* Parse the regulated GDT XML (Decree 123/2020 / TT78) into a reviewable
  registry, auto-creating the vendor partners.
* Create draft vendor bills from the parsed invoices, never posting
  automatically and never silently altering the amounts stated on the
  original invoice.

This is a SEPARATE service from the e-invoice issuance API — it has its own
credentials, its own token endpoint and its own metered quota. It therefore
lives in its own module and shares no configuration with
``l10n_vn_einvoice_hoadon30s``.
    """,
    'author': 'Hotel PMS',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/purchase_einvoice_views.xml',
        'wizards/purchase_einvoice_fetch_wizard_views.xml',
        'wizards/gdt_connect_wizard_views.xml',
        'data/ir_cron.xml',
    ],
    'installable': True,
    'application': False,
}
