# -*- coding: utf-8 -*-
"""STEP 4 -- reorder rules from the owner's filled-in reorder_levels.csv.

    YLAK_DIR=... YLAK_INVENTORY=... \
        odoo-bin shell -c ... -d ... --no-http < load_40_orderpoints.py

A no-op until the owner fills in min/max. Rows with both blank get no
orderpoint at all -- no minimum is ever guessed, because nothing in the source
workbooks contains one.

Deleting a rule the owner emptied out is right here, unlike everywhere else in
this toolchain: an orderpoint is a live instruction to buy, not a record of
anything. Leaving a stale one behind means the system keeps ordering something
they told it to stop ordering.
"""
import csv
import os
import sys

sys.path.insert(0, os.environ["YLAK_DIR"])
from ylak_common import load_json, note, ref, stamp  # noqa: E402

INV = load_json("YLAK_INVENTORY")
PATH = os.path.join(os.environ["YLAK_DIR"], "reorder_levels.csv")

if not os.path.exists(PATH):
    note("no reorder_levels.csv -- run make_reorder_csv.py. Nothing to do.")
    raise SystemExit(0)

warehouse = env["stock.warehouse"].search([], limit=1)
locations = {code: ref(env, "loc", code) for code in INV["stores"]}


def number(text):
    text = (text or "").strip().replace(",", "")
    return float(text) if text else None


wanted, skipped, unknown = {}, 0, []
with open(PATH, encoding="utf-8-sig", newline="") as fh:
    for row in csv.DictReader(fh):
        lo, hi = number(row.get("min")), number(row.get("max"))
        if lo is None and hi is None:
            skipped += 1
            continue
        tmpl = ref(env, "stk", row["product"]) or ref(env, "ing", row["product"])
        loc = locations.get(row["store"])
        if not tmpl or not loc:
            unknown.append(row["product"])
            continue
        # A max below the min would have Odoo order a negative quantity.
        lo = lo or 0.0
        hi = hi if hi is not None and hi >= lo else lo
        wanted[(tmpl.product_variant_id.id, loc.id)] = (row["product"], lo, hi)

Orderpoint = env["stock.warehouse.orderpoint"]
created = updated = removed = 0
for (product_id, loc_id), (name, lo, hi) in wanted.items():
    rule = ref(env, "orp", "%s@%s" % (name, loc_id))
    if not rule:
        rule = Orderpoint.search([("product_id", "=", product_id),
                                  ("location_id", "=", loc_id)], limit=1)
    # trigger='manual', not Odoo's 'auto' default.
    #
    # `purchase` WAS uninstalled when this was written, which left an auto rule
    # with nothing to replenish through. It is installed on production as of
    # 01 Sep 2026, so the Buy route now exists -- but manual is still right,
    # for a second reason: auto procurement needs a vendor on the product, and
    # `product.supplierinfo` is empty. An auto rule with no seller line raises
    # a procurement exception per orderpoint, nightly, and still buys nothing.
    #
    # Manual rules surface in Inventory > Operations > Replenishment as a
    # suggested order quantity -- a shopping list, which is what "follow it and
    # fill it up" asks for, and the Order button now raises a real PO.
    # Set YLAK_ORDERPOINT_TRIGGER=auto once products carry vendors.
    trigger = os.environ.get("YLAK_ORDERPOINT_TRIGGER", "manual")
    if trigger not in ("manual", "auto"):
        raise RuntimeError("YLAK_ORDERPOINT_TRIGGER must be manual or auto")
    vals = {"product_min_qty": lo, "product_max_qty": hi, "trigger": trigger}
    if rule:
        if (rule.product_min_qty, rule.product_max_qty,
                rule.trigger) != (lo, hi, trigger):
            rule.write(vals)
            updated += 1
    else:
        rule = Orderpoint.create(dict(
            vals, product_id=product_id, location_id=loc_id,
            warehouse_id=warehouse.id))
        created += 1
    stamp(env, rule, "orp", "%s@%s" % (name, loc_id))

# Rules this toolchain made that the CSV no longer asks for.
imd = env["ir.model.data"]
for md in imd.search([("module", "=", "__ylak__"),
                      ("model", "=", "stock.warehouse.orderpoint")]):
    rule = Orderpoint.browse(md.res_id).exists()
    if rule and (rule.product_id.id, rule.location_id.id) not in wanted:
        rule.unlink()
        md.unlink()
        removed += 1

note("reorder rules: %d created, %d updated, %d removed, %d row(s) left blank"
     % (created, updated, removed, skipped))
if unknown:
    note("!! %d row(s) named a product or store that does not exist:" % len(unknown))
    for name in unknown[:10]:
        note("     %s" % name)

env.cr.commit()
note("committed.")
