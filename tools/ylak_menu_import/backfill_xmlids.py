# -*- coding: utf-8 -*-
"""PHASE 0 -- stamp external ids onto everything the first import created.

Run this BEFORE any other loader, and before the owner renames anything.

The original loader matched records by exact name only. That works until
someone edits a dish name in Odoo, at which point the next run creates a
duplicate instead of updating. This script closes that hole while it can still
be closed: it keys each record on a slug of the name as the SPREADSHEET spells
it, so the link survives any later rename on either side.

It is also what makes the set-menu load re-runnable at all. product.combo rows
have no natural key, so without external ids every re-run of load_20_sets.py
would create another ~70 combo choices.

Read-mostly: creates ir.model.data rows, touches no business field.

    YLAK_DIR=... YLAK_DATA=.../menu_data.json \
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo-bin shell \
        -c /opt/hotel-pms-test/odoo-test.conf -d hotel_pms_test --no-http \
        --logfile=/dev/null < backfill_xmlids.py
"""
import os
import sys

sys.path.insert(0, os.environ["YLAK_DIR"])
from ylak_common import load_json, note, stamp, norm  # noqa: E402

DATA = load_json("YLAK_DATA")

stamped = 0
missing = []


def adopt(model, prefix, source_name, domain=None):
    """Stamp the record this source row produced, if it is still findable."""
    global stamped
    rec = env[model].search(domain or [("name", "=", source_name)], limit=1)
    if not rec:
        missing.append((model, prefix, source_name))
        return None
    if stamp(env, rec, prefix, source_name):
        stamped += 1
    return rec


# ---------------------------------------------------------------------------
# 1. Units of measure
# ---------------------------------------------------------------------------
# ingredients is a dict keyed by name; its unit field is 'uom', while a dish
# carries 'portion_unit'.
INGREDIENTS = list(DATA.get("ingredients", {}).values())

uom_names = set()
for ing in INGREDIENTS:
    if ing.get("uom"):
        uom_names.add(ing["uom"])
for dish in DATA.get("dishes", []):
    if dish.get("portion_unit"):
        uom_names.add(dish["portion_unit"])
for name in sorted(uom_names):
    adopt("uom.uom", "uom", name)

# ---------------------------------------------------------------------------
# 2. Product & POS categories
# ---------------------------------------------------------------------------
for name in ("Nguyên liệu bếp", "Món ăn nhà hàng"):
    adopt("product.category", "categ", name)

pos_sections = {d.get("menu_section") for d in DATA.get("dishes", [])}
for name in sorted(s for s in pos_sections if s):
    adopt("pos.category", "poscateg", name)

# ---------------------------------------------------------------------------
# 3. Taxes
# ---------------------------------------------------------------------------
adopt("account.tax", "tax", "VAT 8%",
      domain=[("name", "=", "VAT 8%"), ("type_tax_use", "=", "sale")])

# ---------------------------------------------------------------------------
# 4. Ingredients and dishes
# ---------------------------------------------------------------------------
dish_names = {d["name"] for d in DATA.get("dishes", [])}

for ing in INGREDIENTS:
    name = ing["name"]
    # One "ingredient" is really a dish used inside another dish; it was never
    # created as its own product, so it is stamped in the dish pass instead.
    if name in dish_names or norm(name) in {norm(n) for n in dish_names}:
        continue
    adopt("product.template", "ing", name)

for dish in DATA.get("dishes", []):
    tmpl = adopt("product.template", "dish", dish["name"])
    if tmpl:
        # BoMs have no unique name of their own; key them on the dish.
        bom = env["mrp.bom"].search([("product_tmpl_id", "=", tmpl.id)],
                                    limit=1)
        if bom and stamp(env, bom, "bom", dish["name"]):
            stamped += 1

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
note("")
note("=" * 68)
note("external ids written : %d" % stamped)
note("source rows not found in Odoo: %d" % len(missing))
for model, prefix, name in missing[:40]:
    note("    %-18s %-9s %s" % (model, prefix, name))
if len(missing) > 40:
    note("    ... and %d more" % (len(missing) - 40))
note("=" * 68)
note("")
note("A 'not found' row is normal for anything the first import skipped, and")
note("a problem for anything it did create -- that record has been renamed and")
note("must be matched by hand before the next load, or it will be duplicated.")

env.cr.commit()
note("committed.")
