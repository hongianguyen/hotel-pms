# -*- coding: utf-8 -*-
"""Selling prices transcribed from the 'FOOD MENU' deck (Google Slides).

Source: https://docs.google.com/presentation/d/1fmA5JMZmN1IuAM6WOpjW85Lusg9JvaaZQevHiYkrq74
Transcribed 16 Aug 2026. This is the CUSTOMER-FACING price list and is the
authority for POS sale prices.

Why this is a hand-checked table and not a parser: the deck's text export
interleaves dish names, English descriptions and prices, and in several slides
two or three dishes are listed before their prices appear as a run
(e.g. SOUP BÍ ĐỎ / SALAD RAU XANH / GỎI CUỐN -> 95,000 / 95,000 / 135,000).
Positional parsing of that is guesswork; a reviewed table is auditable.

Prices are VND. `None` means the deck lists the dish with no price of its own.
"""

# (vietnamese_name, english_name, price_vnd, menu_section)
DECK_PRICES = [
    # ---- THỰC ĐƠN CHAY / VEGETARIAN MENU ----
    ("KHAI VỊ CHAY", "Vegetarian appetizer platter", 185000, "Chay"),
    ("GỎI ĐU ĐỦ CHAY", "Mixed green papaya salad", 135000, "Chay"),
    ("GỎI MÍT CHAY", "Mixed green jackfruit salad", 135000, "Chay"),
    ("GỎI MĂNG RỪNG", "Mixed young bamboo salad", 135000, "Chay"),
    ("CHẢ GIÒ CHAY", "Crispy spring rolls with tofu, taro, carrot", 105000, "Chay"),
    ("ĐẬU HỦ CHIÊN MUỐI SẢ", "Stuffed tofu with salt and lemongrass", 75000, "Chay"),
    ("ĐẬU HỦ NHỒI NHÂN SỐT CÀ CHUA", "Tofu stuffed with mushroom, carrot", 95000, "Chay"),
    ("NẤM KHO TỘ", "Caramel mushroom in claypot", 155000, "Chay"),
    ("MÍT NON KHO RỊU", "Caramel young jackfruit in claypot", 135000, "Chay"),
    ("CÀ TÍM KHO TỘ", "Caramelized eggplant in claypot", 95000, "Chay"),
    ("NGŨ QUẢ LUỘC KHO QUẸT CHAY", "Mixed five fruit with vegetarian sauce", 135000, "Chay"),
    ("CÀ TÍM XÀO LÁ LỐT", "Stir fried eggplant with Lot leaf", 95000, "Chay"),
    ("ĐẬU KHUÔN XÀO GIÁ & RAU CỦ", "Stir fried tofu with bean sprouts", 95000, "Chay"),
    ("CANH CHUA CHAY", "Tofu, tomato, pineapple, okra, bean sprouts", 135000, "Chay"),
    ("CANH BÍ ĐỎ ĐẬU PHỘNG", "Pumpkin soup with peanut", 135000, "Chay"),
    ("CANH LAGIM", "Pumpkin, carrot, potato, squash", 135000, "Chay"),
    ("LẨU NẤU CHAO", "Mixed vegetable with tofu, taro, soya cheese", 375000, "Chay"),

    # ---- KHAI VỊ / APPETIZERS & SALADS ----
    ("KHAI VỊ Y LAK", "Y Lak appetizer platter", 185000, "Khai vị"),
    ("SOUP BÍ ĐỎ", "Pumpkin soup", 95000, "Khai vị"),
    ("SALAD RAU XANH", "Mixed garden green salad", 95000, "Khai vị"),
    ("GỎI CUỐN TÔM THỊT VƯỜN LẮK", "Lak's garden summer rolls", 135000, "Khai vị"),
    ("CHẢ GIÒ TÔM THỊT", "Crispy spring rolls with pork & shrimp", 135000, "Khai vị"),
    ("GỎI CÀ ĐẮNG CÁ CƠM", "Wild eggplant salad with dry anchovy", 135000, "Khai vị"),
    ("GỎI BÒ BÓP THẤU", "Beef salad with Vietnamese herbs", 165000, "Khai vị"),
    ("GỎI MĂNG RỪNG TÔM THỊT", "Young bamboo salad with pork & shrimp", 165000, "Khai vị"),
    ("GỎI GÀ HOA CHUỐI", "Banana flower salad with chicken", 165000, "Khai vị"),
    ("GỎI NGÓ SEN TÔM THỊT", "Lotus roots salad with pork & shrimp", 165000, "Khai vị"),
    ("GỎI ĐU ĐỦ TÔM THỊT", "Papaya salad with pork & shrimp", 165000, "Khai vị"),
    ("GỎI RAU MUỐNG TÉP RAM", "Morning glory salad with Lak lake shrimp", 165000, "Khai vị"),

    # ---- CÁ & THỊT / FISH & MEAT ----
    ("CÁ RÔ PHI CHIÊN GIÒN CHẤM MẮM XOÀI", "Crispy tilapia with green mango", 165000, "Cá & Thịt"),
    ("CÁ DIÊU HỒNG CHIÊN SỐT CHANH DÂY", "Red tilapia with passion fruit sauce", 165000, "Cá & Thịt"),
    ("TÉP HỒ LAK RAM MẶN VỚI KHẾ", "Stir fried Lak lake shrimp with star fruit", 185000, "Cá & Thịt"),
    ("CHẢ CÁ HỒ LĂK", "Deep-fried Lak lake fishcake", 195000, "Cá & Thịt"),
    ("BÒ NƯỚNG LÁ LỐT", "Grilled beef wrapped in wild betel leaf", 165000, "Cá & Thịt"),
    ("CÁ DIÊU HỒNG NƯỚNG GIẤY BẠC", "Red tilapia baked in foil", 165000, "Cá & Thịt"),
    ("HEO NƯỚNG ỐNG TRE ĂN KÈM CƠM LAM", "Charcoal pork in bamboo with sticky rice", 195000, "Cá & Thịt"),
    ("CÁ LĂNG ƯỚP NGHỆ NƯỚNG LÁ CHUỐI", "Hemibagrus catfish in banana leaf", 215000, "Cá & Thịt"),
    ("SƯỜN NƯỚNG BBQ CƠM LAM", "Pork ribs with bbq sauce and sticky rice", 215000, "Cá & Thịt"),
    ("GÀ NƯỚNG DÙNG KÈM CƠM LAM", "M'Nong charcoal chicken with sticky rice (half)", 275000, "Cá & Thịt"),
    ("VỊT QUAY HỒ LĂK SỐT TIÊU ĐEN", "Roast duck with black pepper and honey", 395000, "Cá & Thịt"),
    ("GÀ HẤP LÁ CHANH", "Steamed chicken with lemon leaf (half)", 275000, "Cá & Thịt"),
    ("GÀ RAM GỪNG", "Chicken with ginger / fried with fish sauce (half)", 275000, "Cá & Thịt"),
    ("CÁ LĂNG KHO TỘ", "Caramelized Hemibagrus catfish", 215000, "Cá & Thịt"),
    ("CÁ BỐNG KHO TIÊU", "Caramelized gobies with black pepper", 195000, "Cá & Thịt"),
    ("TÔM KHO TỘ", "Caramelized shrimps with black pepper", 195000, "Cá & Thịt"),
    ("THỊT HEO KHO TỘ", "Caramelized pork belly", 165000, "Cá & Thịt"),
    ("THỊT HEO ĐỒNG BÀO XÀO LĂN", "Stir fried local pork with lemongrass", 185000, "Cá & Thịt"),
    ("CÁ BÔNG LAU KHO TỘ", "Caramelized catfish", None, "Cá & Thịt"),
    ("ĐẬU HỦ SỐT CÀ CHUA", "Tofu with tomato sauce", 95000, "Cá & Thịt"),
    ("ĐẬU HỦ SỐT SẢ", "Tofu with lemongrass", 75000, "Cá & Thịt"),
    ("CÀ TÍM NƯỚNG MỠ HÀNH", "Charcoal eggplant with onion oil", 95000, "Rau"),

    # ---- RAU / VEGETABLES ----
    ("LÁ BÉP XÀO TỎI", "Sauteed bep leaf with garlic", 95000, "Rau"),
    ("LÁ BÉP XÀO CÁ HỘP", "Sauteed bep leaves with canned fish", 115000, "Rau"),
    ("RAU MUỐNG XÀO TỎI", "Sauteed morning glory with garlic", 95000, "Rau"),
    ("RAU RỪNG XÀO TỎI", "Sauteed wild vegetable with garlic", 95000, "Rau"),
    ("RAU CỦ XÀO THẬP CẨM", "Sauteed mixed vegetable", 95000, "Rau"),
    ("NGÓ SEN TƯƠI XÀO TỎI", "Sauteed fresh lotus roots with garlic", 95000, "Rau"),
    ("ĐỌT BÍ XÀO TỎI", "Sauteed pumpkin shoots with garlic", 95000, "Rau"),
    ("RAU RỪNG LUỘC KHO QUẸT", "Steamed wild vegetable with caramelized sauce", 115000, "Rau"),

    # ---- CƠM & MÌ / RICE & NOODLES ----
    ("CƠM TRẮNG", "Steamed rice / sticky rice in bamboo", 30000, "Cơm & Mì"),
    ("MIẾN XÀO", "Stir-fried vermicelli with meat and vegetables", 155000, "Cơm & Mì"),
    ("MÌ XÀO BÒ", "Stir-fried egg noodles with beef", 155000, "Cơm & Mì"),
    ("CƠM CHIÊN HẢI SẢN HẠT SEN", "Seafood fried rice with lotus seeds", 155000, "Cơm & Mì"),
    ("CƠM CHIÊN GÀ HẠT SEN", "Chicken fried rice with lotus seeds", 155000, "Cơm & Mì"),
    ("MÌ XÀO RAU CỦ", "Stir-fried egg noodles with vegetables", 135000, "Cơm & Mì"),
    ("CƠM CHIÊN RAU CỦ HẠT SEN", "Vegetable fried rice with lotus seeds", 135000, "Cơm & Mì"),
    ("MÌ Ý SỐT CÀ CHUA", "Pomodoro spaghetti", 135000, "Cơm & Mì"),
    ("MÌ Ý SỐT BÒ BẰM", "Spaghetti bolognaise", 155000, "Cơm & Mì"),
    ("BÒ LÚC LẮC KHOAI TÂY CHIÊN", "Wok fried beef cubes + french fries", 245000, "Cơm & Mì"),
    ("BÒ BEEFSTEAK KHOAI TÂY CHIÊN", "Beefsteak + french fries", 245000, "Cơm & Mì"),
    ("CLUB SANDWICH GÀ", "Club sandwich with chicken", 245000, "Cơm & Mì"),

    # ---- CANH / SOUPS ----
    ("CANH CẢI THỊT BẰM", "Mustard leaf soup with ground pork", 135000, "Canh"),
    ("CANH BÍ ĐAO NHỒI THỊT", "Squash soup stuffed with pork", 165000, "Canh"),
    ("CANH GÀ LÁ GIANG", "Chicken soup with sour-sop creeper leaf", 185000, "Canh"),
    ("CANH CHUA CÁ BÔNG LAU", "Sweet and sour catfish soup", 165000, "Canh"),
    ("CANH CÀ ĐẮNG CÁ CƠM", "Wild eggplant soup with anchovies", 165000, "Canh"),
    ("CANH CUA TẬP TÀNG", "Mixed garden vegetable soup with field crab", 135000, "Canh"),
    ("CANH TÔM TẬP TÀNG", "Mixed garden vegetable soup with shrimp", 135000, "Canh"),
    ("CANH SƯỜN HEO NẤU ĐU ĐỦ", "Papaya soup with pork rib", 165000, "Canh"),
    ("CANH CHUA CHẢ CÁ THÁC LÁC", "Sour soup with fishcake", 165000, "Canh"),
    ("CANH CHUA CÁ LĂNG", "Sweet and sour Hemibagrus catfish soup", 195000, "Canh"),

    # ---- LẨU / HOTPOT ----
    ("LẨU CÁ LĂNG ĐỒNG NẤU MĂNG CHUA", "Sour hotpot with catfish and bamboo shoot", 385000, "Lẩu"),
    ("LẨU CHẢ CÁ THÁC LÁC MĂNG CHUA", "Wild sour bamboo and fishcake hotpot", 385000, "Lẩu"),
    ("LẨU GÀ LÁ GIANG", "Braised chicken and sour-sop creeper leaf hotpot", 385000, "Lẩu"),

    # ---- TRÁNG MIỆNG / DESSERTS ----
    ("CHÈ CHUỐI", "Banana sweet custard", 35000, "Tráng miệng"),
    ("CHÈ HẠT SEN", "Lotus seeds sweet custard", 35000, "Tráng miệng"),
    ("TRÁI CÂY THEO MÙA", "Seasonal fruit platter", 75000, "Tráng miệng"),
    ("BÁNH CHUỐI NƯỚNG DÙNG KÈM KEM VANI", "Baked banana cake with vanilla ice cream", 75000, "Tráng miệng"),
    ("KEM SÔ CÔ LA", "Chocolate ice cream", 65000, "Tráng miệng"),
    ("KEM VANILLA", "Vanilla ice cream", 65000, "Tráng miệng"),
    ("SỮA CHUA TRÁI CÂY THEO MÙA", "Seasonal fruit yogurt", 35000, "Tráng miệng"),

    # ---- MÓN VÙNG MIỀN / LOCAL ----
    ("TEMPURA CỦ QUẢ", "Vegetable tempura", 135000, "Món vùng miền"),
    ("TÔM HỒ LAK CHIÊN VỚI KHOAI LANG", "Lak lake shrimp fried with sweet potato", 185000, "Món vùng miền"),
    ("KHOAI TÂY CHIÊN", "French fries", 65000, "Món vùng miền"),
    ("TRỨNG VỊT HỒ LAK CHIÊN HÀNH", "Fried duck egg with onion", 45000, "Món vùng miền"),
]
