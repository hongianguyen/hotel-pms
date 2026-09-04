# -*- coding: utf-8 -*-
"""Build menu_data.json from the newer 'cost of places rvd' workbook.

    python3 extract_menu.py

Offline: reads sources/cost_of_places_rvd.md plus deck_prices.py, writes
menu_data.json, and touches nothing in Odoo.

Supersedes extract.py, which parsed the older COST.xlsx and found 73 dishes.
Sheet 1 of the new workbook is the richest single source in the whole folder:
one uniform table carrying the dish list, the recipe quantities AND the
ingredient unit costs together, for ~110 dishes including drinks.

    | \\[merged\\] CHẢ GIÒ CHAY | ...            <- dish header
    | Đậu khuôn | miếng |  3,240 | 1.00 | 3,240 |  <- ingredient|unit|cost|qty|line
    | Tỷ lệ gia vị 10%+ 20% hao hụt | | 30% | 1 | 1,620 |

The spice row is NOT a recipe line and never becomes a BoM line. The owner
directed 10% (spices only; the sheet's other 20% is waste, an operational
loss), applied to each INGREDIENT's cost -- decided 30 Aug 2026 after we found
that Odoo computes POS margin by exploding the BoM and summing component
costs, so an uplift written to the dish itself would never appear in any
margin figure Odoo shows.

Consequence worth knowing: an ingredient's standard_price is therefore its
buy price + 10%, not the raw supplier price. Nothing today depends on the
distinction -- `purchase` is not installed -- but purchase price variance
would read 10% high if it ever is.
"""
import json
import os
import re
import sys
from collections import Counter, OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ylak_common import norm  # noqa: E402
from extract import ALIASES  # noqa: E402  -- 45 hand-checked name mappings
from mapping import RVD_ALIASES, AMBIGUOUS  # noqa: E402
from deck_prices import DECK_PRICES  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources", "cost_of_places_rvd.md")
OUT = os.path.join(HERE, "menu_data.json")

# Owner's directive, 30 Aug 2026.
SPICE_UPLIFT = 0.10

# Sheet 1 is the primary source: full recipe costing for every dish including
# drinks, in one uniform table. Sheet 0 is the older a-la-carte costing block
# and is read only to pick up dishes sheet 1 does not carry -- KHAI VỊ CHAY HỒ
# LAK is one, and the 255,000 vegetarian set needs it as a course. Its rows
# have an extra column but the ingredient/unit/price/qty positions match.
RECIPE_SHEET = (21739, 60045)
SUPPLEMENT_SHEET = (0, 21739)

SPICE_ROW = re.compile(r"gia vi|hao hut", re.I)
SKIP_ROW = re.compile(r"^(tong|t\u1ed4ng|cost|ghi chu|stt)\b", re.I)
# Section banners, not dishes.
# Banners, not dishes. Prefix-matched: sheet 0 interleaves section headers
# ("MENU CHAY", "TẤT CẢ CÁC MÓN ALACART DÀNH CHO 2 PAX") and stray price cells
# ("95,000") with the dish headers, and an anchored exact match let all of
# them through as dishes.
NOT_A_DISH = re.compile(
    r"^(menu\b|thuc don\b|tat ca\b|canh$|mon \b|set \b|cost\b|"
    r"khach tham quan\b|buffet\b|[\d][\d ,.]*$)", re.I)


def clean(cell):
    return re.sub(r"\\?\[merged\\?\]", "", cell).replace("\\", "").strip()


