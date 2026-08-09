# hotel_pos_folio — version-coupled by design

This module reaches into `point_of_sale` internals. That is unavoidable — POS
has no public extension point for "restrict the customer list and settle a
payment somewhere other than the till" — but it means **this module is the one
most likely to break on an Odoo major-version upgrade.**

Before upgrading, diff each of the following against the new `point_of_sale`
source. Check the **signature first**, behaviour second.

| Override | File | Why it's fragile |
|---|---|---|
| `res.partner._load_pos_data_domain(data, config)` | `models/res_partner.py:55` | Private POS loader. Core reads `data['pos.order']` out of the payload, so the **shape of `data`** is part of the contract too, not just the signature — passing `{}` raises `KeyError`. |
| `res.partner._load_pos_data_fields(config)` | `models/res_partner.py:67` | Same family, same churn. |
| `res.partner.get_new_partner(config_id, domain, offset)` | `models/res_partner.py:71` | Cashier-side search; three positional args, no stability guarantee. |
| `res.partner._extract_search_term(domain)` | `models/res_partner.py:87` | Reverse-engineers the *shape* of the domain POS built. Nothing about that shape is contractual. **Fails silently.** |
| `pos.order._process_order(order, existing_order)` | `models/pos_order.py:26` | Private order-creation hook; `existing_order` was added relatively recently. |
| `PartnerLine` template xpaths | `static/src/app/screens/partner_list/partner_line/partner_line.xml:8,13` | Anchored on Bootstrap utility classes in a core template. **Fails silently.** |
| Settings-view xpath | `views/pos_config_views.xml:14` | `//setting[@id='other_devices']`. Settings views get rewritten often. |

`tests/test_pos_api_surface.py` exists specifically to turn the silent failures
into loud ones. Run it first after any upgrade:

```
odoo-bin -c <conf> -d <db> -u hotel_pos_folio --test-enable --stop-after-init
```

The clearing account must stay a **reconcilable current asset**, not a
receivable — Odoo reclassifies receivable accounts out of `invoice_line_ids`,
so a receivable clearing account would never reach the guest's check-out
invoice. The constraint in `pos_payment_method.py` enforces this; don't relax it.

See `UPGRADE_READINESS.md` at the repo root for the full picture.
