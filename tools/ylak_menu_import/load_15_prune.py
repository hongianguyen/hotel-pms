# -*- coding: utf-8 -*-
"""STEP 1b -- archive records the current extract no longer produces.

    YLAK_DIR=... YLAK_DATA=... YLAK_INVENTORY=... YLAK_SETS=... \
        odoo-bin shell -c ... -d ... --no-http < load_15_prune.py

The first import read the older COST.xlsx and named dishes in a
"Vietnamese/English" style ("Súp bí đỏ/ Pumpkin soup"). The new workbook names
the same dishes in Vietnamese caps ("SOUP BÍ ĐỎ"), so the catalogue load
creates them fresh rather than renaming: they have different external ids and
nothing links the two. Left alone, POS shows every dish twice.

This archives -- never deletes -- any product or BoM carrying a `__ylak__`
external id that the current extract does not produce. Archiving keeps the
history, the stock moves and the old order lines intact, and the owner can
unarchive anything this gets wrong.

Run LAST, after every other loader. It archives anything with a `__ylak__` id
that the extracts do not account for, so it has to know about the set menus,
the buffet and the visitor charge -- which load_20_sets.py creates. Running it
before them archived all 18 on the second pass, and the next run silently
rebuilt them.
"""
import os
import sys

sys.path.insert(0, os.environ["YLAK_DIR"])
from ylak_common import load_json, note, norm, slug  # noqa: E402

MENU = load_json("YLAK_DATA")
INV = load_json("YLAK_INVENTORY")
SETS = load_json("YLAK_SETS")

BUFFET_NAME = "BUFFET / PAX (CHƯA CÓ GIÁ)"
VISITOR = "KHÁCH THAM QUAN"

# Every external id the current extract is entitled to own.
expected = set()
dish_names = {d["name"] for d in MENU["dishes"]}
dish_norms = {norm(n) for n in dish_names}

for d in MENU["dishes"]:
    expected.add("dish_%s" % slug(d["name"]))
    expected.add("bom_%s" % slug(d["name"]))
for i in MENU["ingredients"].values():
    if i["name"] not in dish_names and norm(i["name"]) not in dish_norms:
        expected.add("ing_%s" % slug(i["name"]))
    else:
        expected.add("ing_%s" % slug(i["name"]))   # self-named bought goods
for p in INV["products"]:
    expected.add("stk_%s" % slug(p["name"]))
    expected.add("ing_%s" % slug(p["name"]))       # may have come from either

# Created by load_20_sets.py, not by an extract file.
for spec in SETS["sets"]:
    short = spec["tier"].split("/")[0].strip()
    name = "%s - %s (tối thiểu 2 khách)" % (short, spec["variant"])
    expected.add("set_%s" % slug(name))
for line in SETS["buffet"]["lines"]:
    expected.add("ing_%s" % slug(line["ingredient"]))
expected.add("dish_%s" % slug(BUFFET_NAME))
expected.add("bom_%s" % slug(BUFFET_NAME))
expected.add("fee_%s" % slug(VISITOR))

# Products the FIRST import created that lost their external id when the slug
# scheme changed, so nothing below can see them. Named explicitly rather than
# matched by a rule: an unowned product is not this toolchain's to retire, and
# a rule loose enough to catch this one also catches Odoo's demo data.
# `Canh Tập Tàng` is priced 150,000 VND, has no product category, and is not in
# any current extract -- a live POS button from the superseded 73-dish import.
ORPHANS = {"Canh Tập Tàng"}

imd = env["ir.model.data"]
archived = {"product.template": [], "mrp.bom": []}

for name in sorted(ORPHANS):
    rec = env["product.template"].search([("name", "=", name)], limit=1)
    if rec and rec.active:
        env["mrp.bom"].search([("product_tmpl_id", "=", rec.id)]).active = False
        rec.active = False
        archived["product.template"].append(("(first import, no xmlid)", name))

for model in ("product.template", "mrp.bom"):
    rows = imd.search([("module", "=", "__ylak__"), ("model", "=", model)])
    for row in rows:
        prefix = row.name.split("_", 1)[0]
        if prefix not in ("dish", "ing", "stk", "bom", "set", "fee"):
            continue
        if row.name in expected:
            continue
        rec = env[model].browse(row.res_id).exists()
        if not rec or not rec.active:
            continue
        label = rec.display_name
        rec.active = False
        archived[model].append((row.name, label))

note("=" * 68)
for model, items in archived.items():
    note("%-18s archived %d" % (model, len(items)))
    for xid, label in items[:12]:
        note("    %-40s %s" % (label[:40], xid))
    if len(items) > 12:
        note("    ... and %d more" % (len(items) - 12))
note("=" * 68)
# Anything sellable that this toolchain does not own. Reported, never touched:
# 26 of them are Odoo's own POS demo products, which are not ours to archive
# and which the owner should retire before the till goes live.
unowned = env["product.template"].search([("available_in_pos", "=", True)])
unowned = unowned.filtered(lambda t: not imd.search_count([
    ("module", "=", "__ylak__"), ("model", "=", "product.template"),
    ("res_id", "=", t.id)]))
if unowned:
    note("")
    note("%d sellable product(s) this toolchain does not own -- left alone:"
         % len(unowned))
    for tmpl in unowned[:6]:
        note("     %-38s %s" % (tmpl.display_name[:38], tmpl.list_price))
    if len(unowned) > 6:
        note("     ... and %d more (Odoo's POS demo data)" % (len(unowned) - 6))

note("Archived, not deleted: stock moves, past orders and history are intact,")
note("and anything archived in error can be restored from the product list by")
note("filtering on Archived.")

env.cr.commit()
note("committed.")
