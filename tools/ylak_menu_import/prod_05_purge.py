# -*- coding: utf-8 -*-
"""STEP -1 -- clear the hand-made POS menu so the import can land clean.

    YLAK_DIR=... odoo-bin shell -c ... -d ... --no-http < prod_05_purge.py

Production carried 34 POS products keyed in by hand ("Gỏi gà hoa chuối") that
are the same dishes this toolchain imports in the workbook's caps ("GỎI GÀ HOA
CHUỐI"). Odoo names are case-sensitive, so loading on top gives every dish
twice -- once with a kit BoM that deducts stock, once without. The prune cannot
help: those products carry no `__ylak__` external id, and an unowned product is
not the toolchain's to retire.

The owner asked for them DELETED, not archived. That is safe here and would not
be in general -- the audit behind it: one POS order exists in the whole
database, it is CANCELLED, and there are no stock moves, no quants, no account
move lines, no combo items and no orderpoints against any of these products. No
`hotel_*` table references product at all, so the PMS and folio side cannot be
touched by this.

Rails, because "delete every POS product" is a sentence that ages badly:

  * REFUSES to run once the import owns POS products. After load_10 the entire
    Y Lak menu is `available_in_pos`, so a second run would delete exactly what
    the first run made room for.
  * Never deletes a product owned by an installed module (`Tips` belongs to
    `point_of_sale` and is wired to `pos_config.tip_product_id`).
  * Deletes a blocking POS order only when it is CANCELLED. Anything else, the
    product is archived instead and reported -- history always wins over tidy.
"""
import os
import sys

sys.path.insert(0, os.environ["YLAK_DIR"])
from ylak_common import note  # noqa: E402

imd = env["ir.model.data"]

# ---------------------------------------------------------------------------
# Rail 1 -- refuse to run against an already-imported database
# ---------------------------------------------------------------------------
owned = imd.search_count([("module", "=", "__ylak__"),
                          ("model", "=", "product.template")])
if owned:
    raise SystemExit(
        "REFUSED: %d product(s) already carry a __ylak__ external id.\n"
        "This script clears the PRE-import menu. Running it now would delete\n"
        "the imported catalogue itself." % owned)

# ---------------------------------------------------------------------------
# 1. Close any open POS session -- its cached product list is about to go
# ---------------------------------------------------------------------------
for sess in env["pos.session"].search([("state", "!=", "closed")]):
    if sess.order_ids.filtered(lambda o: o.state != "cancel"):
        raise SystemExit(
            "REFUSED: session %s holds real orders. Close the till properly "
            "first." % sess.name)
    note("closing stale session %s (orders=%d)" % (sess.name, len(sess.order_ids)))
    try:
        sess.action_pos_session_closing_control()
    except Exception as exc:                                   # noqa: BLE001
        note("  closing_control raised: %s" % exc)
    if sess.state != "closed":
        try:
            sess.action_pos_session_close()
        except Exception as exc:                               # noqa: BLE001
            note("  close raised: %s" % exc)
    note("  state now %s" % sess.state)

# ---------------------------------------------------------------------------
# 2. Work out what to remove
# ---------------------------------------------------------------------------
boms = env["mrp.bom"].with_context(active_test=False).search([])
# The components of those BoMs exist only to feed them; with the BoM gone they
# are orphan ingredients. Included deliberately -- "products on POS and BoM".
bom_components = boms.mapped("bom_line_ids.product_id.product_tmpl_id")
pos_products = env["product.template"].with_context(active_test=False).search(
    [("available_in_pos", "=", True)])

targets = pos_products | bom_components


def module_owner(tmpl):
    row = imd.search([("model", "=", "product.template"),
                      ("res_id", "=", tmpl.id)], limit=1)
    return row.module if row else None


protected, candidates = [], env["product.template"]
for tmpl in targets:
    owner = module_owner(tmpl)
    if owner:
        protected.append((tmpl.display_name, owner))
    else:
        candidates |= tmpl

note("=" * 68)
note("BoMs to delete          : %d" % len(boms))
note("POS products            : %d" % len(pos_products))
note("BoM component products  : %d" % len(bom_components))
note("candidates for deletion : %d" % len(candidates))
for name, owner in protected:
    note("  PROTECTED (module %s) %s" % (owner, name))

# ---------------------------------------------------------------------------
# 3. Delete the BoMs first, then the products
# ---------------------------------------------------------------------------
note("-" * 68)
for bom in boms:
    note("delete BoM %s (%s)" % (bom.id, bom.display_name))
boms.unlink()

variants = candidates.mapped("product_variant_ids")

# A cancelled order is the only history allowed to be swept aside.
blocking = env["pos.order.line"].search([("product_id", "in", variants.ids)])
cancelled = blocking.mapped("order_id").filtered(lambda o: o.state == "cancel")
live = blocking.mapped("order_id") - cancelled
if cancelled:
    note("deleting %d cancelled POS order(s): %s"
         % (len(cancelled), ", ".join("%s/%s" % (o.id, o.state) for o in cancelled)))
    cancelled.unlink()
live_products = env["product.template"]
if live:
    live_products = live.mapped("lines.product_id.product_tmpl_id")
    note("%d POS order(s) are NOT cancelled -- their products will be archived,"
         " not deleted" % len(live))

deleted, archived, failed = [], [], []
for tmpl in candidates:
    label = tmpl.display_name
    if tmpl in live_products:
        tmpl.active = False
        archived.append((label, "referenced by a non-cancelled POS order"))
        continue
    try:
        with env.cr.savepoint():
            tmpl.unlink()
        deleted.append(label)
    except Exception as exc:                                   # noqa: BLE001
        reason = str(exc).strip().split("\n")[0][:90]
        try:
            with env.cr.savepoint():
                tmpl.active = False
            archived.append((label, reason))
        except Exception as exc2:                              # noqa: BLE001
            failed.append((label, str(exc2)[:90]))

note("=" * 68)
note("deleted  : %d" % len(deleted))
for name in deleted[:40]:
    note("    %s" % name)
if len(deleted) > 40:
    note("    ... and %d more" % (len(deleted) - 40))
note("archived : %d  (could not be deleted -- history kept)" % len(archived))
for name, why in archived:
    note("    %-38s %s" % (name[:38], why))
if failed:
    note("FAILED   : %d" % len(failed))
    for name, why in failed:
        note("    %-38s %s" % (name[:38], why))

note("=" * 68)
note("remaining POS products: %d"
     % env["product.template"].search_count([("available_in_pos", "=", True)]))
note("remaining BoMs        : %d" % env["mrp.bom"].search_count([]))

env.cr.commit()
note("committed.")
