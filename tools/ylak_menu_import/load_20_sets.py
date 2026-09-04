# -*- coding: utf-8 -*-
"""STEP 2 -- set menus, the buffet and the visitor charge.

    YLAK_DIR=... YLAK_SETS=.../sets_data.json YLAK_DATA=.../menu_data.json \
        odoo-bin shell -c ... -d ... --no-http < load_20_sets.py

Set menus are POS combos (product.template.type = 'combo'), not nested kit
BoMs. Both deduct stock correctly -- Odoo's explode() recurses through a kit
whose component is itself a kit -- so the decision rests on everything else:

  * A combo puts each course on the ticket as its own pos.order.line, so the
    kitchen display shows the six dishes. A nested kit prints one opaque
    "SET LUNCH" line and the courses never reach the pass.
  * Every course here is fixed, and a combo choice holding exactly one item
    auto-confirms, so the cashier sees no popup: one tap, like any other
    product.
  * The parent's price is prorated across the children by their a-la-carte
    prices, giving per-dish revenue for free.
  * Combo children are force-loaded into POS regardless of available_in_pos,
    so course-only dishes work without being individually sellable.

The 2-pax minimum has no field in Odoo. It lives in the product name.

The buffet is an ordinary kit: one per-pax product whose BoM is each of the 38
lines divided by 20.
"""
import os
import re
import sys

sys.path.insert(0, os.environ["YLAK_DIR"])
from ylak_common import (  # noqa: E402
    get_or_create, load_json, norm, note, ref, require_precision, stamp,
)

require_precision(env, 3)

SETS = load_json("YLAK_SETS")
MENU = load_json("YLAK_DATA")

VAT_NAME = "VAT 8%"
vat = ref(env, "tax", VAT_NAME)
if not vat:
    raise RuntimeError("%s has no __ylak__ id; run load_10_catalog.py first"
                       % VAT_NAME)

pos_set = ref(env, "poscateg", "Set menu")
pos_buffet = ref(env, "poscateg", "Buffet")
pos_extra = ref(env, "poscateg", "Phụ thu")
categ = ref(env, "categ", "Món ăn nhà hàng")
uom_pax = ref(env, "uom", "pax")
if not all([pos_set, pos_buffet, pos_extra, categ, uom_pax]):
    raise RuntimeError("catalogue prerequisites missing; run load_10_catalog.py")

# ---------------------------------------------------------------------------
# 1. Set menus
# ---------------------------------------------------------------------------
# The owner's naming, 30 Aug 2026: "COMBO SET Lunch 01 245000" -- course type,
# set number zero-padded, price with no separators, so every record belonging
# to one set shares a single searchable string.
MIN_PAX = "Tối thiểu 2 khách."


def combo_name(spec):
    """'SET LUNCH 245.000/ 1 PAX ( MINIMUM 2PAX)' + 'SET 2'
       -> 'COMBO SET LUNCH 02 245000'"""
    head = spec["tier"].split("/")[0].strip()          # "SET LUNCH 245.000"
    head = re.sub(r"[\d.,]+\s*$", "", head).strip()     # "SET LUNCH"
    num = re.search(r"(\d+)", spec["variant"] or "")
    return "COMBO %s %02d %d" % (head.upper(), int(num.group(1)) if num else 0,
                                 round(spec["price"]))


def legacy_key(spec):
    """The ORIGINAL constructed name, kept only as the external-id key.

    slug() is meant to be fed a stable source string. Feeding it the display
    name instead means this rename mints a fresh id, orphans the existing
    product and has load_15_prune.py archive it -- losing the link, the order
    history, and the prune's own keep-list, which derives from this same
    formula. So the id keeps the old string and only the label changes.
    """
    return "%s - %s (tối thiểu 2 khách)" % (
        spec["tier"].split("/")[0].strip(), spec["variant"])


