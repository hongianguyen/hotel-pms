# -*- coding: utf-8 -*-
"""Load the extracted Y Lak menu into Odoo (POS products + manufacturing BoMs).

Run through odoo shell so no API credentials are needed:

    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo-bin shell \
        -c /opt/hotel-pms-test/odoo-test.conf -d hotel_pms_test --no-http \
        --logfile=/dev/null < load_odoo.py

Idempotent: every record is looked up by name first, so re-running after the
owner corrects the spreadsheet updates in place instead of duplicating.

Model shapes assumed (verified against Odoo 19 on hotel_pms_test):
  * uom.uom has relative_factor / relative_uom_id (no category_id, no uom_type).
    Each Vietnamese unit is created as its own ROOT unit, so no product is ever
    convertible into another unit - cross-unit conversion is exactly the trap
    we want to avoid in a kitchen BoM.
  * product.template.type is 'consu'|'service'|'combo' with is_storable.
  * mrp.bom.type is 'normal'|'phantom' (phantom = Kit).
"""
import json
import os
import re
import unicodedata


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())

PATH = os.environ.get("YLAK_DATA", "/tmp/ylak/menu_data.json")

with open(PATH, encoding="utf-8") as fh:
    DATA = json.load(fh)

ING_CATEG = "Nguyên liệu bếp"
DISH_CATEG = "Món ăn nhà hàng"

log = []


def note(msg):
    log.append(msg)
    print(msg)


# ---------------------------------------------------------------------------
# 0. Precision. Quantities like 0.075 kg must survive; the default is 2 dp.
# ---------------------------------------------------------------------------
# Odoo 19 calls this record 'Product Unit'; older versions 'Product Unit of
# Measure'. Recipes carry 0.075 kg, which silently rounds to 0.08 at 2 dp.
prec = env["decimal.precision"].search([
    ("name", "in", ["Product Unit", "Product Unit of Measure"])
], limit=1)
if not prec:
    raise RuntimeError(
        "No product-unit decimal.precision record found; refusing to import "
        "recipes that would be rounded. Records present: %s"
        % env["decimal.precision"].search([]).mapped("name")
    )
if prec.digits < 3:
    old = prec.digits
    prec.digits = 3
    note(f"decimal.precision {prec.name!r}: {old} -> 3 (RESTART REQUIRED before BoM load)")
else:
    note(f"decimal.precision {prec.name!r} already {prec.digits}")

# Make the UoM field visible in the UI, otherwise the units we create are hidden.
grp = env.ref("uom.group_uom", raise_if_not_found=False)
if grp:
    users = env.ref("base.group_user")
    if grp not in users.implied_ids:
        users.write({"implied_ids": [(4, grp.id)]})
        note("enabled Units of Measure group for internal users")

# ---------------------------------------------------------------------------
# 1. Units of measure - one independent root unit per Vietnamese unit string
# ---------------------------------------------------------------------------
units = set()
for ing in DATA["ingredients"].values():
    units.add(ing["uom"])
for d in DATA["dishes"]:
    if d.get("portion_unit"):
        units.add(d["portion_unit"])

uom_by_name = {}
for name in sorted(units):
    rec = env["uom.uom"].search([("name", "=", name)], limit=1)
    if not rec:
        rec = env["uom.uom"].create({
            "name": name,
            "relative_factor": 1.0,
            "rounding": 0.001,
        })
        note(f"uom created: {name}")
    uom_by_name[name] = rec

# ---------------------------------------------------------------------------
# 2. Product + POS categories
# ---------------------------------------------------------------------------
def get_product_categ(name):
    rec = env["product.category"].search([("name", "=", name)], limit=1)
    if not rec:
        rec = env["product.category"].create({"name": name})
        note(f"product category created: {name}")
    return rec

ing_categ = get_product_categ(ING_CATEG)
dish_categ = get_product_categ(DISH_CATEG)

pos_categ_by_name = {}
for section in sorted({d.get("menu_section") or "Khác" for d in DATA["dishes"]}):
    rec = env["pos.category"].search([("name", "=", section)], limit=1)
    if not rec:
        rec = env["pos.category"].create({"name": section})
        note(f"pos category created: {section}")
    pos_categ_by_name[section] = rec

# ---------------------------------------------------------------------------
# 3. Ingredient products (raw materials - never sold in POS)
# ---------------------------------------------------------------------------
prep_names = set(DATA["prep_items"])
dish_names = {d["name"] for d in DATA["dishes"]}

# A component may BE a dish (e.g. 'Trái cây theo mùa' inside the Picnic, where
# the dish is recorded as 'Trái cây theo mùa/ Seasonal fruit'). Match on the
# Vietnamese part so the BoM points at the dish product instead of creating a
# duplicate raw material.
dish_by_norm_vn = {_norm(d["name_vn"]): d["name"] for d in DATA["dishes"]}

