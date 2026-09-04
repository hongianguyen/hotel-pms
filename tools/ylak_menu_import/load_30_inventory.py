# -*- coding: utf-8 -*-
"""STEP 3 -- per-store stock locations and the opening count.

    YLAK_DIR=... YLAK_INVENTORY=.../inventory_data.json \
        odoo-bin shell -c ... -d ... --no-http < load_30_inventory.py

One warehouse, seven internal locations under WH/Stock -- the owner's choice,
and the right one: everything is on a single site, so transfers between stores
stay ordinary internal moves and one report still shows the whole camp. Six
warehouses would mean six picking types, six sequences and an inter-warehouse
route for every transfer.

Opening stock goes in as a real inventory adjustment (inventory_quantity plus
action_apply_inventory), never a direct write to stock.quant.quantity. A
direct write leaves valuation with no backing moves, which is unauditable and
matters here because stock_account is installed with anglo-saxon accounting.

Idempotency is by OUTCOME, not by reference. The `inventory_name` context key
does not survive onto stock.move.reference -- Odoo stamps its own "Product
Quantity Confirmed" -- so a reference-based key silently matched nothing and
re-running applied every row a second time. Instead each row is compared to
the quantity already on hand and skipped when it agrees, which is a true no-op
on re-run and needs no marker at all.
"""
import os
import sys

sys.path.insert(0, os.environ["YLAK_DIR"])
from ylak_common import load_json, note, ref, stamp  # noqa: E402

INV = load_json("YLAK_INVENTORY")
REFERENCE = "YLAK opening 24/08/2026"
CHUNK = 100

# Resolve the warehouse explicitly. `search([], limit=1)` was fine while test
# had one warehouse, but production has two -- WH ("Bao Tri-Maintenance") and
# HK ("Housekeeping") -- and the arbitrary first row would silently decide
# where 1,081 counted items live. WH is the main site warehouse (its stock
# location is WH/Stock); HK is housekeeping's own. Override with YLAK_WAREHOUSE
# if that ever stops being true.
WH_CODE = os.environ.get("YLAK_WAREHOUSE", "WH")
warehouse = env["stock.warehouse"].search([("code", "=", WH_CODE)], limit=1)
if not warehouse:
    raise RuntimeError(
        "no stock.warehouse with code %r -- have: %s" % (
            WH_CODE, ", ".join(env["stock.warehouse"].search([]).mapped("code"))))
parent = warehouse.lot_stock_id
note("warehouse %s, stock location %s" % (warehouse.name, parent.complete_name))

# ---------------------------------------------------------------------------
# 1. One internal location per store
# ---------------------------------------------------------------------------
locations = {}
for code, label in sorted(INV["stores"].items()):
    loc = ref(env, "loc", code)
    if not loc:
        loc = env["stock.location"].search([
            ("location_id", "=", parent.id), ("name", "=", label),
        ], limit=1)
    if not loc:
        loc = env["stock.location"].create({
            "name": label,
            "location_id": parent.id,
            "usage": "internal",
            # Counted on a cycle rather than transaction by transaction: much
            # of this is crockery and hand tools, which nobody books out.
            "cyclic_inventory_frequency": 30,
        })
    stamp(env, loc, "loc", code)
    locations[code] = loc
note("stock locations  : %d" % len(locations))

# ---------------------------------------------------------------------------
# 2. Opening count
# ---------------------------------------------------------------------------
Quant = env["stock.quant"].with_context(
    inventory_mode=True, inventory_name=REFERENCE)

pending = []
missing = []
agreed = 0
expected = set()
for row in INV["quants"]:
    tmpl = ref(env, "stk", row["name"]) or ref(env, "ing", row["name"])
    if not tmpl:
        missing.append(row["name"])
        continue
    variant = tmpl.product_variant_id
    loc = locations[row["store"]]
    expected.add((variant.id, loc.id))
    on_hand = env["stock.quant"].search([
        ("product_id", "=", variant.id), ("location_id", "=", loc.id),
    ], limit=1)
    if on_hand and abs(on_hand.quantity - row["qty"]) < 1e-6:
        agreed += 1
        continue
    pending.append((variant, loc, row["qty"]))

note("stock rows: %d to apply, %d already agree, %d product not found"
     % (len(pending), agreed, len(missing)))

# Quants this toolchain put in a Y Lak location that the current extract no
# longer accounts for -- left behind when two source rows that used to share
# an external id were split into separate products.
strays = env["stock.quant"].search([
    ("location_id", "in", [l.id for l in locations.values()]),
])
# Only ones still holding stock. action_apply_inventory() empties a quant but
# does not delete the row, so an unconditional filter re-reports the same three
# lines on every run -- noise that makes a genuinely dirty run hard to spot.
strays = strays.filtered(
    lambda q: (q.product_id.id, q.location_id.id) not in expected
    and abs(q.quantity) > 1e-6)
if strays:
    note("clearing %d stray quant line(s) the extract no longer produces:"
         % len(strays))
    for q in strays:
        note("     %-40s %s  qty %g"
             % (q.product_id.display_name[:40], q.location_id.name, q.quantity))
    strays.with_context(inventory_mode=True).write({"inventory_quantity": 0})
    strays.with_context(inventory_mode=True).action_apply_inventory()

applied = 0
for start in range(0, len(pending), CHUNK):
    batch = pending[start:start + CHUNK]
    quants = env["stock.quant"]
    for variant, loc, qty in batch:
        quants |= Quant.create({
            "product_id": variant.id,
            "location_id": loc.id,
            "inventory_quantity": qty,
        })
    quants.action_apply_inventory()
    applied += len(batch)
    # Commit per chunk: ~1,000 _action_done() calls in one transaction is slow
    # on a small VPS, and an abort at the end would lose the lot.
    env.cr.commit()
    note("  applied %d/%d" % (applied, len(pending)))

if missing:
    note("!! %d stock row(s) had no product:" % len(missing))
    for name in missing[:15]:
        note("     %s" % name)

# ---------------------------------------------------------------------------
# 3. Report
# ---------------------------------------------------------------------------
note("")
note("=" * 68)
for code, loc in sorted(locations.items()):
    quants = env["stock.quant"].search([("location_id", "=", loc.id)])
    on_hand = len(quants.filtered(lambda q: q.quantity))
    note("  %-12s %-26s %4d lines, %3d with stock"
         % (code, INV["stores"][code], len(quants), on_hand))
note("=" * 68)

env.cr.commit()
note("committed.")
