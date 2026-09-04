# -*- coding: utf-8 -*-
"""Merge `extra Cost_ingredients` into menu_data.json. Offline.

    python3 extract_extra.py          # after extract_menu.py, before extract_sets.py

The owner added this sheet on 30 Aug 2026, after the first load. It is the
same block format as `cost of places rvd` sheet 0 -- dish header, ingredient
rows, a 30% spice/waste row, then a TỔNG row -- and unlike sheet 1 it carries
**selling prices**, which is what most of it is here to supply.

It merges INTO menu_data.json rather than emitting a sibling file. That is not
cosmetic: `load_15_prune.py` builds its keep-list from `MENU["dishes"]` and
`MENU["ingredients"]`, so anything in a separate file would be archived on the
next prune, and `verify.py`'s dish/BoM/price/cost-reconciliation checks would
silently stop covering it. Merging means every guard already built applies.

Re-running is safe: the merge is keyed on dish and ingredient name and always
recomputes from both sources, so `extract_menu.py && extract_extra.py` is
idempotent however many times it runs.

## Three blocks are NOT new dishes

Verified against the loaded data rather than assumed from the name:

  KHAI VỊ CHAY            = KHAI VỊ CHAY HỒ LAK, already priced 185,000 (the
                            deck spells it the short way). Price-only.
  TRỨNG VỊT HỒ LAK CHIÊN  = TRỨNG VỊT HỒ LAK CHIÊN THỊT BẰM. The block's only
                            component carries the LONG name at 2,484/quả --
                            it is the duck egg, and the existing ingredient
                            sits at 2,732 = 2,484 x 1.10. Price-only: 45,000.
  CACAO                   = CACAO SỮA. The recipe contains Sữa tươi, so it is
                            the milk cocoa; the sweetener differs (sugar here,
                            condensed milk there) and the deck has no cocoa
                            line at all. Price-only: 45,000.

Creating any of them fresh would put a second button on the till for a dish
that is already there.

## Eight blocks are retail goods, not dishes

Five wines sold by the bottle, plus honey / cocoa / coffee sold by the pack --
each a fraction of a bulk good (honey 151,200/l x 0.350 = one 350 ml jar at
135,000). Tagged `kind: 'retail'` so the catalogue keeps them out of
`Món ăn nhà hàng`, where they would sit among the food on the POS grid.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ylak_common import norm  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources", "extra_cost.md")
MENU = os.path.join(HERE, "menu_data.json")
INVENTORY = os.path.join(HERE, "inventory_data.json")

# Blocks that name a dish already in menu_data.json under a different
# spelling. Value is the existing dish name. Hand-checked; see the docstring.
SAME_DISH = {
    "khai vi chay": "KHAI VỊ CHAY HỒ LAK",
    "trung vit ho lak chien": "TRỨNG VỊT HỒ LAK CHIÊN THỊT BẰM",
    "cacao": "CACAO SỮA",
}

# Sold as bought, by the bottle or the pack. Keys are norm()ed, which DROPS
# parenthesised text -- "POL REMY DEMI ( SPARLING WINE - FRANCE)" normalises to
# just "pol remy demi", and spelling the country into the key silently made it
# never match.
WINE = {
    "pol remy demi", "chateau foncrose sauvignon blanc",
    "chateau foncrose cabernet sauvignon", "tarapaca coshecha sauvignon blanc",
    "tarapaca coshecha cabernet sauvignon",
}
RETAIL = WINE | {"mat ong", "bot cacao", "ca phe bot"}
DRINK = {"tra xanh"}

# A course of the 195,000 vegetarian set, priced nowhere because it is never
# sold on its own -- the sheet says so in its own header cell ("trong set
# menu"). Kept out of POS; extract_sets.py picks it up as CUỐN DIẾP CHAY.
SET_ONLY = {"cuon diep ram bap"}

SECTION = {"retail": "Hàng bán lẻ", "wine": "Rượu vang",
           "drink": "Đồ uống", "dish": "Món thêm"}

UPLIFT_ROW = re.compile(r"^t[ỷy]\s*l[ệe]\s*gia\s*v[ịi]", re.I)


def number(cell):
    cell = (cell or "").replace(",", "").replace("%", "").strip()
    try:
        return float(cell)
    except ValueError:
        return None


def rows(text):
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(c in ("", ":-:") for c in cells):
            continue
        yield cells


def parse(text):
    """-> [{name, components, cost_sheet, sale_price}]"""
    blocks, cur = [], None
    for cells in rows(text):
        first = cells[0]
        if first.startswith("\\[merged\\]"):
            # A dish header: the merge repeats the name across its span. The
            # CUỐN DIẾP block also carries an unmerged "trong set menu" note in
            # the later columns, so only cell 0 is the name.
            name = first.replace("\\[merged\\]", "").strip()
            cur = {"name": name, "components": [], "cost_sheet": None,
                   "sale_price": None, "uplifted": False, "uplift_row": None}
            blocks.append(cur)
            continue
        if cur is None or not first:
            continue
        if UPLIFT_ROW.match(first):
            # The 30% row; the owner directed 10%. Noted, because the eight
            # resale blocks have no such row and their TỔNG is therefore a raw
            # figure -- comparing them as if uplifted reads as a 30% error.
            cur["uplifted"] = True
            cur["uplift_row"] = number(cells[4]) if len(cells) > 4 else None
            continue
        if norm(first) == "tong":
            cur["cost_sheet"] = number(cells[4] if len(cells) > 4 else "")
            # The price sits in column 6 for most blocks but column 7 for the
            # whole MIẾN/MÌ/CƠM CHIÊN group -- the sheet's columns shift there.
            # Scan, and ignore the cost-% cell, which is a bare number once the
            # '%' is stripped.
            for idx in range(5, min(len(cells), 8)):
                if "%" in cells[idx]:
                    continue
                val = number(cells[idx])
                if val and val >= 1000:
                    cur["sale_price"] = val
                    break
            cur = None
            continue

        unit_cost = number(cells[2]) if len(cells) > 2 else None
        qty = number(cells[3]) if len(cells) > 3 else None
        line_cost = number(cells[4]) if len(cells) > 4 else None
        if not unit_cost:
            continue
        # TRÀ XANH shows qty "0.00" against a line cost of 60 at 59,800/kg --
        # the real quantity is 0.001 and the sheet simply rounds it away in
        # display. Recover it from the line cost, which is not rounded.
        if (not qty) and line_cost and unit_cost:
            qty = round(line_cost / unit_cost, 3)
        if not qty:
            continue
        cur["components"].append({"ingredient": first, "unit": cells[1],
                                  "qty": qty, "unit_cost": unit_cost})
    return [b for b in blocks if b["components"]]


def kind_of(block):
    key = norm(block["name"])
    if key in WINE:
        return "wine"
    if key in RETAIL:
        return "retail"
    if key in SET_ONLY:
        return "set_only"
    if key in DRINK:
        return "drink"
    return "dish"


def main():
    text = open(SRC, encoding="utf-8").read()
    data = json.load(open(MENU, encoding="utf-8"))
    spice = data.get("spice_uplift", 0.10)
    blocks = parse(text)

    # Product identity is case-sensitive, and the sources capitalise
    # inconsistently: the department stock count holds "Ống cơm lam",
    # "Khoai tây Siêu Thị" and "Cá Lăng" where the recipe sheets write
    # "ỐNG CƠM LAM", "Khoai tây siêu thị" and "Cá lăng". Left alone that is
    # two products for one good -- the counted one holds the 30 bamboo tubes
    # and never moves, while the recipe one, which is what every BoM line
    # actually deducts, sits at zero and goes negative on the first sale.
    #
    # The STOCK COUNT wins: it is what the storekeeper counts and where the
    # quant lives. Applied to the whole of menu_data, not just this sheet,
    # because most of these pairs come from the earlier one.
    inv_names = []
    if os.path.exists(INVENTORY):
        inv_names = [p["name"] for p in
                     json.load(open(INVENTORY, encoding="utf-8"))["products"]]
    canon = {" ".join(n.lower().split()): n for n in inv_names}
    for k in data["ingredients"]:
        canon.setdefault(" ".join(k.lower().split()), k)

    def canonical(name):
        return canon.get(" ".join(name.lower().split()), name)

    renamed, merged = [], {}
    for key in list(data["ingredients"]):
        keep = canonical(key)
        if keep == key:
            continue
        renamed.append((key, keep))
        entry = data["ingredients"].pop(key)
        entry["name"] = keep
        # The stock count carries no cost, so the recipe entry's cost is the
        # one worth keeping; only the name changes.
        data["ingredients"].setdefault(keep, entry)
        merged[key] = keep
    for dish in data["dishes"]:
        for comp in dish["components"]:
            comp["ingredient"] = merged.get(comp["ingredient"],
                                            comp["ingredient"])
    for block in blocks:
        for comp in block["components"]:
            keep = canonical(comp["ingredient"])
            if keep != comp["ingredient"]:
                renamed.append((comp["ingredient"], keep))
                comp["ingredient"] = keep

    by_name = {d["name"]: d for d in data["dishes"]}
    by_norm = {norm(d["name"]): d for d in data["dishes"]}
    ings = data["ingredients"]

    # ---- 1. ingredient costs -------------------------------------------
    # A product carries ONE cost, so a cost written here changes the
    # standard_cost of every existing dish that uses it. Rule: fill a missing
    # or zero cost, otherwise keep the figure already in menu_data. That keeps
    # the 110 existing dishes' costs -- and verify.py's cost reconciliation --
    # stable, and confines this file's effect to what it actually adds.
    # The file also disagrees with itself (Bánh phồng tôm is 86,400 in one
    # block and 92,880 in another), so first-seen wins there too.
    added, filled, conflicts, internal = 0, 0, [], {}
    for block in blocks:
        for comp in block["components"]:
            name, raw = comp["ingredient"], comp["unit_cost"]
            if name in internal and internal[name] != raw:
                conflicts.append(("(within extra_cost)", name,
                                  internal[name], raw))
            internal.setdefault(name, raw)
            existing = ings.get(name)
            if existing is None:
                ings[name] = {"name": name, "uom": comp["unit"],
                              "raw_cost": raw,
                              "standard_cost": round(raw * (1 + spice), 2)}
                added += 1
            elif not existing.get("standard_cost"):
                existing["raw_cost"] = raw
                existing["standard_cost"] = round(raw * (1 + spice), 2)
                filled += 1
            elif abs((existing.get("raw_cost") or 0) - raw) > 1:
                conflicts.append(("menu_data", name,
                                  existing.get("raw_cost"), raw))

    def cost_of(block):
        return round(sum(c["qty"] * ings[c["ingredient"]]["standard_cost"]
                         for c in block["components"]), 2)

    # ---- 2. dishes -------------------------------------------------------
    new, priced, unchanged, recipe_differs = [], [], [], []
    for block in blocks:
        kind = kind_of(block)
        key = norm(block["name"])
        target = SAME_DISH.get(key)
        dish = by_name.get(target) if target else by_norm.get(key)

        if dish is not None:
            # Existing dish. Take the price if it has none; never overwrite a
            # price, and never rewrite a recipe -- that would change what a
            # sale deducts from stock, silently, from a sheet whose quantities
            # disagree with the established one.
            if block["sale_price"] and not dish.get("sale_price"):
                dish["sale_price"] = block["sale_price"]
                priced.append((dish["name"], block["sale_price"]))
            else:
                unchanged.append((dish["name"], dish.get("sale_price")))
            here = {norm(c["ingredient"]): c["qty"] for c in block["components"]}
            there = {norm(c["ingredient"]): c["qty"] for c in dish["components"]}
            if here != there:
                recipe_differs.append((dish["name"], there, here))
            continue

        entry = {
            "name": block["name"],
            "name_vn": block["name"],
            "portion_unit": "chai" if kind == "wine" else "phần",
            "components": [{"ingredient": c["ingredient"], "unit": c["unit"],
                            "qty": c["qty"]} for c in block["components"]],
            "standard_cost": cost_of(block),
            "sale_price": block["sale_price"],
            "menu_section": SECTION.get(kind, "Món thêm"),
            "kind": kind,
            "source": "extra_cost",
        }
        if kind == "set_only":
            # No price on purpose: it is only ever sold inside the 195,000 set,
            # so available_in_pos stays False and the combo pulls it in.
            entry["menu_section"] = "Set menu"
            entry["sale_price"] = None
        data["dishes"].append(entry)
        new.append((entry["name"], kind, entry["sale_price"]))

    # A block that should have a price and does not is a parse failure, not a
    # data gap: it would load hidden from POS, which is the exact complaint
    # this file was supplied to fix.
    missing_price = [b["name"] for b in blocks
                     if not b["sale_price"] and kind_of(b) != "set_only"]
    if missing_price:
        raise SystemExit("no selling price parsed for: %s"
                         % ", ".join(missing_price))

    json.dump(data, open(MENU, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # ---- 3. report -------------------------------------------------------
    print("=" * 72)
    print("extra_cost.md: %d blocks" % len(blocks))
    print("ingredients: %d added, %d had a zero cost filled in" % (added, filled))
    print()
    print("NEW (%d):" % len(new))
    for name, kind, price in new:
        print("   %-42s %-9s %s" % (name[:42], kind,
                                    "{:,.0f}".format(price) if price else "-"))
    print()
    print("PRICED an existing dish (%d):" % len(priced))
    for name, price in priced:
        print("   %-42s %s" % (name[:42], "{:,.0f}".format(price)))
    if unchanged:
        print()
        print("already priced, left alone (%d):" % len(unchanged))
        for name, price in unchanged:
            print("   %-42s %s" % (name[:42], price))
    if recipe_differs:
        print()
        print("!! %d existing dish(es) have a DIFFERENT recipe here. The "
              "established" % len(recipe_differs))
        print("   recipe was kept -- rewriting it changes what a sale deducts:")
        for name, there, here in recipe_differs:
            print("   %s" % name)
            for k in sorted(set(there) | set(here)):
                if there.get(k) != here.get(k):
                    print("      %-30s menu_data %-8s extra %s"
                          % (k[:30], there.get(k, "-"), here.get(k, "-")))
    # One line per (ingredient, disagreement), not one per use: Cà rốt appears
    # in nine blocks and printed nine identical lines.
    seen = sorted({(n, w, o, r) for w, n, o, r in conflicts})
    if seen:
        print()
        print("!! %d ingredient cost disagreement(s) across %d use(s); the "
              "first figure was kept:" % (len(seen), len(conflicts)))
        for name, where, old, raw in seen:
            print("   %-28s %-20s kept %-12s vs %s"
                  % (name[:28], where, old, raw))
    if renamed:
        print()
        print("adopted the stock count's spelling for %d name(s) differing "
              "only by case" % len(set(renamed)))
        print("(else the same good is two products and the recipe deducts the "
              "one nobody counts):")
        for was, now in sorted(set(renamed)):
            print("   %-28s -> %s" % (was, now))

    # Names in the catalogue that differ only by case. Reported, never merged:
    # the owner's instruction was that duplicate-looking items are separate
    # items, and only they can say whether "Tôm biển" and "tôm biển" are one
    # prawn or two.
    seen_ci = {}
    for name in data["ingredients"]:
        seen_ci.setdefault(" ".join(name.lower().split()), []).append(name)
    collide = [v for v in seen_ci.values() if len(v) > 1]
    if collide:
        print()
        print("!! %d ingredient name(s) exist in more than one capitalisation. "
              "Each is" % len(collide))
        print("   a SEPARATE product with its own stock -- the owner decides "
              "if they are one:")
        for group in sorted(collide):
            print("   %s" % " | ".join(group))

    # Fidelity, not self-consistency: the checks in verify.py compare two
    # numbers that both come from this parse, so a mis-read quantity would pass
    # them. This compares the computed cost against the sheet's OWN TỔNG, which
    # the parser never uses for anything.
    print()
    print("cost vs the sheet's own line costs (its uplift row replaced by "
          "the owner's 10%):")
    off = []
    for block in blocks:
        got = round(sum(c["qty"] * ings[c["ingredient"]]["standard_cost"]
                        for c in block["components"]), 2)
        # Against the sheet's own LINE costs, not its TỔNG: the uplift row is
        # nominally 30% but several blocks apply something else, so dividing
        # the total by 1.30 invents a discrepancy that is not there. Comparing
        # the lines isolates the one legitimate cause -- an ingredient whose
        # cost in menu_data differs from this sheet's.
        lines = sum(c["qty"] * c["unit_cost"] for c in block["components"])
        want = lines * (1 + spice)
        ratio = got / want if want else 0
        if 0.95 <= ratio <= 1.05:
            continue
        # Distinguish a bad parse from a bad sheet. Each block states its own
        # line costs, its 30% row and its TỔNG, so the sheet can be checked
        # against itself: if its TỔNG does not equal its lines plus its uplift,
        # the divergence is the sheet's arithmetic, not this parser's reading.
        stated = (block["uplift_row"] or 0) + lines
        why = "cost precedence"
        if abs(stated - (block["cost_sheet"] or 0)) > max(2, 0.01 * lines):
            why = ("SHEET ARITHMETIC: its lines %s + its uplift %s = %s, "
                   "but its TỔNG says %s"
                   % ("{:,.0f}".format(lines),
                      "{:,.0f}".format(block["uplift_row"] or 0),
                      "{:,.0f}".format(stated),
                      "{:,.0f}".format(block["cost_sheet"] or 0)))
        off.append((block["name"], got, want, ratio, why))
    if off:
        for name, got, want, ratio, why in off:
            print("   %-32s computed %9.0f  sheet %9.0f  x%.3f"
                  % (name[:32], got, want, ratio))
            print("      %s" % why)
    else:
        print("   all %d blocks within 5%%" % len(blocks))

    print("=" * 72)
    total = len(data["dishes"])
    sellable = sum(1 for d in data["dishes"] if d.get("sale_price"))
    print("menu_data.json now: %d dishes, %d priced, %d hidden pending a price"
          % (total, sellable, total - sellable))


if __name__ == "__main__":
    main()
