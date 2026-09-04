# -*- coding: utf-8 -*-
"""STEP 5 -- bilingual POS names and English sales descriptions.

    YLAK_DIR=... odoo-bin shell -c ... -d ... --no-http < load_50_english.py

Turns every till button from "GỎI GÀ HOA CHUỐI" into
"GỎI GÀ HOA CHUỐI / Banana flower salad with chicken" and fills
`description_sale` with the English line off the owner's menu deck. English in
the NAME rather than in a translation is deliberate: every product name on
this database lives in the `en_US` jsonb key and all nine users are `en_US`,
so an `en_US` translation would replace the Vietnamese for the kitchen and a
`vi_VN` one would be seen by nobody. The name is the only field POS renders on
the button and on the receipt.

Runs LAST, after load_15_prune.py: load_10_catalog.py writes `name` from
menu_data.json on every dish it owns, so it would strip the English half back
off. Re-running this puts it back.

Idempotent. A product is found under either its bare Vietnamese name or the
bilingual name a previous run gave it, and the English half is recomputed
rather than appended to.

Scope is deliberately narrow: only products that are `available_in_pos`, plus
the courses reachable through a POS combo. Matching by name across the whole
catalogue would collide with the kitchen ingredients, several of which share a
dish's name exactly ("SỮA CHUA" is both a buffet ingredient and a set-menu
course).
"""
import json
import os
import sys

sys.path.insert(0, os.environ["YLAK_DIR"])
from english_names import ENGLISH  # noqa: E402
from ylak_common import note  # noqa: E402

SEP = " / "
BACKUP = os.path.join(os.environ["YLAK_DIR"], "english_backup.json")

P = env["product.template"]

# ---------------------------------------------------------------------------
# 1. The set of products this script is allowed to touch
# ---------------------------------------------------------------------------
on_till = P.search([("available_in_pos", "=", True)])
combo_courses = P.browse([
    item.product_id.product_tmpl_id.id
    for tmpl in on_till
    for combo in tmpl.combo_ids
    for item in combo.combo_item_ids
])
targets = on_till | combo_courses
note("candidate products: %d on the till, %d more reachable only through a "
     "combo" % (len(on_till), len(combo_courses - on_till)))

by_name, by_prefix = {}, {}
for tmpl in targets:
    by_name.setdefault(tmpl.name, []).append(tmpl)
    head, sep, _tail = tmpl.name.partition(SEP)
    if sep:
        by_prefix.setdefault(head, []).append(tmpl)

# ---------------------------------------------------------------------------
# 2. Back up what we are about to overwrite, before overwriting it
# ---------------------------------------------------------------------------
if not os.path.exists(BACKUP):
    with open(BACKUP, "w", encoding="utf-8") as fh:
        json.dump([{"id": t.id, "name": t.name,
                    "description_sale": t.description_sale or ""}
                   for t in targets.sorted("id")], fh,
                  ensure_ascii=False, indent=1)
    note("backup of %d names/descriptions written to %s" % (len(targets), BACKUP))
else:
    note("backup already present at %s -- kept (it is the pre-English state)"
         % BACKUP)

# The backup is not just an undo file: it is the record of what the OWNER had
# written in description_sale before any English existed, and that is what has
# to be preserved above the English line. Deriving it from the current value
# instead only works while the English text never changes -- edit a wording in
# english_names.py and the old paragraph is no longer recognisable as ours, so
# it survives as "owner text" and the new one stacks under it.
with open(BACKUP, encoding="utf-8") as fh:
    ORIGINAL = {row["id"]: row.get("description_sale") or ""
                for row in json.load(fh)}

# ---------------------------------------------------------------------------
# 3. Apply
# ---------------------------------------------------------------------------
renamed = described = unchanged = 0
missing, ambiguous = [], []

for vn, en, desc, source in ENGLISH:
    bilingual = vn + SEP + en if en else vn
    # Either spelling identifies the same product: the bare Vietnamese name on
    # a first run, the bilingual one on every run after it.
    # Three spellings identify the same product: the bare Vietnamese name on a
    # first run, the bilingual name on every run after it, and -- when the
    # English half in this table has since been edited -- the bilingual name
    # built from the PREVIOUS English. The prefix fallback catches that last
    # case; without it, editing an entry orphans its product and it silently
    # keeps the old English forever.
    found = by_name.get(bilingual) or by_name.get(vn) or by_prefix.get(vn) or []
    if not found:
        missing.append(vn)
        continue
    if len(found) > 1:
        # Two live products under one name: on prod this is the import's
        # unpriced copy (the one a set menu serves) sitting beside the priced
        # copy the owner keyed by hand onto the till. Merging them changes
        # which product a combo deducts, so that stays the owner's call --
        # but both are the same dish, so both get the same English and the
        # pair is reported below.
        ambiguous.append((vn, found))

    for tmpl in found:
        vals = {}
        if tmpl.name != bilingual:
            vals["name"] = bilingual

        # Whatever the owner typed here is theirs -- the twelve combos carry
        # "Tối thiểu 2 khách." Keep it as the first line and put the English
        # under it. Recomputed, not appended: re-running must not stack copies.
        current = tmpl.description_sale or ""
        if tmpl.id in ORIGINAL:
            keep = ORIGINAL[tmpl.id].rstrip()
        elif current.endswith(desc):
            # Not in the backup, so created after the first English run.
            keep = current[:-len(desc)].rstrip()
        else:
            keep = current.rstrip()
        want_desc = (keep + "\n" + desc) if keep else desc
        if current != want_desc:
            vals["description_sale"] = want_desc

        if not vals:
            unchanged += 1
            continue
        tmpl.write(vals)
        renamed += "name" in vals
        described += "description_sale" in vals

note("renamed          : %d" % renamed)
note("descriptions set : %d" % described)
note("already correct  : %d" % unchanged)

if missing:
    note("!! %d table entr(y/ies) matched no POS product -- renamed in the UI "
         "since the table was written?" % len(missing))
    for vn in missing:
        note("     %s" % vn)

if ambiguous:
    note("!! %d name(s) held by more than one live product -- all copies were "
         "given the same English, but the duplicate itself needs resolving:"
         % len(ambiguous))
    for vn, recs in ambiguous:
        note("     %s" % vn)
        for r in recs:
            note("       id %-5s price %10s  in POS %-5s  %s"
                 % (r.id, "{:,.0f}".format(r.list_price), r.available_in_pos,
                    r.get_external_id().get(r.id) or "(no external id)"))

# ---------------------------------------------------------------------------
# 4. Anything on the till we have no English for
# ---------------------------------------------------------------------------
known = set()
for vn, en, _d, _s in ENGLISH:
    known.add(vn)
    if en:
        known.add(vn + SEP + en)
uncovered = sorted(t.name for t in targets if t.name not in known)
if uncovered:
    note("!! %d POS product(s) carry no English -- add them to english_names.py:"
         % len(uncovered))
    for name in uncovered:
        note("     %s" % name)
else:
    note("every POS product carries English.")

env.cr.commit()
note("committed.")