built = skipped = 0
for spec in SETS["sets"]:
    tier = spec["tier"]
    key = legacy_key(spec)
    name = combo_name(spec)

    if spec.get("incomplete"):
        note("SKIPPED %s -- a course has no recipe, so selling it would "
             "under-deduct stock" % name)
        skipped += 1
        continue

    courses = []
    ok = True
    for dish_name in spec["courses"]:
        tmpl = ref(env, "dish", dish_name)
        if not tmpl:
            note("!! %s: no product for course %r" % (name, dish_name))
            ok = False
            break
        courses.append(tmpl)
    if not ok:
        skipped += 1
        continue

    cost = sum(c.standard_price for c in courses)

    # Build the choices FIRST. product.template._check_combo_ids_not_empty
    # fires during create(), so a combo product cannot exist for even one
    # transaction without at least one choice attached.
    #
    # One product.combo per course, each holding exactly that one dish. A
    # single-item choice auto-confirms in the configurator, so a fixed set is
    # still one tap for the cashier.
    combo_ids = []
    for seq, course in enumerate(courses, 1):
        # Same split as the product: the id keeps the old string, the label
        # carries the owner's format. Every choice is prefixed with the combo
        # name, so one search for "COMBO SET LUNCH 01 245000" brings back the
        # set and all six of its courses together.
        ckey = "%s — %s" % (key, course.name)
        cname = "%s — %s" % (name, course.name)
        combo = ref(env, "combo", ckey)
        vals = {"name": cname, "sequence": seq}
        if combo:
            combo.write(vals)
            combo.combo_item_ids.unlink()
        else:
            combo = env["product.combo"].create(vals)
            stamp(env, combo, "combo", ckey)
        env["product.combo.item"].create({
            "combo_id": combo.id,
            "product_id": course.product_variant_id.id,
            "extra_price": 0.0,
        })
        combo_ids.append(combo.id)

    tmpl = get_or_create(env, "product.template", "set", key, {
        "name": name,
        # The 2-pax minimum has no field in Odoo and used to live in the
        # product name. The owner's format has no room for it, so it moves to
        # the sales description rather than being dropped.
        "description_sale": MIN_PAX,
        "type": "combo",
        "list_price": spec["price"],
        "standard_price": cost,
        "available_in_pos": True,
        "sale_ok": True,
        "purchase_ok": False,
        "uom_id": uom_pax.id,
        "categ_id": categ.id,
        "taxes_id": [(6, 0, [vat.id])],
        "pos_categ_ids": [(6, 0, [pos_set.id])],
        "combo_ids": [(6, 0, combo_ids)],
    }, search_domain=[("name", "in", [name, key])])
    built += 1

note("set menus: %d built, %d skipped" % (built, skipped))

# ---------------------------------------------------------------------------
# 2. Buffet
# ---------------------------------------------------------------------------
buf = SETS["buffet"]
BUFFET_NAME = "BUFFET / PAX (CHƯA CÓ GIÁ)"

# available_in_pos is forced True even at price 0: the owner asked for the
# buffet on the till. The name carries the warning, so a 0 VND ring-up on the
# test system is self-evidently wrong rather than quietly plausible.
buffet_tmpl = get_or_create(env, "product.template", "dish", BUFFET_NAME, {
    "name": BUFFET_NAME,
    "type": "consu",
    "is_storable": True,
    "uom_id": uom_pax.id,
    "categ_id": categ.id,
    "list_price": 0.0,
    # standard_price is set from the BoM explosion after the BoM exists, the
    # way every dish's is. The sheet's own per-pax total is not used.
    "available_in_pos": True,
    "sale_ok": True,
    "purchase_ok": False,
    "taxes_id": [(6, 0, [vat.id])],
    "pos_categ_ids": [(6, 0, [pos_buffet.id])],
})

# 17 of the 38 buffet lines name goods that appear nowhere else -- not in a
# recipe, not in any department count (cereal, jam, sandwich loaves, cold
# cuts). They still have to exist as products or the buffet BoM silently
# under-deducts by nearly half. Created here from the buffet sheet's own unit
# costs, with the same 10% the recipe ingredients carry.
uom_cache = {}


def uom_named(name):
    name = (name or "Cái").strip()
    if name not in uom_cache:
        u = ref(env, "uom", name)
        if not u:
            u = env["uom.uom"].search([("name", "=", name)], limit=1)
        if not u:
            u = env["uom.uom"].create({"name": name, "relative_factor": 1.0})
            stamp(env, u, "uom", name)
        uom_cache[name] = u
    return uom_cache[name]


ing_categ = ref(env, "categ", "Nguyên liệu bếp")
SPICE = MENU.get("spice_uplift", 0.10)

# Two buffet lines quote a unit the product does not carry, so the sheet's
# quantity would be silently reinterpreted -- these units do not inter-convert
# by design, so Odoo will not catch it. Both need the owner, and neither has a
# conversion I am willing to invent:
#
#   Sandwich   buffet 68,680/Cây (loaf)  vs  recipe 6,868/miếng (slice).
#              Exactly 10x, so "10 slices to a loaf" is nearly certain -- but
#              0.15 in the sheet then means 1.5 slices per pax, not 0.15.
#   Sữa chua   buffet 6,763/Kg  vs  recipe 84,334/hủ (pot). No ratio fits;
#              one of the two figures is simply wrong.
#
# A differing unit LABEL alone is not a conflict. The buffet sheet writes "Kg"
# against 25 Trứng gà for 20 pax at 3,996 each -- plainly 25 eggs, and the
# product's per-Trái cost matches to the đồng. The sheet and the product only
# really disagree when the unit AND the price of one unit both differ.
# Listed rather than silently accepted, so a genuinely new conflict in a
# future sheet is reported instead of quietly skewing the buffet cost.
KNOWN_UNIT_CONFLICTS = {"Sandwich", "Sữa chua"}


def unit_conflict(line, product):
    if norm(line["uom"]) == norm(product.uom_id.name):
        return False
    want = (line.get("unit_cost") or 0) * (1 + SPICE)
    return abs(product.standard_price - want) > max(1.0, 0.005 * max(want, 1))

