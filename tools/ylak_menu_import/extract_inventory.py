# -*- coding: utf-8 -*-
"""Parse the KHO stock counts into inventory_data.json.

    python3 extract_inventory.py

Offline: reads sources/kho_no_duplicate.md, writes inventory_data.json and
kho_review.csv, and touches nothing in Odoo.

The workbook is ten stock-count tables spread over three sheets. They do NOT
share a column layout, so this is driven by a per-table spec rather than one
generic parser -- a generic parser silently mis-reads the department tables,
which put the item name in the second column behind an STT counter.

Every table's store is written in its own heading, so nothing here guesses
which department an item belongs to.
"""
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ylak_common import norm  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources", "kho_no_duplicate.md")
OUT = os.path.join(HERE, "inventory_data.json")
REVIEW = os.path.join(HERE, "kho_review.csv")

# The seven stores, keyed by the code used for the stock location.
STORES = {
    "BEP": "Kho Bếp",
    "NHAHANG": "Kho Nhà hàng & Bar",
    "BAOTRI": "Kho Bảo trì",
    "BUONGPHONG": "Kho Buồng phòng",
    "LETAN": "Kho Lễ tân",
    "TOUR": "Kho Tour",
    "CAYXANH": "Kho Cây xanh",
}

# Table heading -> (store, is_equipment). Matched on a normalised substring.
#
# The needles deliberately avoid the letter Đ. norm() strips accents via NFD,
# but Đ is a distinct letter with no decomposition, so it survives NFD and is
# then dropped as non-ASCII: "ĐỒ TOUR" normalises to "o tour", not "do tour".
# Needles containing "do" silently matched nothing, which swallowed the Lễ tân,
# Tour and Cây xanh tables into the preceding store.
TABLE_SPECS = [
    ("cong cu dung cu bo phan bao tri", "BAOTRI", True),
    ("cong cu dung cu buong phong", "BUONGPHONG", True),
    ("cong cu dung cu nha hang", "NHAHANG", True),
    ("cong cu dung cu bep", "BEP", True),
    ("luu niem", "LETAN", True),
    ("kiem ke o tour", "TOUR", True),
    ("kiem ke o cay xanh", "CAYXANH", True),
]

# The three stock-count sheets each open with a BÁO CÁO KIỂM KÊ banner, in this
# order. Used only until a department heading takes over; sheet 3's own opening
# table is unheaded office and general supplies.
BANNER = "bao cao kiem ke"
SHEET_DEFAULTS = [
    ("BEP", False),        # sheet 1: KHO BẾP, the recipe ingredients
    ("NHAHANG", False),    # sheet 2: bar / resale drinks
    ("BAOTRI", True),      # sheet 3: office & general supplies
]

# Rows that are headings, totals or layout noise rather than stock.
SKIP_EXACT = {
    "", "stt", "ten", "tên", "TÊN", "hang hoa", "hàng hoá", "dvt", "đvt",
    "so luong", "số lượng", "ten cong cu dung cu", "tên công cụ dụng cụ",
    "nhom hang hoa", "nhóm hàng hoá", "don vi tinh", "đơn vị tính",
    "ton cuoi ky", "tồn cuối kỳ", "tong cong", "tổng cộng", "tong", "tổng",
    "ghi chu", "ghi chú", "bo sung", "bổ sung",
}


def clean(cell):
    return re.sub(r"\\?\[merged\\?\]", "", cell).replace("\\", "").strip()


def is_merged_heading(cells):
    """A merged heading repeats one value across every column."""
    vals = [clean(c) for c in cells if "merged" in c]
    if not vals:
        return None
    uniq = {v for v in vals if v}
    if len(uniq) == 1:
        return uniq.pop()
    return None


def parse_qty(raw):
    raw = clean(raw).replace(",", "")
    if not raw:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return None


def parse():
    with open(SRC, encoding="utf-8") as fh:
        text = fh.read()

    # Read the file as one linear stream. Splitting on the markdown table
    # separator does not give three sheets -- each department table carries its
    # own separator, so the file splits into ten blocks and any sheet-indexed
    # default lands on the wrong store. Track the current store from the
    # headings instead, seeded by the BÁO CÁO KIỂM KÊ banner that opens each
    # of the three sheets.
    rows = []
    review = []
    banner_seen = 0
    store, equip = SHEET_DEFAULTS[0]
    table = "KHO BẾP"

    for lineno, line in enumerate(text.split("\n"), 1):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or ":-:" in line:
            continue

        heading = is_merged_heading(cells)
        if heading:
            key = norm(heading)
            if BANNER in key:
                if banner_seen < len(SHEET_DEFAULTS):
                    store, equip = SHEET_DEFAULTS[banner_seen]
                    table = ["KHO BẾP", "KHO NHÀ HÀNG",
                             "Văn phòng phẩm & vật tư chung"][banner_seen]
                banner_seen += 1
                continue
            for needle, st, eq in TABLE_SPECS:
                if needle in key:
                    store, equip, table = st, eq, heading
                    break
            continue

        vals = [clean(c) for c in cells]
        if not any(vals):
            continue

        # Column layout differs per table. When the first cell is a plain
        # row counter the name sits in the second column; otherwise the
        # name leads. Everything after is (group?, unit, qty) in order.
        if vals[0].isdigit() and len(vals) > 1 and vals[1]:
            name, rest = vals[1], vals[2:]
        else:
            name, rest = vals[0], vals[1:]

        if norm(name) in {norm(s) for s in SKIP_EXACT} or not name:
            continue
        if name.isdigit():
            continue

        # Quantity is the last numeric cell; unit is the last non-numeric
        # cell before it. Reading positionally instead breaks on the
        # tables that carry an extra group column.
        qty, unit, group = None, "", ""
        numeric_idx = None
        for i in range(len(rest) - 1, -1, -1):
            q = parse_qty(rest[i])
            if q is not None and rest[i] != "":
                qty, numeric_idx = q, i
                break
        if numeric_idx is not None:
            for j in range(numeric_idx - 1, -1, -1):
                if rest[j] and parse_qty(rest[j]) is None:
                    unit = rest[j]
                    group = rest[j - 1] if j >= 1 else ""
                    break
        if qty is None:
            review.append({
                "table": table, "name": name, "reason": "no quantity cell",
                "raw": " | ".join(vals),
            })
            continue

        rows.append({
            "name": name,
            "uom": unit or "Cái",
            "qty": qty,
            "store": store,
            "group": group,
            "is_equipment": equip,
            "table": table,
            "source_line": lineno,
        })

    return rows, review


