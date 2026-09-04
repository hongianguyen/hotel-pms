# -*- coding: utf-8 -*-
"""Helpers shared by every Y Lak loader script.

Imported from inside `odoo shell`, which reads the script from stdin, so
`__file__` is undefined and relative imports do not work. Each loader begins:

    import os, sys
    sys.path.insert(0, os.environ["YLAK_DIR"])
    from ylak_common import note, slug, xmlid, get_or_create

with YLAK_DIR set by run.sh.
"""
import json
import os
import re
import unicodedata

# Module name every record this toolchain creates is filed under. Not a real
# Odoo module -- a namespace for ir.model.data rows, the way Odoo's own
# `__export__` and `__import__` work.
MODULE = "__ylak__"

_LOG = []


def note(msg):
    _LOG.append(msg)
    print(msg)


def log_lines():
    return list(_LOG)


def norm(s):
    """Accent-stripped, punctuation-free comparison key."""
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def slug(s):
    """Stable identifier fragment derived from a SOURCE name.

    Derived from the spreadsheet name, never from the record's current name in
    Odoo: the whole point is that the link survives the owner renaming a dish
    in the UI.

    Unlike norm(), this keeps parenthesised text. norm() drops it so that
    aliases can match loosely, but the stock counts rely on exactly that text
    to tell items apart -- "Máy sưởi" from "Máy sưởi (máy khử khuẩn)", the
    dorm mattresses from the kpan ones. Dropping it here silently gave four
    pairs of distinct products the same external id, and the second of each
    pair overwrote the first.
    """
    t = unicodedata.normalize("NFD", str(s or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
    out = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return out or "unnamed"


def xmlid(prefix, source_name):
    """Full external id, e.g. '__ylak__.dish_goi_ga_hoa_chuoi'."""
    return "%s.%s_%s" % (MODULE, prefix, slug(source_name))


def load_json(env_var, default=None):
    path = os.environ.get(env_var, default)
    if not path:
        # No silent fallback: the old loader defaulted to a fixed /tmp path and
        # would happily load a previous run's stale data.
        raise RuntimeError(
            "%s is not set. run.sh must export it; refusing to guess a path."
            % env_var
        )
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# ir.model.data plumbing
# ---------------------------------------------------------------------------

def ref(env, prefix, source_name):
    """Resolve a record by external id, or None."""
    return env.ref(xmlid(prefix, source_name), raise_if_not_found=False)


def stamp(env, record, prefix, source_name):
    """Give `record` an external id, idempotently.

    Returns True when a new ir.model.data row was written.
    """
    full = xmlid(prefix, source_name)
    module, name = full.split(".", 1)
    imd = env["ir.model.data"]
    existing = imd.search([
        ("module", "=", module),
        ("name", "=", name),
    ], limit=1)
    if existing:
        if existing.res_id != record.id or existing.model != record._name:
            # The slug now points somewhere else -- almost always two source
            # rows colliding on one slug. Refuse rather than silently repoint.
            raise RuntimeError(
                "xmlid %s already points at %s(%s); refusing to repoint to "
                "%s(%s)" % (full, existing.model, existing.res_id,
                            record._name, record.id))
        return False
    imd.create({
        "module": module,
        "name": name,
        "model": record._name,
        "res_id": record.id,
        # noupdate: these are data rows the owner edits in the UI; a module
        # upgrade must never revert them.
        "noupdate": True,
    })
    return True


def get_or_create(env, model, prefix, source_name, vals,
                  search_domain=None, create_only=False):
    """Find by external id, then by name, else create. Always stamped.

    The name fallback exists only to adopt records created before this
    toolchain had external ids; once stamped, renames are safe.
    """
    rec = ref(env, prefix, source_name)
    if not rec:
        domain = search_domain or [("name", "=", source_name)]
        # active_test off: an archived record still owns the name, and creating
        # a second one beside it is exactly the duplicate this function exists
        # to prevent.
        rec = env[model].with_context(active_test=False).search(domain, limit=1)
    if rec and "active" in rec._fields and not rec.active:
        # Reachable by external id but archived -- load_15_prune.py retired it
        # on an earlier run. The extract asks for it again, so it is wanted;
        # nothing else would ever bring it back, because the diff below only
        # writes fields present in `vals` and `active` never is.
        rec.active = True
    if rec and create_only:
        # Nothing to sync on an existing record, and some fields are simply
        # not writable once in use: uom.uom.relative_factor is refused as soon
        # as any product with that unit has moved.
        pass
    elif rec:
        # Write only what actually differs. Odoo refuses some writes outright
        # once a record is in use -- uom.uom.relative_factor cannot be touched
        # after any product with that unit has moved -- and re-sending the
        # identical value is enough to trigger the refusal.
        changed = {}
        for field, want in (vals or {}).items():
            if isinstance(want, (list, tuple)):
                changed[field] = want          # x2many commands: cannot diff
                continue
            have = rec[field]
            if hasattr(have, "id"):
                have = have.id
            if have != want:
                changed[field] = want
        if changed:
            rec.write(changed)
    else:
        rec = env[model].create(dict(vals, name=vals.get("name", source_name)))
    stamp(env, rec, prefix, source_name)
    return rec


# ---------------------------------------------------------------------------
# Precision guard
# ---------------------------------------------------------------------------

PRECISION_NAMES = ["Product Unit", "Product Unit of Measure"]


def product_unit_digits(env):
    prec = env["decimal.precision"].search([("name", "in", PRECISION_NAMES)],
                                           limit=1)
    if not prec:
        raise RuntimeError(
            "No product-unit decimal.precision record found. Present: %s"
            % env["decimal.precision"].search([]).mapped("name"))
    return prec, prec.digits


def require_precision(env, minimum=3):
    """Abort unless quantities like 0.075 will survive a write.

    Called at the top of every loader that writes a quantity. The bump itself
    lives in load_00_precision.py and runs in its OWN shell process: the value
    is cached per-process, so a bump and a BoM write in one process would use
    the stale digit count.
    """
    prec, digits = product_unit_digits(env)
    if digits < minimum:
        raise RuntimeError(
            "decimal.precision %r is %d digits, need >= %d. Run "
            "load_00_precision.py, restart Odoo, then re-run this script."
            % (prec.name, digits, minimum))
    return digits