product_by_name = {}
created = updated = 0
for name, ing in sorted(DATA["ingredients"].items()):
    if name in dish_names or _norm(name) in dish_by_norm_vn:
        continue                      # nested dish, created in step 4
    uom = uom_by_name[ing["uom"]]
    vals = {
        "name": name,
        "type": "consu",
        "is_storable": True,
        "uom_id": uom.id,
        "categ_id": ing_categ.id,
        "available_in_pos": False,
        "standard_price": ing["standard_cost"],
        "purchase_ok": True,
        "sale_ok": False,
    }
    rec = env["product.template"].search([("name", "=", name)], limit=1)
    if rec:
        rec.write(vals)
        updated += 1
    else:
        rec = env["product.template"].create(vals)
        created += 1
    product_by_name[name] = rec

note(f"ingredients: {created} created, {updated} updated")

# ---------------------------------------------------------------------------
# 4. Dish products (sold in POS)
# ---------------------------------------------------------------------------
created = updated = no_price = 0
for dish in DATA["dishes"]:
    name = dish["name"]
    portion = dish.get("portion_unit") or "phần"
    uom = uom_by_name.get(portion) or uom_by_name["phần"]
    price = dish.get("sale_price")
    if not price:
        no_price += 1
    section = dish.get("menu_section") or "Khác"
    vals = {
        "name": name,
        "type": "consu",
        "is_storable": True,
        "uom_id": uom.id,
        "categ_id": dish_categ.id,
        # A dish with no confirmed price must not be sellable - otherwise a
        # cashier can ring it up for 0 VND. These switch themselves on as soon
        # as the owner supplies a price and this script is re-run.
        "available_in_pos": bool(price),
        "list_price": price or 0.0,
        "sale_ok": True,
        "purchase_ok": False,
        # No tax, deliberately. The deck prices are printed menu prices, i.e.
        # VAT-INCLUSIVE, but the only sale tax on this database is a generic
        # 15% with price_include=False, which would add 15% on top of every
        # menu price. Leaving taxes off keeps the POS total equal to the
        # printed price. Set a price-included VN VAT tax here once the owner
        # confirms the rate (8% or 10%), then re-run.
        "taxes_id": [(5, 0, 0)],
        "pos_categ_ids": [(6, 0, [pos_categ_by_name[section].id])],
    }
    rec = env["product.template"].search([("name", "=", name)], limit=1)
    if rec:
        rec.write(vals)
        updated += 1
    else:
        rec = env["product.template"].create(vals)
        created += 1
    product_by_name[name] = rec

note(f"dishes: {created} created, {updated} updated, {no_price} with NO price (set to 0)")

# Prep items (made in batches, not sold)
for name in sorted(prep_names):
    if name in product_by_name:
        product_by_name[name].write({"available_in_pos": False, "sale_ok": False})

# ---------------------------------------------------------------------------
# 5. Bills of material
# ---------------------------------------------------------------------------
bom_created = bom_updated = 0
skipped_lines = []

for dish in DATA["dishes"]:
    tmpl = product_by_name[dish["name"]]
    bom_type = "normal" if dish["name"] in prep_names else "phantom"

    lines = []
    for comp in dish["components"]:
        cname = comp["ingredient"]
        target = product_by_name.get(cname)
        if not target and _norm(cname) in dish_by_norm_vn:
            target = product_by_name.get(dish_by_norm_vn[_norm(cname)])
        if not target:
            skipped_lines.append((dish["name"], cname, "no product"))
            continue
        qty = comp["qty"]
        if not isinstance(qty, (int, float)):
            skipped_lines.append((dish["name"], cname, f"qty not numeric: {qty!r}"))
            continue
        # BoM line must use the product's own UoM (all units are independent roots)
        lines.append((0, 0, {
            "product_id": target.product_variant_id.id,
            "product_qty": qty,
            "product_uom_id": target.uom_id.id,
        }))

    if not lines:
        skipped_lines.append((dish["name"], "-", "no usable components"))
        continue

    existing = env["mrp.bom"].search([("product_tmpl_id", "=", tmpl.id)], limit=1)
    vals = {
        "product_tmpl_id": tmpl.id,
        "product_qty": 1.0,
        "type": bom_type,
        "product_uom_id": tmpl.uom_id.id,
        "bom_line_ids": lines,
    }
    if existing:
        existing.bom_line_ids.unlink()
        existing.write(vals)
        bom_updated += 1
    else:
        env["mrp.bom"].create(vals)
        bom_created += 1

note(f"BoMs: {bom_created} created, {bom_updated} updated")
if skipped_lines:
    note(f"SKIPPED BoM lines: {len(skipped_lines)}")
    for a, b, why in skipped_lines:
        note(f"   {a} | {b} | {why}")

# ---------------------------------------------------------------------------
# 6. Make the dishes available in the running POS config(s)
# ---------------------------------------------------------------------------
env.cr.commit()

note("")
note("=" * 60)
note("SUMMARY")
note("=" * 60)
note(f"UoM total            : {len(uom_by_name)}")
note(f"POS categories       : {len(pos_categ_by_name)}")
note(f"Products total       : {len(product_by_name)}")
note(f"BoMs                 : {env['mrp.bom'].search_count([])}")
note(f"Kit (phantom) BoMs   : {env['mrp.bom'].search_count([('type','=','phantom')])}")
note(f"Normal BoMs          : {env['mrp.bom'].search_count([('type','=','normal')])}")
