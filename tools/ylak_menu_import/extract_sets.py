# -*- coding: utf-8 -*-
"""Parse the SET MENU and BUFFET sheets into sets_data.json.

    python3 extract_sets.py

Offline: reads sources/cost_of_places_rvd.md and menu_data.json, writes
sets_data.json, and touches nothing in Odoo.

Two quite different things live here because they share the workbook and the
same dish-name matcher:

  * SET MENU (sheet 2) -- six price tiers, each offering a SET 1 and a SET 2,
    laid out SIDE BY SIDE: SET 1 occupies the left columns and SET 2 the right
    ones, so the sheet is read as two independent column bands over the same
    rows. Every course is a dish that already exists a la carte, so a set is
    extracted as a LIST OF DISH NAMES, never as ingredients.

  * COST BUFFET (sheet 4) -- 38 ingredient lines costed for 20 pax. Divided by
    20 to give a per-pax recipe.

A course that does not resolve to a known dish is a hard failure. A set with a
missing course would under-deduct stock and mis-split revenue on every sale --
worse than having no set at all.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ylak_common import norm  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources", "cost_of_places_rvd.md")
MENU = os.path.join(HERE, "menu_data.json")
OUT = os.path.join(HERE, "sets_data.json")

BUFFET_PAX = 20

# Sheet offsets in the committed export (see sources/README.md).
SET_SHEET = (60045, 89647)
BUFFET_SHEET = (112413, None)

# Course names in the set sheet do not always match the recipe sheet's
# spelling. These are hand-checked, like the 45 ALIASES in extract.py.
# Courses named in a set for which the workbook carries NO recipe anywhere.
# The set still loads, marked incomplete, and the loader refuses it: a set that
# silently skips a course would under-deduct stock on every sale. The owner
# supplies the recipe, or confirms the course should be dropped.
NO_RECIPE = {
}

COURSE_ALIASES = {
    # The owner uploaded `extra Cost_ingredients` on 30 Aug 2026 immediately
    # after being asked for this recipe, and it contains a CUỐN DIẾP & RAM BẮP
    # block: no selling price, all-vegetarian, and annotated "trong set menu"
    # (= in the set menu) in its own header row. Read as the answer, which
    # completes the 195,000 vegetarian SET 1 -- the only set of the twelve that
    # was being withheld. Flagged to the owner in case it is a different dish.
    "cuon diep chay": "cuon diep ram bap",

    "canh u u nau ga": "canh ga la giang",
    "ca bong kho tieu": "ca bong kho tieu chien gion",
    "lau ga la giang": "lau ga la giang la e",
    "au hu kho nam rom": "nam kho to",
    "rau cai xao": "rau cu xao thap cam",
    "cha ram bap": "cha gio chay",
    "trai cay theo mua": "trai cay theo mua",
    "sua chua": "sua chua",
}

# Rows that are structure, not courses.
NOT_A_COURSE = re.compile(
    r"^(set\s*\d*|cost.*|tong|t\u1ed4ng|.*minimum.*|.*cho 2\s*pax.*|"
    r"cost for two)$", re.I)
# Banners that sit inside a tier block but are not courses. KHÁCH THAM QUAN is
# the visitor entrance fee, priced per head and sold on its own.
BANNER_COURSE = re.compile(r"khach tham quan", re.I)

TIER_RE = re.compile(
    r"SET\s+(LUNCH|DINNER|MENU)\s*([\d.,]+)\s*/?\s*1?\s*PAX", re.I)


def clean(cell):
    return re.sub(r"\\?\[merged\\?\]", "", cell).replace("\\", "").strip()


def rows(text):
    for line in text.split("\n"):
        if not line.startswith("|") or ":-:" in line:
            continue
        raw = [c.strip() for c in line.strip().strip("|").split("|")]
        yield raw, [clean(c) for c in raw]


def merged_value(raw_cells, lo, hi):
    """The merged heading spanning columns [lo, hi), if the band has one."""
    vals = {clean(c) for i, c in enumerate(raw_cells)
            if lo <= i < hi and "merged" in c and clean(c)}
    return vals.pop() if len(vals) == 1 else None


def load_dishes():
    with open(MENU, encoding="utf-8") as fh:
        data = json.load(fh)
    by_norm = {}
    for d in data["dishes"]:
        by_norm[norm(d["name_vn"])] = d["name"]
        by_norm.setdefault(norm(d["name"]), d["name"])
    return by_norm, data


def resolve(course, by_norm):
    key = norm(course)
    if key in by_norm:
        return by_norm[key]
    if key in COURSE_ALIASES and COURSE_ALIASES[key] in by_norm:
        return by_norm[COURSE_ALIASES[key]]
    # A slash usually offers the kitchen a choice ("gà ram gừng/ chiên nước
    # mắm"); the first branch is the one the menu names.
    head = norm(course.split("/")[0])
    if head in by_norm:
        return by_norm[head]
    for cand, full in by_norm.items():
        if cand.startswith(key) or key.startswith(cand):
            if abs(len(cand) - len(key)) <= 12:
                return full
    return None


def parse_sets(text, by_norm):
    seg = text[SET_SHEET[0]:SET_SHEET[1]]
    # Two column bands, read independently over the same rows.
    BANDS = [("SET 1", 0, 5), ("SET 2", 5, 11)]

    tier = None
    tier_price = None
    found = []
    current = {}
    unresolved = []
    incomplete = set()

    for raw, vals in rows(seg):
        head = merged_value(raw, 0, len(raw))
        if head:
            m = TIER_RE.search(head)
            if m:
                # New tier: flush whatever the previous one collected.
                for band, courses in current.items():
                    if courses:
                        found.append({"tier": tier, "variant": band,
                                      "price": tier_price,
                                      "courses": courses,
                                      "incomplete": (tier, band) in incomplete})
                tier = head.strip()
                tier_price = float(m.group(2).replace(".", "").replace(",", ""))
                current = {b[0]: [] for b in BANDS}
                continue

        if tier is None:
            continue

        for band, lo, hi in BANDS:
            course = merged_value(raw, lo, hi)
            if not course or NOT_A_COURSE.match(course.strip()):
                continue
            if BANNER_COURSE.search(norm(course)):
                continue
            dish = resolve(course, by_norm)
            if dish is None:
                unresolved.append((tier, band, course))
                if norm(course) in NO_RECIPE:
                    incomplete.add((tier, band))
            elif dish not in current[band]:
                current[band].append(dish)

    for band, courses in current.items():
        if courses:
            found.append({"tier": tier, "variant": band, "price": tier_price,
                          "courses": courses,
                          "incomplete": (tier, band) in incomplete})
    return found, unresolved


def parse_buffet(text):
    seg = text[BUFFET_SHEET[0]:]
    lines = []
    started = False
    for raw, vals in rows(seg):
        head = merged_value(raw, 0, len(raw))
        if head:
            if "BUFFET" in head.upper():
                started = True
            elif started:
                break          # SET UP BUNGALOW / TỔNG ends the table
            continue
        if not started or len(vals) < 5:
            continue
        if not vals[0].isdigit():
            continue
        name, uom, qty, unit_price = vals[1], vals[2], vals[3], vals[4]
        try:
            qty = float(qty.replace(",", ""))
            unit_price = float(unit_price.replace(",", ""))
        except ValueError:
            continue
        lines.append({
            "ingredient": name,
            "uom": uom,
            "qty_20pax": qty,
            "qty_per_pax": qty / BUFFET_PAX,
            "unit_cost": unit_price,
            "line_cost_20pax": qty * unit_price,
        })
    return lines


def main():
    with open(SRC, encoding="utf-8") as fh:
        text = fh.read()
    by_norm, _menu = load_dishes()

    sets, unresolved = parse_sets(text, by_norm)
    buffet = parse_buffet(text)

    total20 = sum(l["line_cost_20pax"] for l in buffet)
    min_pp = min((l["qty_per_pax"] for l in buffet), default=0)

    print("=" * 70)
    print("SET MENUS: %d variants" % len(sets))
    for s in sets:
        print("  %-46s %9s  %d courses"
              % (s["tier"][:46], "{:,.0f}".format(s["price"]),
                 len(s["courses"])))
        for c in s["courses"]:
            print("        - %s" % c)
    print()
    if unresolved:
        print("!! %d COURSE(S) DID NOT MATCH A KNOWN DISH:" % len(unresolved))
        for tier, band, course in unresolved:
            print("     %-34s %-7s %s" % (tier[:34], band, course))
        for tier, band, course in unresolved:
            why = NO_RECIPE.get(norm(course))
            if why:
                print("   %s" % why)
        print("   Sets carrying one are marked incomplete and the loader will")
        print("   refuse them: skipping a course would under-deduct stock on")
        print("   every sale.")
    else:
        print("every course resolved to a known dish")
    print()
    print("BUFFET: %d lines, %s VND for %d pax = %s VND/pax"
          % (len(buffet), "{:,.0f}".format(total20), BUFFET_PAX,
             "{:,.0f}".format(total20 / BUFFET_PAX)))
    print("  smallest per-pax quantity: %.5f" % min_pp)
    if min_pp and min_pp < 0.01:
        print("  !! below 0.01 -- mrp.bom.explode() rounds each leaf UP at the")
        print("     global 'Product Unit' precision, so this line will be")
        print("     materially overstated. Give that ingredient a finer unit")
        print("     (g instead of kg) rather than raising precision globally.")
    print("=" * 70)

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({
            "sets": sets,
            "unresolved_courses": unresolved,
            "buffet": {
                "pax": BUFFET_PAX,
                "lines": buffet,
                "total_cost_20pax": total20,
                "cost_per_pax": total20 / BUFFET_PAX if buffet else 0,
            },
        }, fh, ensure_ascii=False, indent=1)
    print("wrote %s" % OUT)

    if unresolved:
        sys.exit(1)


if __name__ == "__main__":
    main()
