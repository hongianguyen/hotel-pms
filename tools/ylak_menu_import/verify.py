# -*- coding: utf-8 -*-
"""Read-only assertions over a loaded database. Exits non-zero on any failure.

    YLAK_DIR=... YLAK_DATA=... YLAK_INVENTORY=... YLAK_SETS=... \
        odoo-bin shell -c ... -d ... --no-http < verify.py

Checks outcomes rather than restating the loaders: quantities that survived
the write, counts that match the extract, and the POS conditions that decide
whether any of this is actually reachable from a till.
"""
import os
import re
import sys

sys.path.insert(0, os.environ["YLAK_DIR"])
from ylak_common import load_json, note, product_unit_digits, ref  # noqa: E402

MENU = load_json("YLAK_DATA")
INV = load_json("YLAK_INVENTORY")
SETS = load_json("YLAK_SETS")

failures = []

BUFFET = "BUFFET / PAX (CHƯA CÓ GIÁ)"


def SET_NAME(spec):
    """The external-id KEY for a set -- the original constructed name, which
    load_20_sets.py keeps feeding to slug() so the owner's rename does not mint
    a new id and orphan the product. Not what the product is called."""
    return "%s - %s (tối thiểu 2 khách)" % (
        spec["tier"].split("/")[0].strip(), spec["variant"])


def SET_LABEL(spec):
    """What the set is CALLED: the owner's 'COMBO SET LUNCH 01 245000'."""
    head = re.sub(r"[\d.,]+\s*$", "",
                  spec["tier"].split("/")[0].strip()).strip()
    num = re.search(r"(\d+)", spec["variant"] or "")
    return "COMBO %s %02d %d" % (head.upper(), int(num.group(1)) if num else 0,
                                 round(spec["price"]))


def check(label, ok, detail=""):
    note("  %-58s %s" % (label, "OK" if ok else "FAIL"))
    if detail:
        note("      %s" % detail)
    if not ok:
        failures.append(label)


note("=" * 72)
note("PRECISION")
_prec, digits = product_unit_digits(env)
check("decimal.precision 'Product Unit' >= 3", digits >= 3, "%d digits" % digits)

# Generalised past the nine known lines: every recipe quantity must have
# survived the write exactly.
drift = []
for dish in MENU["dishes"]:
    bom = ref(env, "bom", dish["name"])
    if not bom:
        continue
    stored = {}
    for line in bom.bom_line_ids:
        stored.setdefault(line.product_id.display_name, []).append(
            line.product_qty)
    for comp in dish["components"]:
        want = comp["qty"]
        got = None
        for name, qtys in stored.items():
            if any(abs(q - want) < 1e-9 for q in qtys):
                got = want
                break
        if got is None and want:
            drift.append((dish["name"], comp["ingredient"], want))
check("every recipe quantity stored exactly", not drift,
      "%d line(s) drifted" % len(drift) if drift else "")
for d, i, q in drift[:5]:
    note("      %s / %s expected %g" % (d[:36], i[:22], q))

# The invariant is that nothing was rounded, not a fixed count: the number of
# sub-0.01 lines grew with the dish list, so a hard-coded 9 (the old 73-dish
# baseline) fails on correct data. 0.08 is the tell -- it is what 0.075
# becomes when the precision guard is bypassed.
# Scoped to ACTIVE BoMs. mrp.bom.line has no active field of its own, so an
# unscoped count also picks up the archived BoMs from the superseded import --
# which is where the old COST.xlsx's 0.075 lines still live.
sub_cent = env["mrp.bom.line"].search([("product_qty", "<", 0.01),
                                       ("product_qty", ">", 0)])
sub_cent = sub_cent.filtered(lambda l: l.bom_id.active)
rounded = env["mrp.bom.line"].search([("product_qty", "=", 0.08)])
rounded = rounded.filtered(lambda l: l.bom_id.active)
want_rounded = sum(1 for d in MENU["dishes"] for c in d["components"]
                   if abs(c["qty"] - 0.08) < 1e-9)
check("no active BoM line was rounded up to 0.08",
      len(rounded) == want_rounded,
      "0.08 x%d (extract has %d); %d line(s) below 0.01 survived"
      % (len(rounded), want_rounded, len(sub_cent)))

note("")
note("CATALOGUE")