lines = []
created = costed = 0
conflicts = []
for line in buf["lines"]:
    ing = ref(env, "ing", line["ingredient"]) or ref(env, "stk", line["ingredient"])
    if ing and not ing.active:
        # ref() resolves archived records too, so these never went through
        # get_or_create's revival path. 17 of them were archived by a
        # wrong-ordered prune and a BoM line pointing at an archived product
        # is invisible in the product list the storekeeper counts from.
        ing.active = True
    if not ing:
        ing = get_or_create(env, "product.template", "ing",
                            line["ingredient"], {
                                "name": line["ingredient"],
                                "type": "consu",
                                "is_storable": True,
                                "uom_id": uom_named(line["uom"]).id,
                                "categ_id": ing_categ.id,
                                "standard_price": round(
                                    line["unit_cost"] * (1 + SPICE), 2),
                                "available_in_pos": False,
                                "purchase_ok": True,
                                "sale_ok": False,
                            })
        created += 1
    elif not ing.standard_price and line.get("unit_cost"):
        # Resolved to a department stock item, which the counts carry no price
        # for. Four buffet lines landed on one (chả lụa, ngũ cốc bắp, ớt
        # chuông, chanh bếp) and contributed 0 to the buffet's cost. The
        # buffet sheet prices them, so use that.
        ing.standard_price = round(line["unit_cost"] * (1 + SPICE), 2)
        costed += 1

    if line["ingredient"] not in KNOWN_UNIT_CONFLICTS and unit_conflict(line, ing):
        conflicts.append((line["ingredient"], line["uom"], ing.uom_id.name))

    lines.append((0, 0, {
        "product_id": ing.product_variant_id.id,
        "product_qty": line["qty_per_pax"],
        "product_uom_id": ing.uom_id.id,
    }))

bom = ref(env, "bom", BUFFET_NAME) or env["mrp.bom"].with_context(
    active_test=False).search([("product_tmpl_id", "=", buffet_tmpl.id)],
                              limit=1)
vals = {
    "product_tmpl_id": buffet_tmpl.id,
    "product_qty": 1.0,
    "type": "phantom",
    "active": True,
    "product_uom_id": buffet_tmpl.uom_id.id,
    "bom_line_ids": lines,
}
if bom:
    bom.bom_line_ids.unlink()
    bom.write(vals)
else:
    bom = env["mrp.bom"].create(vals)
stamp(env, bom, "bom", BUFFET_NAME)

# The cost is the explosion, not the sheet's own per-pax total. Every dish here
# takes standard_price = Sigma(component cost x qty), and pos_mrp derives COGS
# and margin the same way -- it never reads a kit's own standard_price. Storing
# the sheet figure instead left the buffet as the one product in the catalogue
# whose stated cost and reported margin disagreed.
rollup = sum(l.product_qty * l.product_id.standard_price
             for l in bom.bom_line_ids)
buffet_tmpl.standard_price = rollup

note("buffet: %d of %d lines (%d ingredients created, %d priced from the "
     "buffet sheet), cost %s VND/pax, PRICE NOT SET"
     % (len(lines), len(buf["lines"]), created, costed,
        "{:,.0f}".format(rollup)))
if abs(rollup - buf["cost_per_pax"] * (1 + SPICE)) > 1:
    note("   NB sheet says %s + %d%% = %s. The gap is the unit conflicts above;"
         % ("{:,.0f}".format(buf["cost_per_pax"]), SPICE * 100,
            "{:,.0f}".format(buf["cost_per_pax"] * (1 + SPICE))))
    note("   the same goods are priced twice, in two different units.")
if conflicts:
    note("!! %d NEW buffet unit conflict(s) -- the sheet quantity is being "
         "read in a different unit:" % len(conflicts))
    for name, sheet_uom, prod_uom in conflicts:
        note("     %-30s sheet %-8s product %s" % (name[:30], sheet_uom,
                                                   prod_uom))

# ---------------------------------------------------------------------------
# 3. Visitor charge -- a fee, not a dish: no recipe, no BoM
# ---------------------------------------------------------------------------
VISITOR = "KHÁCH THAM QUAN"
get_or_create(env, "product.template", "fee", VISITOR, {
    "name": VISITOR,
    "type": "service",
    "list_price": 25000.0,
    "available_in_pos": True,
    "sale_ok": True,
    "purchase_ok": False,
    "categ_id": categ.id,
    "taxes_id": [(6, 0, [vat.id])],
    "pos_categ_ids": [(6, 0, [pos_extra.id])],
})
note("visitor charge: 25,000 VND")

# ---------------------------------------------------------------------------
# 4. POS visibility
# ---------------------------------------------------------------------------
# A config with limit_categories on shows only the categories listed on it, so
# new ones are invisible until added. The original loader had a placeholder
# here that did nothing.
wired = 0
for config in env["pos.config"].search([]):
    if not config.limit_categories:
        continue
    want = config.iface_available_categ_ids
    for cat in (pos_set, pos_buffet, pos_extra):
        if cat not in want:
            want |= cat
            wired += 1
    config.iface_available_categ_ids = [(6, 0, want.ids)]
note("POS categories wired onto limited configs: %d" % wired)

env.cr.commit()
note("committed.")
