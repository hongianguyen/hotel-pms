# -*- coding: utf-8 -*-
"""Generate reorder_levels.csv for the owner to fill in. Offline.

    python3 make_reorder_csv.py

"Follow it and fill it up" needs minimum levels, and no workbook contains
them: every sheet is a single count dated 24/08/2026, with no min/max, no
reorder quantity and no supplier lead time. Nothing here guesses one.

What this does is remove the typing. Every stocked item is listed with its
store, unit and current count, `min` and `max` left empty. The owner fills in
only the lines they care about -- the ~80 kitchen consumables that actually
run out, not the 168 dinner plates -- and load_40_orderpoints.py turns the
filled rows into stock.warehouse.orderpoint records. Blank rows get no
orderpoint, so a half-filled file is a valid file.

Ordered by store, then by descending count, so the fast-moving goods that need
a minimum are at the top of each section rather than scattered alphabetically.

**Regenerating never loses a filled-in level.** Any existing min/max is read
back first, keyed on (store, product), and carried into the new file. Without
that, a recount three months from now would silently wipe every number the
owner typed -- and the file is committed, so a plain `git checkout` would too.
Rows whose product has since left the inventory are kept at the end rather than
dropped, so a rename never eats a level in silence.
"""
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
INV = json.load(open(os.path.join(HERE, "inventory_data.json"), encoding="utf-8"))
OUT = os.path.join(HERE, "reorder_levels.csv")

counts = {}
for row in INV["quants"]:
    counts[(row["store"], row["name"])] = row["qty"]

uoms = {p["name"]: p.get("uom") or "" for p in INV["products"]}
equip = {p["name"]: p.get("is_equipment") for p in INV["products"]}
stores = {p["name"]: p["store"] for p in INV["products"]}

# Carry forward whatever is already filled in.
previous = {}
if os.path.exists(OUT):
    with open(OUT, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            lo, hi = (row.get("min") or "").strip(), (row.get("max") or "").strip()
            if lo or hi:
                previous[(row["store"], row["product"])] = (lo, hi)

rows = []
for item in INV["products"]:
    store = stores[item["name"]]
    rows.append({
        "store": store,
        "store_name": INV["stores"][store],
        "product": item["name"],
        "uom": uoms.get(item["name"], ""),
        # Equipment is stock-tracked but nobody reorders a ladle to a minimum;
        # marked so the owner can skip those sections wholesale.
        "kind": "equipment" if equip.get(item["name"]) else "consumable",
        "counted_24_08_2026": counts.get((store, item["name"]), 0),
        "min": previous.get((store, item["name"]), ("", ""))[0],
        "max": previous.get((store, item["name"]), ("", ""))[1],
    })
    previous.pop((store, item["name"]), None)

kept = len([r for r in rows if r["min"] or r["max"]])
rows.sort(key=lambda r: (r["store_name"], r["kind"],
                         -float(r["counted_24_08_2026"] or 0), r["product"]))

# A level the owner set for something no longer in the inventory. Almost always
# a rename upstream. Kept, at the end, flagged -- deleting it silently is how a
# rename turns into lost work.
for (store, name), (lo, hi) in sorted(previous.items()):
    rows.append({
        "store": store, "store_name": INV["stores"].get(store, store),
        "product": name, "uom": "", "kind": "NOT IN CURRENT INVENTORY",
        "counted_24_08_2026": "", "min": lo, "max": hi,
    })

with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
    # utf-8-sig: Excel on Windows shows Vietnamese as mojibake without the BOM,
    # and this file exists to be opened in Excel.
    writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)

by_store = {}
for r in rows:
    by_store.setdefault(r["store_name"], [0, 0])
    by_store[r["store_name"]][r["kind"] == "equipment"] += 1

print("wrote %s" % OUT)
if kept or previous:
    print("carried forward %d filled-in level(s); %d no longer in the "
          "inventory, kept at the end of the file" % (kept, len(previous)))
print("%-26s %10s %10s" % ("store", "consumable", "equipment"))
for name, (cons, eq) in sorted(by_store.items()):
    print("%-26s %10d %10d" % (name, cons, eq))
print("%-26s %10d %10d" % ("TOTAL",
                           sum(v[0] for v in by_store.values()),
                           sum(v[1] for v in by_store.values())))
print("\nmin/max are empty on purpose. Fill in only the lines that matter;")
print("blank rows get no orderpoint. Re-running preserves what is filled in.")
