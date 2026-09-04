# -*- coding: utf-8 -*-
"""STEP 1 -- units, categories, tax, products and kit BoMs.

    YLAK_DIR=... YLAK_DATA=.../menu_data.json YLAK_INVENTORY=.../inventory_data.json \
        odoo-bin shell -c ... -d ... --no-http < load_10_catalog.py

Idempotent through external ids (see backfill_xmlids.py): every record is
found by its `__ylak__` id first and only then by name, so renaming a dish in
Odoo no longer creates a duplicate on the next run.

Loads three populations into one catalogue:
  * kitchen ingredients from the recipe sheets, costed (buy price + 10%)
  * ~1,000 stock items from the ten department counts
  * ~110 dishes, each with a phantom (kit) BoM

Requires load_00_precision.py to have run in a PREVIOUS process; asserts it.
"""
import os
import sys

sys.path.insert(0, os.environ["YLAK_DIR"])
from ylak_common import (  # noqa: E402
    get_or_create, load_json, note, norm, ref, require_precision, slug, stamp,
)

DIGITS = require_precision(env, 3)
note("decimal.precision 'Product Unit' = %d digits" % DIGITS)

MENU = load_json("YLAK_DATA")
INV = load_json("YLAK_INVENTORY")

VAT_NAME = "VAT 8%"
DISH_CATEG = "Món ăn nhà hàng"

# Not everything the extract calls a "dish" is food. The `extra Cost_ingredients`
# sheet prices five wines by the bottle and three packaged goods (honey, cocoa,
# coffee) that are resold as bought. They belong in their own product
# categories: a stock or margin report that mixes a 895,000 bottle of wine in
# with the lemongrass is not a report anyone can read.
KIND_CATEG = {
    "wine": "Rượu vang",
    "retail": "Hàng bán lẻ",
}

# Product categories mirror the seven stores, split by consumable vs durable
# so a reorder report never mixes lemongrass with dinner plates.
STORE_CATEG = {
    "BEP": ("Nguyên liệu bếp", "Công cụ dụng cụ - Bếp"),
    "NHAHANG": ("Đồ uống - Bar", "Công cụ dụng cụ - Nhà hàng"),
    "BAOTRI": ("Vật tư bảo trì", "Công cụ dụng cụ - Bảo trì"),
    "BUONGPHONG": ("Vật tư buồng phòng", "Công cụ dụng cụ - Buồng phòng"),
    "LETAN": ("Hàng lưu niệm", "Công cụ dụng cụ - Lễ tân"),
    "TOUR": ("Vật tư tour", "Công cụ dụng cụ - Tour"),
    "CAYXANH": ("Vật tư cây xanh", "Công cụ dụng cụ - Cây xanh"),
}

# ---------------------------------------------------------------------------
# 1. Units of measure
# ---------------------------------------------------------------------------
# Each Vietnamese unit is its own ROOT unit with no conversion to any other.
# That is deliberate: a kitchen BoM must never silently convert "miếng" into
# kilos. Note uom.uom.rounding is a COMPUTED field in Odoo 19 -- all units
# share the global 'Product Unit' precision -- so it is not set here.
uom_names = {d["portion_unit"] for d in MENU["dishes"] if d.get("portion_unit")}
uom_names |= {i["uom"] for i in MENU["ingredients"].values() if i.get("uom")}
uom_names |= {p["uom"] for p in INV["products"] if p.get("uom")}
uom_names |= {"pax"}

uoms = {}
for name in sorted(n for n in uom_names if n):
    uoms[name] = get_or_create(env, "uom.uom", "uom", name,
                               {"name": name, "relative_factor": 1.0},
                               create_only=True)
note("units of measure : %d" % len(uoms))


def uom_for(name):
    return uoms.get(name) or uoms.get("Cái") or list(uoms.values())[0]