def main():
    rows, review = parse()

    # Product identity is the RAW name, not the normalised one.
    #
    # Owner's call, 30 Aug 2026: rows that look like duplicates are separate
    # items. The source bears that out -- every apparent collision differs only
    # inside parentheses, which norm() strips: "Máy sưởi" (a heater) vs "Máy
    # sưởi (máy khử khuẩn)" (a steriliser); "Nệm 0,9*2m ( Dorm)" vs "Nệm 0.9
    # *2m ( 4 kpan)"; "Dao phát" vs "Dao phát ( chuyển qua cây xanh )". Keying
    # on the raw name keeps them apart without any special case, and nothing is
    # ever summed.
    products = {}
    quants = []
    near = defaultdict(set)

    for r in rows:
        key = r["name"].strip()
        near[norm(r["name"])].add(key)
        if key not in products:
            products[key] = {
                "name": key,
                "uom": r["uom"],
                "store": r["store"],
                "group": r["group"],
                "is_equipment": r["is_equipment"],
                "table": r["table"],
            }
        quants.append({
            "name": key,
            "store": r["store"],
            "qty": r["qty"],
            "uom": r["uom"],
            "table": r["table"],
        })

    # Names that differ only inside parentheses. Not an error -- they are
    # deliberately distinct products -- but worth listing so the owner can see
    # what the till and the stock report will show side by side.
    near_dupes = {n: sorted(v) for n, v in near.items() if len(v) > 1}

    # The same exact name twice in one store WOULD be a double count: two
    # adjustments, the second overwriting the first.
    exact = [k for k, c in Counter(
        (q["name"], q["store"]) for q in quants).items() if c > 1]

    multi_store = {}
    for q in quants:
        multi_store.setdefault(q["name"], set()).add(q["store"])
    multi_store = {n: sorted(v) for n, v in multi_store.items() if len(v) > 1}

    by_store = Counter(q["store"] for q in quants)
    equip = sum(1 for p in products.values() if p["is_equipment"])
    nonzero = sum(1 for q in quants if q["qty"])

    data = {
        "stores": STORES,
        "products": list(products.values()),
        "quants": quants,
        "multi_store": multi_store,
        "near_duplicate_names": near_dupes,
        "counts": {"rows": len(rows), "products": len(products),
                   "quants": len(quants), "by_store": dict(by_store),
                   "equipment": equip, "nonzero_qty": nonzero},
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)

    with open(REVIEW, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["table", "name", "reason", "raw"])
        w.writeheader()
        w.writerows(review)

    print("=" * 70)
    print("source rows       : %d" % len(rows))
    print("distinct products : %d" % len(products))
    print("stock rows (quants): %d  (%d with stock on hand)" % (len(quants), nonzero))
    print("equipment (CCDC)  : %d" % equip)
    print("consumables       : %d" % (len(products) - equip))
    print()
    for store, n in sorted(by_store.items(), key=lambda kv: -kv[1]):
        print("  %-12s %-26s %4d" % (store, STORES[store], n))
    print("  %-12s %-26s %4d" % ("", "TOTAL", sum(by_store.values())))
    print()
    uom_counts = Counter(p["uom"] for p in products.values())
    print("units of measure  : %d distinct" % len(uom_counts))
    print("  most common     : %s" % ", ".join(
        "%s(%d)" % (u, n) for u, n in uom_counts.most_common(8)))
    print()
    if multi_store:
        print("stocked in more than one store: %d (one product, a quant each --"
              % len(multi_store))
        print("  category follows the first table listed):")
        for n, stores in sorted(multi_store.items()):
            print("     %-38s %s" % (n, ", ".join(stores)))
    else:
        print("every product is stocked in exactly one store")
    if near_dupes:
        print()
        print("%d name(s) differ only inside parentheses -- kept as SEPARATE"
              % len(near_dupes))
        print("  products, per the owner:")
        for _n, variants in sorted(near_dupes.items()):
            for v in variants:
                print("     %s" % v)
    if exact:
        print("!! %d item(s) listed twice with the IDENTICAL name in one store"
              % len(exact))
        for name, store in exact[:10]:
            print("     %-38s %s" % (name, store))
    print("rows needing review: %d  -> %s" % (len(review), REVIEW))
    print("=" * 70)
    print("wrote %s" % OUT)


if __name__ == "__main__":
    main()