# env.ref() resolves archived records, so "exists" checks alone stayed green
# while the buffet and 17 of its ingredients sat archived -- retired by a
# wrong-ordered prune and never revived, because the loaders' diff-only write
# never touches `active`. Every id the extract is entitled to own must resolve
# to a LIVE record.
retired = []
for prefix, names in (
        ("dish", [d["name"] for d in MENU["dishes"]] + [BUFFET]),
        ("bom", [d["name"] for d in MENU["dishes"]] + [BUFFET]),
        ("ing", [l["ingredient"] for l in SETS["buffet"]["lines"]]),
        ("set", [SET_NAME(s) for s in SETS["sets"] if not s.get("incomplete")]),
):
    for name in names:
        rec = ref(env, prefix, name)
        if rec and not rec.active:
            retired.append("%s/%s" % (prefix, rec.display_name))
check("nothing the extract still wants is archived", not retired,
      "%d archived, e.g. %s" % (len(retired), retired[0]) if retired else "")

dishes = [d for d in MENU["dishes"] if ref(env, "dish", d["name"])]
check("every dish has a product", len(dishes) == len(MENU["dishes"]),
      "%d/%d" % (len(dishes), len(MENU["dishes"])))

boms = [d for d in MENU["dishes"] if ref(env, "bom", d["name"])]
check("every dish has a BoM", len(boms) == len(MENU["dishes"]),
      "%d/%d" % (len(boms), len(MENU["dishes"])))

non_phantom = [d["name"] for d in MENU["dishes"]
               if (ref(env, "bom", d["name"]) or env["mrp.bom"]).type != "phantom"]
check("every dish BoM is a kit (phantom)", not non_phantom,
      ", ".join(non_phantom[:4]))

zero_cost = [line.product_id.display_name
             for d in MENU["dishes"]
             for line in (ref(env, "bom", d["name"]) or env["mrp.bom"]).bom_line_ids
             if not line.product_id.standard_price]
check("no BoM line points at a zero-cost product", not zero_cost,
      "%d line(s), e.g. %s" % (len(zero_cost), zero_cost[0]) if zero_cost else "")

# "The BoM is set according to cost correctly" -- the requirement in the
# owner's own words. A dish's standard_price and its BoM are two independent
# writes from the same JSON, and nothing tied them together: pos_mrp reports
# COGS and margin by exploding the BoM and summing COMPONENT costs, never
# reading the kit's own standard_price, so a product whose stated cost differs
# from its explosion shows a margin that contradicts its own cost field.
# Tolerance is 0.5% or 1 VND, whichever is larger -- costs are rounded to 2dp
# per ingredient and multiplied by quantities as small as 0.001.
unreconciled = []
for name in [d["name"] for d in MENU["dishes"]] + [BUFFET]:
    tmpl, bom = ref(env, "dish", name), ref(env, "bom", name)
    if not tmpl or not bom:
        continue
    rollup = sum(l.product_qty * l.product_id.standard_price
                 for l in bom.bom_line_ids)
    if abs(rollup - tmpl.standard_price) > max(1.0, 0.005 * max(rollup, 1)):
        unreconciled.append((name, tmpl.standard_price, rollup))
check("dish cost == its BoM explosion", not unreconciled,
      "%d diverge, e.g. %s: product %.0f vs BoM %.0f"
      % ((len(unreconciled),) + unreconciled[0]) if unreconciled else
      "%d dishes + buffet" % len(MENU["dishes"]))

# The zero-cost check above walks MENU dishes only, so the buffet -- whose BoM
# is built from a different sheet -- was never covered. Four of its lines
# resolved to department stock items, which carry no price, and contributed
# nothing to the buffet's cost.
buf_zero = [l.product_id.display_name
            for l in (ref(env, "bom", BUFFET) or env["mrp.bom"]).bom_line_ids
            if not l.product_id.standard_price]
check("no buffet BoM line points at a zero-cost product", not buf_zero,
      "%d line(s), e.g. %s" % (len(buf_zero), buf_zero[0]) if buf_zero else "")