# ---------------------------------------------------------------------------
# 2. Product categories
# ---------------------------------------------------------------------------
# property_valuation / property_cost_method are left unset on purpose. The
# existing categories use the defaults (standard / manual_periodic), and
# mixing real_time in alongside them under anglo-saxon accounting produces
# COGS entries for some sales and not others.
categs = {DISH_CATEG: get_or_create(env, "product.category", "categ",
                                    DISH_CATEG, {"name": DISH_CATEG})}
for name in KIND_CATEG.values():
    categs[name] = get_or_create(env, "product.category", "categ", name,
                                 {"name": name})
for store, (consumable, durable) in STORE_CATEG.items():
    for name in (consumable, durable):
        if name not in categs:
            categs[name] = get_or_create(env, "product.category", "categ",
                                         name, {"name": name})
note("product categories: %d" % len(categs))

# ---------------------------------------------------------------------------
# 3. POS categories and VAT
# ---------------------------------------------------------------------------
sections = {d.get("menu_section") or "Chưa phân loại" for d in MENU["dishes"]}
sections |= {"Set menu", "Buffet", "Phụ thu"}
pos_categs = {}
for name in sorted(sections):
    pos_categs[name] = get_or_create(env, "pos.category", "poscateg", name,
                                     {"name": name})
note("POS categories   : %d" % len(pos_categs))

# The 8% VAT is whatever this database's own chart calls it. Test was seeded by
# the first import and named it "VAT 8%"; production runs the Vietnamese TT200
# chart, where l10n_vn names it plainly "8%". Both are the same thing: an 8%
# sale tax, tax-included, which is what a printed restaurant price means.
# Resolve by external id first (so a stamped choice stays stable), then by
# name, then by shape -- and refuse to guess when the shape is ambiguous rather
# than silently taxing the whole menu at the wrong rate.
vat = ref(env, "tax", VAT_NAME) or env["account.tax"].search(
    [("name", "=", VAT_NAME), ("type_tax_use", "=", "sale"),
     ("active", "=", True)], limit=1)
if not vat:
    candidates = env["account.tax"].search([
        ("amount", "=", 8.0), ("amount_type", "=", "percent"),
        ("type_tax_use", "=", "sale"), ("active", "=", True)])
    # Archived generic-chart taxes are excluded above by active=True; the
    # TT200 migration left several 8%-ish leftovers behind.
    included = candidates.filtered(
        lambda t: t.price_include_override == "tax_included")
    chosen = included or candidates
    if len(chosen) != 1:
        raise RuntimeError(
            "cannot identify the 8%% sale VAT -- %d candidate(s): %s. Rename "
            "the right one to %r, or stamp it as __ylak__ tax_<slug>."
            % (len(chosen),
               ", ".join("%r#%s" % (t.name, t.id) for t in chosen) or "none",
               VAT_NAME))
    vat = chosen
    note("VAT resolved by shape: %r (id %s, %s)"
         % (vat.name, vat.id, vat.price_include_override))
stamp(env, vat, "tax", VAT_NAME)

# ---------------------------------------------------------------------------
# 4. Ingredients (recipe sheet) -- costed, not sellable
# ---------------------------------------------------------------------------
dish_names = {d["name"] for d in MENU["dishes"]}
dish_norms = {norm(n) for n in dish_names}

# A component named after its OWN dish is the bought good the dish is made
# from -- a tub of ice cream, a pot of yoghurt, a tray of duck eggs -- not the
# dish itself. Treating those as nested dishes made four BoMs reference their
# own product, which Odoo rejects as a cycle.
SELF_NAMED = {
    c["ingredient"]
    for d in MENU["dishes"] for c in d["components"]
    if norm(c["ingredient"]) == norm(d["name"])
}
# Where the bought good and the dish are spelled the same, the ingredient needs
# its own name or the two are indistinguishable on screen. Compared with norm()
# like SELF_NAMED itself, not by exact string: the dish is written "BỘT CACAO"
# and the good "Bột Cacao", so an exact test left eight pairs of same-named
# products differing only in capitalisation.
RENAME_INGREDIENT = {n: "%s (nguyên liệu)" % n for n in SELF_NAMED}