def number(raw):
    raw = clean(raw).replace(",", "").replace("%", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def parse_recipes(span=RECIPE_SHEET, dishes=None, costs=None):
    text = open(SRC, encoding="utf-8").read()[span[0]:span[1]]
    dishes = OrderedDict() if dishes is None else dishes
    costs = {} if costs is None else costs
    current = None

    for lineno, line in enumerate(text.split("\n"), 1):
        if not line.startswith("|") or ":-:" in line:
            continue
        raw = [c.strip() for c in line.strip().strip("|").split("|")]
        vals = [clean(c) for c in raw]

        merged = {clean(c) for c in raw if "merged" in c and clean(c)}
        if len(merged) == 1:
            head = merged.pop()
            if NOT_A_DISH.match(norm(head)) or not head:
                current = None
                continue
            current = head
            dishes.setdefault(current, {
                "name": current, "components": [], "row": lineno,
            })
            continue

        if current is None or not vals or not vals[0]:
            continue
        if SPICE_ROW.search(vals[0]) or SKIP_ROW.match(norm(vals[0])):
            continue
        if len(vals) < 4:
            continue

        ing, unit = vals[0], vals[1]
        unit_cost, qty = number(vals[2]), number(vals[3])
        if qty is None or not unit:
            continue

        dishes[current]["components"].append({
            "ingredient": ing, "unit": unit, "qty": qty, "row": lineno,
        })
        if unit_cost:
            # Most recent / highest price seen wins, matching extract.py's
            # pick_cost(): the sheet accumulates buys over time.
            key = (ing, unit)
            costs[key] = max(costs.get(key, 0.0), unit_cost)

    return dishes, costs


def build_price_index():
    idx = {}
    for vn, en, price, section in DECK_PRICES:
        idx[norm(vn)] = (vn, en, price, section)
    return idx


def match_price(dish_name, idx):
    key = norm(dish_name)
    if key in idx:
        return idx[key]
    for table in (RVD_ALIASES, ALIASES):
        alias = table.get(key)
        if alias and norm(alias) in idx:
            return idx[norm(alias)]
    for cand, val in idx.items():
        if cand and (cand.startswith(key) or key.startswith(cand)):
            if abs(len(cand) - len(key)) <= 10:
                return val
    return None


def main():
    dishes, costs = parse_recipes()
    primary = set(dishes)
    # Supplement, never override: sheet 1's recipe wins wherever both have one.
    dishes, costs = parse_recipes(SUPPLEMENT_SHEET, dishes, costs)
    supplemented = [n for n in dishes if n not in primary]
    idx = build_price_index()

    ingredients = {}
    for (name, unit), cost in costs.items():
        prev = ingredients.get(name)
        if prev is None or cost > prev["raw_cost"]:
            ingredients[name] = {
                "name": name,
                "uom": unit,
                "raw_cost": cost,
                # The 10% lands here, per the owner.
                "standard_cost": round(cost * (1 + SPICE_UPLIFT), 2),
            }
    # Ingredients used with no price anywhere still need a product.
    for d in dishes.values():
        for c in d["components"]:
            ingredients.setdefault(c["ingredient"], {
                "name": c["ingredient"], "uom": c["unit"],
                "raw_cost": 0.0, "standard_cost": 0.0,
            })

    priced = unpriced = 0
    out_dishes = []
    for name, d in dishes.items():
        hit = match_price(name, idx)
        cost = sum(
            ingredients[c["ingredient"]]["standard_cost"] * c["qty"]
            for c in d["components"])
        row = {
            "name": name,
            "name_vn": name,
            "portion_unit": "phần",
            "components": d["components"],
            "standard_cost": round(cost, 2),
            "sale_price": hit[2] if hit else None,
            "name_en": hit[1] if hit else None,
            "menu_section": hit[3] if hit else "Chưa phân loại",
            "row": d["row"],
        }
        if hit and hit[2]:
            priced += 1
            row["cost_pct"] = round(100.0 * cost / hit[2], 1) if hit[2] else None
        else:
            unpriced += 1
        out_dishes.append(row)

    no_cost = [i for i in ingredients.values() if not i["standard_cost"]]

    print("=" * 70)
    print("dishes found      : %d  (%d priced, %d without a deck price)"
          % (len(out_dishes), priced, unpriced))
    print("ingredients       : %d  (%d with no cost)"
          % (len(ingredients), len(no_cost)))
    print("spice uplift      : %.0f%% applied to each INGREDIENT cost"
          % (SPICE_UPLIFT * 100))
    if supplemented:
        print("from sheet 0 only : %d  (%s)"
              % (len(supplemented), ", ".join(supplemented[:6])))
    print()
    high = sorted((d for d in out_dishes if d.get("cost_pct")),
                  key=lambda d: -d["cost_pct"])[:8]
    print("highest food cost %:")
    for d in high:
        print("  %5.1f%%  %-44s cost %9s / price %9s"
              % (d["cost_pct"], d["name"][:44],
                 "{:,.0f}".format(d["standard_cost"]),
                 "{:,.0f}".format(d["sale_price"])))
    print()
    if unpriced:
        flagged = [d for d in out_dishes
                   if not d["sale_price"] and norm(d["name"]) in AMBIGUOUS]
        plain = [d for d in out_dishes
                 if not d["sale_price"] and norm(d["name"]) not in AMBIGUOUS]
        if flagged:
            print("NEEDS THE OWNER'S DECISION -- a plausible deck match exists")
            print("but names a different dish, so no price has been guessed:")
            for d in flagged:
                print("  %s" % d["name"])
                print("      %s" % AMBIGUOUS[norm(d["name"])])
            print()
        print("no deck price at all (%d, will not be sellable in POS):"
              % len(plain))
        for d in plain:
            print("    %s" % d["name"])
    print()
    if no_cost:
        print("no cost (%d) -- these make their dish's food cost understated:"
              % len(no_cost))
        print("    " + ", ".join(sorted(i["name"] for i in no_cost)[:24]))
    print("=" * 70)

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({
            "dishes": out_dishes,
            "ingredients": ingredients,
            "spice_uplift": SPICE_UPLIFT,
            "prep_items": [],
            "non_menu_dishes": [],
            "nested": [],
        }, fh, ensure_ascii=False, indent=1)
    print("wrote %s" % OUT)


if __name__ == "__main__":
    main()