# A component whose product carries a different unit from the one the sheet
# quoted means the quantity is being read in the wrong unit. These units are
# deliberately non-convertible roots, so Odoo raises nothing. A differing
# label alone is not enough -- the sheet writes "Kg" against a count of eggs
# whose per-egg price matches exactly. Both the unit and the price of one unit
# have to disagree. Mirrors unit_conflict() in load_20_sets.py.
KNOWN_UNIT_CONFLICTS = {"Sandwich", "Sữa chua"}
SPICE = MENU.get("spice_uplift", 0.10)
unit_clash = []
for line in SETS["buffet"]["lines"]:
    prod = ref(env, "ing", line["ingredient"]) or ref(env, "stk", line["ingredient"])
    if not prod or line["ingredient"] in KNOWN_UNIT_CONFLICTS:
        continue
    want = (line.get("unit_cost") or 0) * (1 + SPICE)
    if prod.uom_id.name.strip().lower() != line["uom"].strip().lower() \
            and abs(prod.standard_price - want) > max(1.0, 0.005 * max(want, 1)):
        unit_clash.append("%s (sheet %s, product %s)"
                          % (line["ingredient"], line["uom"], prod.uom_id.name))
check("no NEW buffet unit conflict", not unit_clash,
      ", ".join(unit_clash[:3]) if unit_clash else
      "%d known, awaiting the owner" % len(KNOWN_UNIT_CONFLICTS))

# A bought good must not be a kit. The duck egg carried a phantom BoM listing
# ITSELF, left behind when the dish and the ingredient -- which share a name --
# were split into two products: selling the dish exploded into a kit that
# exploded into itself, and the egg was never deducted.
raw_boms = []
for ing in MENU["ingredients"].values():
    tmpl = ref(env, "ing", ing["name"])
    if not tmpl:
        continue
    bom = env["mrp.bom"].search([("product_tmpl_id", "=", tmpl.id)], limit=1)
    if bom:
        raw_boms.append(tmpl.display_name)
check("no raw ingredient carries a BoM", not raw_boms,
      "%d, e.g. %s" % (len(raw_boms), raw_boms[0]) if raw_boms else "")

# One good, two products. The recipe sheets and the stock count capitalise
# differently, and product names are case-sensitive, so nine goods existed
# twice: the counted copy held the stock and never moved, while the recipe
# copy every BoM line deducts sat at zero. The recipe name is canonicalised to
# the stock count's at extract time and the `ing_` id repointed at load.
split_goods = []
for ing in MENU["ingredients"].values():
    a, b = ref(env, "ing", ing["name"]), ref(env, "stk", ing["name"])
    if a and b and a.id != b.id and a.active and b.active:
        split_goods.append("%s / %s" % (a.display_name, b.display_name))
check("no good exists as both a recipe and a stock product", not split_goods,
      "%d, e.g. %s" % (len(split_goods), split_goods[0]) if split_goods else "")

priced = [d for d in MENU["dishes"] if d.get("sale_price")]
in_pos = [d for d in MENU["dishes"]
          if (ref(env, "dish", d["name"]) or env["product.template"]).available_in_pos]
check("sellable dishes == priced dishes", len(in_pos) == len(priced),
      "%d in POS, %d priced" % (len(in_pos), len(priced)))

zero_priced = env["product.template"].search_count([
    ("available_in_pos", "=", True), ("list_price", "=", 0),
    ("type", "!=", "combo"), ("name", "not like", "CHƯA CÓ GIÁ"),
])
check("nothing sellable at 0 VND (buffet excepted)", zero_priced == 0,
      "%d product(s)" % zero_priced)

note("")
note("SET MENUS")
built = [s for s in SETS["sets"] if not s.get("incomplete")]
found = 0
bad_price = []
for spec in built:
    name = SET_NAME(spec)
    tmpl = ref(env, "set", name)
    if not tmpl:
        continue
    found += 1
    if abs(tmpl.list_price - spec["price"]) > 0.5:
        bad_price.append(name)
    if len(tmpl.combo_ids) != len(spec["courses"]):
        failures.append("%s course count" % name)
check("every complete set exists", found == len(built),
      "%d/%d" % (found, len(built)))

# The rename is the point of the whole exercise, and it is invisible to every
# other check -- they all resolve by external id, which deliberately did not
# change. A set left under its old label would pass all of them.
mislabelled = []
for spec in built:
    tmpl = ref(env, "set", SET_NAME(spec))
    if tmpl and tmpl.name != SET_LABEL(spec):
        mislabelled.append("%s (want %s)" % (tmpl.name, SET_LABEL(spec)))
