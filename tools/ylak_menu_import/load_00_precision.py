# -*- coding: utf-8 -*-
"""STEP 0 -- precision and security groups. Runs in its OWN shell process.

    YLAK_DIR=... odoo-bin shell -c ... -d ... --no-http < load_00_precision.py

Why this is a separate script rather than the first section of the loader:

`decimal.precision` is read through a registry cache that each Odoo process
holds. Bumping the value and then writing BoM lines in the SAME process uses
the stale digit count, and quantities like 0.075 are silently stored as 0.08.
The original loader printed "RESTART REQUIRED" and then carried straight on to
load BoMs, so the warning could not actually protect anything.

Running the bump in its own invocation removes the trap structurally: the next
script is a fresh process that reads the value at startup. The columns
themselves are unconstrained `numeric`, so no schema change is involved.

Exits non-zero if it changed anything, so run.sh stops and the HTTP server can
be restarted before the catalog load.
"""
import os
import sys

sys.path.insert(0, os.environ["YLAK_DIR"])
from ylak_common import note, product_unit_digits  # noqa: E402

REQUIRED_DIGITS = 3
changed = False

prec, digits = product_unit_digits(env)
note("decimal.precision %r: %d digits" % (prec.name, digits))
if digits < REQUIRED_DIGITS:
    prec.digits = REQUIRED_DIGITS
    changed = True
    note("  raised to %d -- recipes carry quantities as small as 0.075"
         % REQUIRED_DIGITS)
else:
    note("  already sufficient")

# New units of measure and stock locations are invisible in the UI unless
# these groups are on, and multi-location silently pins every quant view to
# the warehouse's main stock location.
users = env.ref("base.group_user")
for xmlid, why in [
    ("uom.group_uom", "units of measure"),
    ("stock.group_stock_multi_locations", "per-store stock locations"),
]:
    grp = env.ref(xmlid, raise_if_not_found=False)
    if not grp:
        note("!! %s not found -- is the module installed?" % xmlid)
        continue
    if grp in users.implied_ids:
        note("%-38s already enabled" % why)
    else:
        users.write({"implied_ids": [(4, grp.id)]})
        changed = True
        note("%-38s ENABLED (%s)" % (why, xmlid))

env.cr.commit()
note("committed.")

if changed:
    note("")
    note("=" * 68)
    note("RESTART ODOO before running load_10_catalog.py.")
    note("Other worker processes still hold the old cached values.")
    note("=" * 68)
    sys.exit(2)

note("nothing changed; safe to continue without a restart.")
