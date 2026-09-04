# -*- coding: utf-8 -*-
"""Hand-curated link from the 24 Aug guest page's menu to the products that
actually exist on the production till.

The automatic join (exact / containment / fuzzy on the Vietnamese name) gets
most of the way, but it makes mistakes a machine cannot see -- it matched
"Gà nướng dùng kèm cơm lam" (grilled chicken WITH bamboo rice) to plain
"CƠM LAM" (bamboo rice) purely because the shorter string is inside the
longer one. Everything below was checked by eye against the prod product
list in ../tools/ylak_menu_import/english_names.py.

OVERRIDE  page name -> the single prod product it really is.
VARIANTS  page name -> the several prod products it was split into.
          The page shows one row, translated, with a variant picker; the
          variant labels stay Vietnamese because that is what the guest says
          to the kitchen.
ABSENT    on the menu deck but not sold on the till -- shown, not orderable.
"""

OVERRIDE = {
    "Gà nướng dùng kèm cơm lam":       "GÀ ĐỒNG BÀO NƯỚNG DÙNG KÈM CƠM LAM",
    "Gỏi mít chay":                    "GỎI MÍT TRỘN",
    "Tép hồ Lắk ram mặn với khế":      "TÉP HỒ LAK RAM VỚI KHẾ/ RAM MẶN",
    "Thịt heo đồng bào xào lăn":       "HEO XÀO LĂN",
    "Tôm hồ Lắk chiên với khoai lang": "BÁNH TÔM HỒ CHIÊN KHOAI LANG",
    # yoghurt with seasonal fruit is not the same product as seasonal fruit
    "Sữa chua trái cây theo mùa":      "SỮA CHUA",
    # prod sells this as one button listing four preparations
    "Gà hấp lá chanh":
        "GÀ CUỘN SẢ NƯỚNG SỐT CAY/ GÀ RAM GỪNG/ GÀ CHIÊN NƯỚC MẮM/ HẤP LÁ CHANH",
}

VARIANTS = {
    "Gà ram gừng / chiên nước mắm": [
        "GÀ CUỘN SẢ NƯỚNG SỐT CAY/ GÀ RAM GỪNG/ GÀ CHIÊN NƯỚC MẮM/ HẤP LÁ CHANH"],
    "Rau muống / rau rừng / đậu rồng / đậu cove / lá bép xào tỏi": [
        "RAU MUỐNG XÀO TỎI", "RAU RỪNG XÀO TỎI", "ĐẬU RỒNG XÀO/ LUỘC",
        "ĐẬU COVE XÀO TỎI", "LÁ BÉP XÀO TỎI"],
    # only these three are sold boiled with kho quẹt
    "Rau muống / rau rừng / đậu rồng / đậu cove / lá bép luộc kho quẹt": [
        "RAU RỪNG LUỘC KHO QUẸT", "ĐẬU RỒNG XÀO/ LUỘC", "ĐẬU COVE XÀO/ LUỘC"],
    "Trứng vịt hồ Lắk chiên hành / thịt băm": [
        "TRỨNG VỊT HỒ LAK CHIÊN", "TRỨNG VỊT HỒ LAK CHIÊN THỊT BẰM"],
    "Khoai lang / khoai tây chiên": ["KHOAI LANG CHIÊN", "KHOAI TÂY CHIÊN"],
    "Cơm trắng / cơm lam":          ["CƠM TRẮNG", "CƠM LAM"],
    "Cơm chiên hải sản / gà / heo / bò hạt sen": [
        "CƠM CHIÊN HẢI SẢN HẠT SEN", "CƠM CHIÊN GÀ XÉ HẠT SEN",
        "CƠM CHIÊN THỊT HEO", "CƠM CHIÊN THỊT BÒ"],
    "Miến xào bò / heo / gà / hải sản": [          # no pork glass-noodle on prod
        "MIẾN XÀO THỊT BÒ", "MIẾN XÀO THỊT GÀ", "MIẾN XÀO HẢI SẢN"],
    "Mì xào bò / heo / gà / hải sản": [
        "MÌ XÀO BÒ", "MÌ XÀO THỊT HEO", "MÌ XÀO THỊT GÀ", "MÌ XÀO HẢI SẢN"],
    "Club sandwich gà / heo":       ["CLUB SANDWICH GÀ"],   # chicken only on prod
    "Canh cua / tôm tập tàng":      ["CANH CUA TẬP TÀNG", "CANH TÔM TẬP TÀNG"],
    "Canh bí đao / khổ qua nhồi thịt": [
        "CANH BÍ ĐAO NẤU THỊT BẰM", "CANH KHỔ QUA NHỒI THỊT"],
    "Canh sườn heo nấu đu đủ / măng": [
        "CANH SƯỜN HEO NẤU ĐU ĐỦ", "CANH SƯỜN HEO NẤU MĂNG"],
    "Canh chua chả cá thác lác / mướp đắng rừng": [
        "CANH CÁ THÁC LÁC MĂNG CHUA", "CANH CHẢ CÁ NẤU MƯỚP ĐẮNG"],
    "Lẩu chả cá thác lác măng chua / mướp đắng": [
        "LẨU CÁ THÁC LÁC NẤU MƯỚP ĐẮNG", "LẨU CÁ THÁC LÁC MƯỚP ĐẮNG RỪNG"],
    "Kem sô cô la / vani":          ["KEM SÔ CÔ LA", "KEM VANI"],
}

ABSENT = ["Cơm chiên cá mặn / trứng tỏi / muối ớt"]

# The page's 12 set menus against prod's 12 combo products. The page numbers
# them 1-8 within each price tier; prod encodes tier in the product name, so
# the pairing is by (price, order of appearance) and is exactly 1:1.
SETS = [
    (195000, ["COMBO SET MENU 01 195000",   "COMBO SET MENU 02 195000"]),
    (255000, ["COMBO SET MENU 01 255000",   "COMBO SET MENU 02 255000"]),
    (245000, ["COMBO SET LUNCH 01 245000",  "COMBO SET LUNCH 02 245000"]),
    (295000, ["COMBO SET DINNER 01 295000", "COMBO SET DINNER 02 295000"]),
    (375000, ["COMBO SET DINNER 01 375000", "COMBO SET DINNER 02 375000"]),
    (455000, ["COMBO SET DINNER 01 455000", "COMBO SET DINNER 02 455000"]),
]