check("every set carries the owner's COMBO name", not mislabelled,
      ", ".join(mislabelled[:2]) if mislabelled else
      "e.g. %s" % SET_LABEL(built[0]))

# Each course choice is prefixed with the combo name, so one search brings the
# set and all its courses back together -- which is what was asked for.
unprefixed = []
for spec in built:
    tmpl = ref(env, "set", SET_NAME(spec))
    if not tmpl:
        continue
    for combo in tmpl.combo_ids:
        if not combo.name.startswith(SET_LABEL(spec)):
            unprefixed.append(combo.name)
check("every course choice is prefixed with its combo name", not unprefixed,
      "%d, e.g. %s" % (len(unprefixed), unprefixed[0]) if unprefixed else "")
check("set prices match the tier", not bad_price, ", ".join(bad_price[:3]))

incomplete = [s for s in SETS["sets"] if s.get("incomplete")]
leaked = [s for s in incomplete if ref(env, "set", SET_NAME(s))]
check("incomplete sets were NOT loaded", not leaked,
      "%d leaked" % len(leaked) if leaked else
      "%d correctly withheld" % len(incomplete))

empty = env["product.template"].search([("type", "=", "combo")]).filtered(
    lambda t: not t.combo_ids)
check("no combo product without choices", not empty, "%d" % len(empty))

note("")
note("BUFFET")
buf_tmpl = ref(env, "dish", BUFFET)
buf_bom = ref(env, "bom", BUFFET)
check("buffet product exists", bool(buf_tmpl))
check("buffet BoM has every line", bool(buf_bom) and
      len(buf_bom.bom_line_ids) == len(SETS["buffet"]["lines"]),
      "%d/%d" % (len(buf_bom.bom_line_ids) if buf_bom else 0,
                 len(SETS["buffet"]["lines"])))
if buf_bom:
    smallest = min(buf_bom.bom_line_ids.mapped("product_qty"))
    check("buffet quantities clear the UP-rounding floor",
          smallest >= 10 ** -digits * 10,
          "smallest %.5f, floor %.5f" % (smallest, 10 ** -digits * 10))

note("")
note("INVENTORY")
locs = {code: ref(env, "loc", code) for code in INV["stores"]}
check("every store has a location", all(locs.values()),
      "%d/%d" % (sum(1 for l in locs.values() if l), len(locs)))

grp = env.ref("stock.group_stock_multi_locations", raise_if_not_found=False)
check("multi-location is enabled",
      bool(grp) and grp in env.ref("base.group_user").implied_ids)

mismatch = []
for row in INV["quants"]:
    tmpl = ref(env, "stk", row["name"]) or ref(env, "ing", row["name"])
    loc = locs.get(row["store"])
    if not tmpl or not loc:
        mismatch.append((row["name"], "no product/location"))
        continue
    q = env["stock.quant"].search([
        ("product_id", "=", tmpl.product_variant_id.id),
        ("location_id", "=", loc.id)], limit=1)
    if not q or abs(q.quantity - row["qty"]) > 1e-6:
        mismatch.append((row["name"], "%s vs %s"
                         % (q.quantity if q else "none", row["qty"])))
check("every counted quantity matches the sheet", not mismatch,
      "%d mismatch(es)" % len(mismatch))
for name, why in mismatch[:5]:
    note("      %-42s %s" % (name[:42], why))

negative = env["stock.quant"].search_count([
    ("location_id", "in", [l.id for l in locs.values() if l]),
    ("quantity", "<", 0)])
check("no negative stock in any store", negative == 0, "%d" % negative)

note("")
note("POS REACHABILITY")
configs = env["pos.config"].search([])
hidden = []
for config in configs:
    if not config.limit_categories:
        continue
    for cat_name in ("Set menu", "Buffet", "Phụ thu"):
        cat = ref(env, "poscateg", cat_name)
        if cat and cat not in config.iface_available_categ_ids:
            hidden.append("%s/%s" % (config.name, cat_name))
check("new POS categories are visible on limited configs", not hidden,
      ", ".join(hidden[:4]))

note("")
note("=" * 72)
if failures:
    note("%d CHECK(S) FAILED:" % len(failures))
    for f in failures:
        note("   - %s" % f)
    sys.exit(1)
note("all checks passed")
