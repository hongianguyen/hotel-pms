# -*- coding: utf-8 -*-
"""Prove a POS sale deducts raw ingredients. Destructive -- test DB only.

    YLAK_DIR=... YLAK_DATA=... YLAK_SETS=... \
        odoo-bin shell -c ... -d ... --no-http < smoke_pos.py

Everything else in this toolchain checks what is stored. This checks what
happens when someone sells it, which is the whole point of the kit BoMs: if
phantom explosion does not fire on a POS order, nothing ever deducts an
ingredient and "inventory set up so we can follow it" is hollow -- the counts
would simply sit at their opening figures forever.

Two orders, one session:

  1. an a-la-carte dish  -- single-level explosion, never confirmed for the
     73 BoMs of the first import either
  2. a set menu          -- a combo, so each course lands as its own order
     line and each of those must explode in turn

Asserts stock moves reach the INGREDIENT products and that no move is booked
against the dish or the set itself. Rolls back at the end: this leaves a paid
session and real stock moves behind otherwise.
"""
import os
import sys

sys.path.insert(0, os.environ["YLAK_DIR"])
from ylak_common import load_json, note, ref  # noqa: E402

MENU = load_json("YLAK_DATA")
SETS = load_json("YLAK_SETS")

failures = []


def check(label, ok, detail=""):
    note("  %-56s %s" % (label, "OK" if ok else "FAIL"))
    if detail:
        note("      %s" % detail)
    if not ok:
        failures.append(label)


# Reuse an already-open session if there is one -- a config may have only one,
# and this script must not close somebody's till to make room for itself.
session = env["pos.session"].search([("state", "=", "opened")], limit=1)
config = session.config_id or env["pos.config"].search([], limit=1)
if not config:
    raise RuntimeError("no pos.config on this database")

# Pick a dish that is priced, has a BoM with lines, and whose components are
# all storable -- a service component would legitimately produce no move.
# The one with the MOST components, not merely the first: a single-ingredient
# soup passing proves far less than an eight-line stir-fry.
candidates = []
for d in MENU["dishes"]:
    tmpl, bom = ref(env, "dish", d["name"]), ref(env, "bom", d["name"])
    if not (tmpl and bom and d.get("sale_price") and bom.bom_line_ids):
        continue
    if all(l.product_id.is_storable for l in bom.bom_line_ids):
        candidates.append((len(bom.bom_line_ids), tmpl, bom))
if not candidates:
    raise RuntimeError("no priced dish with an all-storable kit BoM")
_n, dish, dish_bom = max(candidates, key=lambda c: c[0])

spec = next((s for s in SETS["sets"] if not s.get("incomplete")), None)
set_tmpl = ref(env, "set", "%s - %s (tối thiểu 2 khách)"
               % (spec["tier"].split("/")[0].strip(), spec["variant"])) if spec else None

note("dish : %s (%d component lines)" % (dish.name, len(dish_bom.bom_line_ids)))
note("set  : %s" % (set_tmpl.name if set_tmpl else "none"))

if session:
    note("reusing open session %s" % session.name)
else:
    session = env["pos.session"].create({"config_id": config.id,
                                         "user_id": env.uid})
    session.action_pos_session_open()

pricelist = config.pricelist_id
partner = env["res.partner"].search([], limit=1)


def ring(lines, ref_name):
    """Create and pay one order. `lines` is [(variant, qty, price)]."""
    order_lines = [(0, 0, {
        "product_id": v.id,
        "qty": q,
        "price_unit": p,
        "price_subtotal": q * p,
        "price_subtotal_incl": q * p,
    }) for v, q, p in lines]
    total = sum(q * p for _, q, p in lines)
    order = env["pos.order"].create({
        "session_id": session.id,
        "company_id": env.company.id,
        "partner_id": partner.id,
        "pricelist_id": pricelist.id if pricelist else False,
        "lines": order_lines,
        "amount_tax": 0.0,
        "amount_total": total,
        "amount_paid": total,
        "amount_return": 0.0,
    })
    order.action_pos_order_paid()
    # The POS front end reaches this through _process_saved_order(), which
    # calls action_pos_order_paid() and then _create_order_picking(). Paying
    # alone moves no stock, which is why the first run of this saw zero moves
    # and looked like a broken kit BoM.
    order._create_order_picking()
    return order


def moves_for(order):
    if not order.picking_ids:
        raise RuntimeError(
            "no picking for %s -- this session is set to update stock at "
            "closing, which this test does not cover" % order.name)
    picking = order.picking_ids
    # A phantom BoM is exploded by stock.move.action_explode(): the component
    # moves REPLACE the kit's own move on the picking, so move_ids is already
    # the exploded set. move_orig_ids is included for the chained case.
    return picking.move_ids | picking.move_ids.mapped("move_orig_ids")


# ---------------------------------------------------------------------------
# 1. A la carte
# ---------------------------------------------------------------------------
note("")
note("A LA CARTE")
order = ring([(dish.product_variant_id, 1.0, dish.list_price)], "smoke-dish")
moved = moves_for(order).mapped("product_id")
want = dish_bom.bom_line_ids.mapped("product_id")
check("the dish itself is NOT stock-moved", dish.product_variant_id not in moved,
      "moved: %s" % ", ".join(moved.mapped("display_name")[:4]))
check("every ingredient is stock-moved",
      all(p in moved for p in want),
      "%d of %d ingredients moved"
      % (len([p for p in want if p in moved]), len(want)))

# ---------------------------------------------------------------------------
# 2. Set menu
# ---------------------------------------------------------------------------
if set_tmpl:
    note("")
    note("SET MENU (combo)")
    courses = set_tmpl.combo_ids.combo_item_ids.mapped("product_id")
    # A real POS combo order carries combo_item_id on each child line; created
    # here as plain lines for the courses, which is what reaches stock either
    # way -- the parent combo product is never itself delivered.
    order = ring([(c, 1.0, 0.0) for c in courses], "smoke-set")
    moved = moves_for(order).mapped("product_id")
    course_boms = env["mrp.bom"]
    for c in courses:
        course_boms |= env["mrp.bom"].search(
            [("product_tmpl_id", "=", c.product_tmpl_id.id)], limit=1)
    want = course_boms.bom_line_ids.mapped("product_id")
    check("no course product is itself stock-moved",
          not any(c in moved for c in courses))
    check("every course's ingredients are stock-moved",
          all(p in moved for p in want),
          "%d of %d ingredients across %d courses"
          % (len([p for p in want if p in moved]), len(want), len(courses)))

note("")
env.cr.rollback()
note("rolled back -- session, orders and stock moves discarded.")
if failures:
    note("%d CHECK(S) FAILED" % len(failures))
    sys.exit(1)
note("POS explosion confirmed.")
