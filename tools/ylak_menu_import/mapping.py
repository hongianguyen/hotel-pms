# -*- coding: utf-8 -*-
"""Hand-checked name mappings between the cost workbook and the menu deck.

Kept as a reviewed table rather than fuzzy matching, for the reason
deck_prices.py already gives: positional or approximate matching of these
names is guesswork, and a wrong match silently prices a dish incorrectly.

`extract.py` holds the original 45 ALIASES, built against the older COST.xlsx.
The newer 'cost of places rvd' workbook spells many dishes differently, so
these are added on top. Keys and values are both normalised with norm() at
use, so case and accents do not matter here.
"""

# Recipe-sheet name -> deck name. Only entries where the two clearly name the
# same dish.
RVD_ALIASES = {
    "goi mit tron": "GỎI MÍT CHAY",
    "au hu chien sa": "ĐẬU HỦ CHIÊN MUỐI SẢ",
    "au hu nhoi sot ca chua": "ĐẬU HỦ NHỒI NHÂN SỐT CÀ CHUA",
    "tep ho lak ram voi khe ram man": "TÉP HỒ LAK RAM MẶN VỚI KHẾ",
    "ga ong bao nuong dung kem com lam": "GÀ NƯỚNG DÙNG KÈM CƠM LAM",
    "vit quay ho lak sot tieu en va mat ong": "VỊT QUAY HỒ LĂK SỐT TIÊU ĐEN",
    "ca bong kho tieu chien gion": "CÁ BỐNG KHO TIÊU",
    "heo xao lan": "THỊT HEO ĐỒNG BÀO XÀO LĂN",
    "khai vi chay ho lak": "KHAI VỊ CHAY",
    "goi ngo sen tuoi ho lak xao": "GỎI NGÓ SEN TÔM THỊT",

    # Owner, 30 Aug 2026: "Ga Hap La Chanh and Ga Nuong La Chanh has same
    # cost." Both chicken rows therefore take the deck's 275,000. The second
    # is a single recipe row covering four preparations, which mirrors the
    # deck's own combined line ("GÀ RAM GỪNG/ CHIÊN NƯỚC MẮM (Nửa con/Half)"),
    # so it stays one POS item rather than being split into four.
    "ga nuong la chanh": "GÀ HẤP LÁ CHANH",
    "ga cuon sa nuong sot cay ga ram gung ga chien nuoc mam hap la chanh":
        "GÀ RAM GỪNG",
}

# Deliberately NOT aliased. Each is a plausible-looking pair that names a
# different dish, and a wrong match here puts a wrong price on the till. The
# owner decides; until then the dish loads unpriced and stays out of POS.
AMBIGUOUS = {
    # Owner, 30 Aug 2026: "Lau Chay Thap Cam, new item, enter it in menu."
    # So it is NOT the deck's LẨU NẤU CHAO — it is a new dish with no deck
    # entry, and therefore no price yet. It loads with its recipe and stays
    # out of POS until the owner sets one.
    "lau chay thap cam": (
        "NEW dish per the owner, distinct from the deck's LẨU NẤU CHAO. "
        "Needs a selling price before it can be sold."),
}
