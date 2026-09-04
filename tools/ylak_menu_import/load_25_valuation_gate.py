# -*- coding: utf-8 -*-
"""STEP 2b -- refuse to post an opening count into a real-time-valued category.

    YLAK_DIR=... odoo-bin shell -c ... -d ... --no-http < load_25_valuation_gate.py

`load_30_inventory.py` applies a 1,081-line inventory adjustment. With
`stock_account` installed -- it is, on both servers -- a category whose
`property_valuation` is `real_time` posts a journal entry for every one of
those lines, straight into the live TT200 books. There is no clean undo: the
entries land in a posted stock journal.

`load_10_catalog.py` deliberately leaves `property_valuation` unset so its new
categories inherit the database default, and on `hotel_db` that default
resolves to `periodic`. This gate exists because "inherits a safe default" is a
claim about configuration that can change without anyone touching this code --
a new company, a chart-of-accounts migration, someone ticking Automated
Inventory Valuation in Settings. It reads the EFFECTIVE value on every category
the loader owns and stops the chain before step 30 if any is real_time.

Read-only. It never writes, and it exits non-zero rather than continuing.
"""
import os
import sys

sys.path.insert(0, os.environ["YLAK_DIR"])
from ylak_common import note  # noqa: E402

imd = env["ir.model.data"]

rows = imd.search([("module", "=", "__ylak__"), ("model", "=", "product.category")])
ours = env["product.category"].browse(rows.mapped("res_id")).exists()

# Belt and braces: also check every category any product we own actually sits
# in, in case a category was reused rather than created by us.
prod_rows = imd.search([("module", "=", "__ylak__"),
                        ("model", "=", "product.template")])
owned_products = env["product.template"].with_context(active_test=False).browse(
    prod_rows.mapped("res_id")).exists()
ours |= owned_products.mapped("categ_id")

if not ours:
    note("no __ylak__ categories yet -- nothing to gate (run after load_10).")
    sys.exit(0)

note("=" * 68)
note("checking stock valuation on %d category(ies)" % len(ours))

bad = []
for categ in ours.sorted("complete_name"):
    valuation = categ.property_valuation
    cost = categ.property_cost_method
    flag = "REAL-TIME" if valuation == "real_time" else "ok"
    note("  %-42s %-16s %-10s %s"
         % (categ.complete_name[:42], valuation, cost, flag))
    if valuation == "real_time":
        bad.append(categ.complete_name)

note("=" * 68)
if bad:
    note("ABORT: %d category(ies) use real-time valuation:" % len(bad))
    for name in bad:
        note("    %s" % name)
    note("")
    note("Applying the opening count would post a journal entry per line into")
    note("the live books. Set these categories to Periodic (manual) valuation,")
    note("or exclude them, before running load_30_inventory.py.")
    sys.exit(3)

note("all clear: valuation is periodic, the opening count posts no journal entries.")