# One good, two products. The recipe sheets and the department stock count
# capitalise differently -- "ỐNG CƠM LAM" against "Ống cơm lam" -- and product
# names are case-sensitive, so nine goods existed twice: the counted copy held
# the 30 bamboo tubes and never moved, while the recipe copy that every BoM
# line deducts sat at zero and went negative on the first sale. The extract now
# canonicalises to the stock count's spelling, but the `ing_` external id still
# points at the old twin, so it is repointed here and the twin archived.
absorbed = []
for ing in MENU["ingredients"].values():
    twin = ref(env, "ing", ing["name"])
    counted = ref(env, "stk", ing["name"])
    if not (twin and counted) or twin.id == counted.id:
        continue
    row = env["ir.model.data"].search([
        ("module", "=", "__ylak__"), ("model", "=", "product.template"),
        ("name", "=", "ing_%s" % slug(ing["name"]))], limit=1)
    if row:
        row.res_id = counted.id
    if not counted.standard_price and twin.standard_price:
        counted.standard_price = twin.standard_price
    twin.active = False
    absorbed.append((twin.display_name, counted.display_name))
if absorbed:
    # Order matters, and getting it wrong is silent. env.ref() answers from a
    # registry-wide xmlid cache, so the cache has to be cleared or the very
    # next lookup returns the archived twin, get_or_create revives it, and the
    # merge undoes itself. But clearing also DISCARDS pending ORM writes, so
    # flush first -- otherwise the repoint and the archive are thrown away and
    # every run reports the same merge again having changed nothing.
    env.flush_all()
    env.registry.clear_cache()
    note("!! %d duplicate good(s) merged into the counted product; the recipe "
         "copy is archived:" % len(absorbed))
    for was, now in absorbed:
        note("     %-34s -> %s" % (was[:34], now[:34]))

ing_products = {}
for ing in MENU["ingredients"].values():
    name = ing["name"]
    # Genuine nesting -- one dish used inside another -- points the BoM at the
    # dish product instead of duplicating it.
    if (name in dish_names or norm(name) in dish_norms) \
            and name not in SELF_NAMED:
        continue
    tmpl = get_or_create(env, "product.template", "ing", name, {
        "name": RENAME_INGREDIENT.get(name, name),
        "type": "consu",
        "is_storable": True,
        "uom_id": uom_for(ing.get("uom")).id,
        "categ_id": categs["Nguyên liệu bếp"].id,
        "standard_price": ing.get("standard_cost") or 0.0,
        "available_in_pos": False,
        "purchase_ok": True,
        "sale_ok": False,
    })
    ing_products[name] = tmpl
note("recipe ingredients: %d" % len(ing_products))

# ---------------------------------------------------------------------------
# 5. Department stock items
# ---------------------------------------------------------------------------
stock_products = {}
for item in INV["products"]:
    name = item["name"]
    if name in ing_products or name in dish_names:
        # Already created from the recipe sheet, which carries a cost; the
        # stock count carries none, so do not overwrite it.
        stock_products[name] = ing_products.get(name)
        continue
    consumable, durable = STORE_CATEG[item["store"]]
    tmpl = get_or_create(env, "product.template", "stk", name, {
        "name": name,
        "type": "consu",
        "is_storable": True,
        "uom_id": uom_for(item.get("uom")).id,
        "categ_id": categs[durable if item["is_equipment"] else consumable].id,
        "available_in_pos": False,
        "purchase_ok": True,
        "sale_ok": False,
    })
    stock_products[name] = tmpl
note("department stock items: %d" % len(stock_products))

# ---------------------------------------------------------------------------
# 6. Dishes
# ---------------------------------------------------------------------------
# available_in_pos follows the price: a 0 VND ring-up is worse than a missing
# button, and an unpriced dish switches itself on as soon as a price arrives
# and this runs again.
dish_products = {}
sellable = 0
for dish in MENU["dishes"]:
    price = dish.get("sale_price") or 0.0
    section = dish.get("menu_section") or "Chưa phân loại"
    tmpl = get_or_create(env, "product.template", "dish", dish["name"], {
        "name": dish["name"],
        "type": "consu",
        "is_storable": True,
        "uom_id": uom_for(dish.get("portion_unit")).id,
        "categ_id": categs[KIND_CATEG.get(dish.get("kind"), DISH_CATEG)].id,
        "list_price": price,
        "standard_price": dish.get("standard_cost") or 0.0,
        "available_in_pos": bool(price),
        "sale_ok": True,
        "purchase_ok": False,
        "taxes_id": [(6, 0, [vat.id])],
        "pos_categ_ids": [(6, 0, [pos_categs[section].id])],
    })
    dish_products[dish["name"]] = tmpl
    if price:
        sellable += 1
note("dishes: %d (%d sellable in POS, %d hidden pending a price)"
     % (len(dish_products), sellable, len(dish_products) - sellable))

# ---------------------------------------------------------------------------
# 7. Kit BoMs
# ---------------------------------------------------------------------------
# phantom = Kit: selling the dish explodes into its ingredients, so stock
# moves hit the raw goods and never the dish itself.
bom_count = line_count = 0
missing_components = []

for dish in MENU["dishes"]:
    tmpl = dish_products[dish["name"]]
    lines = []
    for comp in dish["components"]:
        cname = comp["ingredient"]
        if norm(cname) == norm(dish["name"]):
            # Self-named: always the bought good, never the dish.
            target = ing_products.get(cname)
        else:
            target = ing_products.get(cname) or dish_products.get(cname)
        if not target:
            missing_components.append((dish["name"], cname))
            continue
        lines.append((0, 0, {
            "product_id": target.product_variant_id.id,
            "product_qty": comp["qty"],
            # The component's OWN unit -- these units do not inter-convert.
            "product_uom_id": target.uom_id.id,
        }))
    if not lines:
        continue

    bom = ref(env, "bom", dish["name"]) or env["mrp.bom"].with_context(
        active_test=False).search([("product_tmpl_id", "=", tmpl.id)], limit=1)
    vals = {
        "product_tmpl_id": tmpl.id,
        "product_qty": 1.0,
        "type": "phantom",
        # Explicit: a BoM the prune archived on an earlier run has to come back
        # when the extract asks for it again.
        "active": True,
        "product_uom_id": tmpl.uom_id.id,
        "bom_line_ids": lines,
    }
    if bom:
        bom.bom_line_ids.unlink()
        bom.write(vals)
    else:
        bom = env["mrp.bom"].create(vals)
    stamp(env, bom, "bom", dish["name"])
    bom_count += 1
    line_count += len(lines)

note("kit BoMs: %d with %d lines" % (bom_count, line_count))

# A raw good must never carry a kit BoM. One did: the duck egg
# TRỨNG VỊT HỒ LAK CHIÊN THỊT BẰM shares its name with the dish, so before
# RENAME_INGREDIENT existed they were one product; the dish's BoM was written
# onto it and stayed attached to the ingredient when the rename split the two.
# It listed ITSELF as a component, so selling the dish exploded into a kit that
# exploded into itself and the egg was never deducted at all.
raw_goods = env["product.template"]
for tmpl in list(ing_products.values()) + list(stock_products.values()):
    if tmpl:
        raw_goods |= tmpl
stray_boms = env["mrp.bom"].search([("product_tmpl_id", "in", raw_goods.ids)])
if stray_boms:
    note("!! %d BoM(s) on a raw ingredient -- archived, a bought good is not a "
         "kit:" % len(stray_boms))
    for bom in stray_boms:
        note("     %s" % bom.product_tmpl_id.display_name[:60])
    stray_boms.active = False
if missing_components:
    note("!! %d BoM line(s) dropped -- no such product:" % len(missing_components))
    for dish_name, ing in missing_components[:15]:
        note("     %-40s needs %s" % (dish_name[:40], ing))

env.cr.commit()
note("committed.")
