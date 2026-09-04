# -*- coding: utf-8 -*-
"""English name + description for every product on the Y Lak POS.

Source of record for the food: the owner's "LAK Tented Camp - A-la-carte Menu"
Google Slides deck
https://docs.google.com/presentation/d/1fmA5JMZmN1IuAM6WOpjW85Lusg9JvaaZQevHiYkrq74
read 04 Sep 2026. That deck prints each dish as Vietnamese name, then one line
of English, then the price -- so the English line is both the name and the
description, and both columns below are derived from it.

The deck is FOOD ONLY. It carries no drinks, no bar and no wine, but 76 of the
190 POS products are exactly that (the owner added them by hand after the
01 Sep menu import -- they have no `__ylak__` external id). Those are written
here too, marked `inferred`, so the owner can see at a glance which English
text did not come off their own menu.

Match key is the product's EXACT Vietnamese name as it stands on prod,
including the doubled space in "GOI  BO BOP THAU" and the spaced parentheses
in "VANG DALAT ( DO)". Odoo names are case-sensitive and the sources disagree
about case, so nothing here is matched loosely -- see load_50_english.py.

`en_name = None` means the product's name is ALREADY English or an
international brand (MOJITO, BACARDI, the five wines). Those keep their name
untouched and get a description only; "MOJITO / Mojito cocktail" helps nobody.

source values:
    deck          the deck lists this exact dish; English is the deck's own
    deck-variant  the deck lists it under a slightly different Vietnamese name,
                  or prod splits/merges what the deck prints as one line
    combo         a set menu; English is built from the courses the combo
                  ACTUALLY contains on prod, not from the deck's course list,
                  because the two differ in a few places (see README)
    inferred      not in the deck at all -- written here, owner to confirm
"""

# (vietnamese_name_on_prod, en_name, en_description, source)
ENGLISH = [
    # ---------------------------------------------------------------- salads
    ("KHAI VỊ Y LAK", "Y Lak appetiser platter",
     "Eggplant salad with dried anchovy, egg salad, fish cake and grilled chicken.", "deck"),
    ("KHAI VỊ CHAY HỒ LAK", "Vegetarian appetiser platter",
     "Deep-fried spring rolls, fresh spring rolls, jackfruit salad and papaya salad.", "deck"),
    ("SOUP BÍ ĐỎ", "Pumpkin soup", "Pumpkin soup.", "deck"),
    ("SALAD RAU XANH HỖN HỢP", "Mixed garden green salad",
     "Mixed garden green salad with tomato, cucumber and vinegar dressing.", "deck"),
    ("GỎI CUỐN TÔM THỊT", "Fresh summer rolls with pork & shrimp",
     "Lak garden summer rolls with pork, shrimp and local herbs.", "deck"),
    ("CHẢ GIÒ TÔM THỊT", "Crispy spring rolls with pork & shrimp",
     "Crispy spring rolls with pork and shrimp.", "deck"),
    ("GỎI CÀ ĐẮNG CÁ CƠM", "Wild eggplant salad with dried anchovy",
     "Wild eggplant salad with dried anchovy.", "deck"),
    ("GỎI  BÒ BÓP THẤU", "Beef salad with Vietnamese herbs",
     "Beef salad with Vietnamese herbs.", "deck"),
    ("GỎI MĂNG RỪNG TÔM THỊT", "Wild bamboo shoot salad with pork & shrimp",
     "Young wild bamboo shoot salad with pork and shrimp. Seasonal.", "deck"),
    ("GỎI GÀ HOA CHUỐI", "Banana flower salad with chicken",
     "Banana flower salad with chicken.", "deck"),
    ("GỎI NGÓ SEN TÔM THỊT", "Lotus root salad with pork & shrimp",
     "Lotus root salad with pork and shrimp.", "deck"),
    ("GỎI ĐU ĐỦ TÔM THỊT", "Green papaya salad with pork & shrimp",
     "Green papaya salad with pork and shrimp.", "deck"),
    ("GỎI RAU MUỐNG TÉP RAM HỒ LĂK", "Morning glory salad with Lak lake shrimp",
     "Morning glory salad with Lak lake shrimp.", "deck"),
    ("GỎI ĐU ĐỦ CHAY", "Vegetarian green papaya salad",
     "Green papaya salad with carrot, Vietnamese herbs, tofu and peanut.", "deck"),
    ("GỎI MÍT TRỘN", "Young jackfruit salad",
     "Green jackfruit salad with Vietnamese herbs, tofu and peanut.", "deck-variant"),
    ("GỎI MĂNG RỪNG", "Wild bamboo shoot salad",
     "Young wild bamboo shoot salad with Vietnamese herbs, tofu and peanut. Seasonal.", "deck"),
    ("CHẢ GIÒ CHAY", "Vegetarian spring rolls",
     "Crispy spring rolls with tofu, taro and carrot.", "deck"),
    ("CUỐN DIẾP & RAM BẮP", "Lettuce rolls & corn fritters",
     "Lettuce rolls served with crispy corn fritters.", "deck"),

    # ------------------------------------------------------------ tofu & veg
    ("ĐẬU HỦ CHIÊN SẢ", "Fried tofu with lemongrass",
     "Tofu fried with a little salt and lemongrass.", "deck"),
    ("ĐẬU HỦ NHỒI SỐT CÀ CHUA", "Stuffed tofu in tomato sauce",
     "Tofu stuffed with mushroom and carrot in tomato sauce.", "deck"),
    ("NẤM KHO TỘ", "Caramelised mushrooms in claypot",
     "Caramelised mushrooms in claypot.", "deck"),
    ("MÍT NON KHO RỊU", "Caramelised young jackfruit in claypot",
     "Caramelised young jackfruit in claypot.", "deck"),
    ("CÀ TÍM KHO TỘ", "Caramelised eggplant in claypot",
     "Caramelised eggplant in claypot.", "deck"),
    ("NGŨ QUẢ LUỘC + KHO QUẸT CHAY", "Steamed five vegetables with vegetarian dip",
     "Five steamed vegetables served with a vegetarian caramelised dip.", "deck"),
    ("CÀ TÍM XÀO LÁ LỐT", "Stir-fried eggplant with betel leaf",
     "Stir-fried eggplant with wild betel leaf.", "deck"),
    ("ĐẬU KHUÔN XÀO GIÁ & RAU CỦ", "Stir-fried tofu with bean sprouts & vegetables",
     "Stir-fried tofu with bean sprouts and vegetables.", "deck"),
    ("CÀ TÍM NƯỚNG MỠ HÀNH", "Charcoal eggplant with spring onion oil",
     "Charcoal-grilled eggplant with spring onion oil.", "deck"),
    ("LÁ BÉP XÀO TỎI", "Sautéed bep leaves with garlic",
     "Sautéed bep leaves with garlic.", "deck"),
    ("LÁ BÉP XÀO CÁ HỘP", "Sautéed bep leaves with canned fish",
     "Sautéed bep leaves with canned fish.", "deck"),
    ("RAU MUỐNG XÀO TỎI", "Sautéed morning glory with garlic",
     "Sautéed morning glory with garlic.", "deck"),
    ("RAU RỪNG XÀO TỎI", "Sautéed wild vegetables with garlic",
     "Sautéed wild forest vegetables with garlic.", "deck"),
    ("RAU CỦ XÀO THẬP CẨM", "Sautéed mixed vegetables",
     "Sautéed mixed vegetables with oyster sauce.", "deck"),
    ("NGÓ SEN TƯƠI HỒ LĂK XÀO", "Sautéed fresh Lak lake lotus roots",
     "Sautéed fresh Lak lake lotus roots with garlic. Seasonal.", "deck-variant"),
    ("ĐỌT BÍ XÀO", "Sautéed pumpkin shoots with garlic",
     "Sautéed pumpkin shoots with garlic.", "deck"),
    ("RAU RỪNG LUỘC KHO QUẸT", "Steamed wild vegetables with caramelised dip",
     "Steamed wild forest vegetables with Lak caramelised dipping sauce.", "deck"),
    ("RAU CỦ LUỘC KHO QUẸT", "Steamed vegetables with caramelised dip",
     "Steamed mixed vegetables with Lak caramelised dipping sauce.", "deck-variant"),
    ("ĐẬU COVE XÀO/ LUỘC", "Green beans, sautéed or steamed",
     "Cove beans, sautéed with garlic or steamed with caramelised dip.", "deck-variant"),
    ("ĐẬU RỒNG XÀO/ LUỘC", "Dragon beans, sautéed or steamed",
     "Dragon beans, sautéed with garlic or steamed with caramelised dip.", "deck-variant"),
    ("MĂNG XÀO LÁ QUẾ", "Stir-fried bamboo shoots with basil",
     "Stir-fried bamboo shoots with basil leaf.", "inferred"),

    # --------------------------------------------------------- fish and meat
    ("CÁ RÔ PHI CHIÊN GIÒN CHẤM MẮM XOÀI", "Crispy tilapia with green mango fish sauce",
     "Crispy tilapia, fresh from the lake, served with green mango and fish sauce.", "deck"),
    ("CÁ DIÊU HỒNG SỐT CHANH DÂY", "Red tilapia with passion fruit sauce",
     "Red tilapia fillet with passion fruit sauce.", "deck"),
    ("CÁ DIÊU HỒNG NƯỚNG GIẤY BẠC", "Red tilapia baked in foil",
     "Red tilapia fillet baked in foil.", "deck"),
    ("TÉP HỒ LAK RAM VỚI KHẾ/ RAM MẶN", "Lak lake shrimp with star fruit",
     "Stir-fried Lak lake shrimp with star fruit.", "deck"),
    ("CHẢ CÁ HỒ LĂK", "Lak lake fishcake",
     "Deep-fried Lak lake fishcake with local herbs and chilli sauce.", "deck"),
    ("BÒ NƯỚNG LÁ LỐT", "Grilled beef in betel leaf",
     "Grilled beef wrapped in wild betel leaf.", "deck"),
    ("HEO NƯỚNG ỐNG TRE ĂN KÈM CƠM LAM", "Charcoal pork in bamboo with sticky rice",
     "Charcoal pork served in bamboo, with bamboo sticky rice.", "deck"),
    ("CÁ LĂNG ƯỚP NGHỆ NƯỚNG LÁ CHUỐI", "Turmeric catfish grilled in banana leaf",
     "Hemibagrus catfish fillet marinated with turmeric, grilled in banana leaf.", "deck"),
    ("SƯỜN NƯỚNG BBQ CƠM LAM", "BBQ pork ribs with bamboo sticky rice",
     "Pork ribs with home-made BBQ sauce, served with bamboo sticky rice.", "deck"),
    ("GÀ ĐỒNG BÀO NƯỚNG DÙNG KÈM CƠM LAM", "M'Nong charcoal chicken with sticky rice",
     "Half a chicken, M'Nong style over charcoal, served with bamboo sticky rice.", "deck"),
    ("VỊT QUAY HỒ LAK SỐT TIÊU ĐEN VÀ MẬT ONG", "Roast duck with black pepper & honey",
     "Duck roasted over hot coals, Lak style, with black pepper and honey sauce.", "deck"),
    ("GÀ NƯỚNG LÁ CHANH", "Grilled chicken with lemon leaf",
     "Half a chicken grilled with lemon leaf.", "deck-variant"),
    ("GÀ CUỘN SẢ NƯỚNG SỐT CAY/ GÀ RAM GỪNG/ GÀ CHIÊN NƯỚC MẮM/ HẤP LÁ CHANH",
     "Half chicken, four ways",
     "Half a chicken: grilled lemongrass roll with chilli sauce, braised with ginger, "
     "fried with fish sauce, or steamed with lemon leaf.", "deck-variant"),
    ("CÁ LĂNG KHO TỘ", "Caramelised Hemibagrus catfish",
     "Caramelised Lak Hemibagrus catfish in claypot.", "deck"),
    ("CÁ BỐNG KHO TIÊU/ CHIÊN GIÒN", "Gobies, caramelised or crispy fried",
     "Gobies caramelised with black pepper, or deep-fried crisp.", "deck-variant"),
    ("CÁ BÔNG LAU KHO TỘ", "Caramelised catfish in claypot",
     "Caramelised catfish in claypot.", "deck"),
    ("TÔM KHO TỘ", "Caramelised shrimp with black pepper",
     "Caramelised shrimp with black pepper.", "deck"),
    ("THỊT HEO KHO TỘ", "Caramelised pork belly",
     "Caramelised pork belly in claypot.", "deck"),
    ("HEO XÀO LĂN", "Stir-fried local pork with lemongrass",
     "Stir-fried local pork with lemongrass.", "deck"),
    ("TRỨNG VỊT HỒ LAK CHIÊN", "Fried duck egg with onion",
     "Lak lake duck egg fried with onion.", "deck"),
    ("TRỨNG VỊT HỒ LAK CHIÊN THỊT BẰM", "Fried duck egg with minced pork",
     "Lak lake duck egg fried with minced pork.", "deck"),
    ("VỊT NẤU CHAO", "Duck in fermented tofu hotpot",
     "Duck simmered with fermented soya cheese and taro.", "inferred"),

    # ------------------------------------------------------- rice and noodles
    ("CƠM TRẮNG", "Steamed rice", "Steamed white rice.", "deck"),
    ("CƠM LAM", "Sticky rice in bamboo", "Sticky rice cooked in a bamboo tube.", "deck"),
    ("MIẾN XÀO NỒI ĐẤT", "Claypot stir-fried vermicelli",
     "Stir-fried glass vermicelli served in a claypot.", "inferred"),
    ("MIẾN XÀO THỊT BÒ", "Stir-fried vermicelli with beef",
     "Stir-fried glass vermicelli with beef and vegetables.", "deck-variant"),
    ("MIẾN XÀO THỊT GÀ", "Stir-fried vermicelli with chicken",
     "Stir-fried glass vermicelli with chicken and vegetables.", "deck-variant"),
    ("MIẾN XÀO HẢI SẢN", "Stir-fried vermicelli with seafood",
     "Stir-fried glass vermicelli with seafood and vegetables.", "deck-variant"),
    ("MIẾN XÀO RAU CỦ", "Stir-fried vermicelli with vegetables",
     "Stir-fried glass vermicelli with vegetables.", "deck-variant"),
    ("MÌ XÀO BÒ", "Stir-fried egg noodles with beef",
     "Stir-fried egg noodles with beef and vegetables.", "deck"),
    ("MÌ XÀO THỊT HEO", "Stir-fried egg noodles with pork",
     "Stir-fried egg noodles with pork and vegetables.", "deck-variant"),
    ("MÌ XÀO THỊT GÀ", "Stir-fried egg noodles with chicken",
     "Stir-fried egg noodles with chicken and vegetables.", "deck-variant"),
    ("MÌ XÀO HẢI SẢN", "Stir-fried egg noodles with seafood",
     "Stir-fried egg noodles with seafood and vegetables.", "deck-variant"),
    ("MÌ XÀO RAU CỦ", "Stir-fried egg noodles with vegetables",
     "Stir-fried egg noodles with vegetables.", "deck"),
    ("CƠM CHIÊN HẢI SẢN HẠT SEN", "Seafood fried rice with lotus seeds",
     "Seafood fried rice with lotus seeds.", "deck"),
    ("CƠM CHIÊN GÀ XÉ HẠT SEN", "Shredded chicken fried rice with lotus seeds",
     "Shredded chicken fried rice with lotus seeds.", "deck-variant"),
    ("CƠM CHIÊN THỊT HEO", "Pork fried rice with lotus seeds",
     "Pork fried rice with lotus seeds.", "deck-variant"),
    ("CƠM CHIÊN THỊT BÒ", "Beef fried rice with lotus seeds",
     "Beef fried rice with lotus seeds.", "deck-variant"),
    ("CƠM CHIÊN RAU CỦ HẠT SEN", "Vegetable fried rice with lotus seeds",
     "Vegetable fried rice with lotus seeds.", "deck"),
    ("MÌ Ý SỐT CÀ CHUA", "Pomodoro spaghetti", "Spaghetti in tomato sauce.", "deck"),
    ("MÌ Ý SỐT BÒ BẰM", "Spaghetti bolognaise", "Spaghetti bolognaise.", "deck"),
    ("BÒ LÚC LẮC KHOAI TÂY CHIÊN", "Wok-fried beef cubes with french fries",
     "Wok-fried beef cubes served with french fries.", "deck"),
    ("CLUB SANDWICH GÀ", "Club sandwich with chicken",
     "Life club sandwich with chicken.", "deck"),
    ("MÌ TÔM NẤU THỊT BÒ", "Instant noodle soup with beef",
     "Instant noodles in broth with beef.", "inferred"),

    # ------------------------------------------------------------------ soups
    ("CANH CHUA CHAY", "Vegetarian sour soup",
     "Sour soup with tofu, tomato, pineapple, okra and bean sprouts.", "deck"),
    ("CANH BÍ ĐỎ ĐẬU PHỘNG", "Pumpkin soup with peanut",
     "Pumpkin soup with peanut.", "deck"),
    ("CANH LAGIM", "Mixed vegetable soup",
     "Soup of pumpkin, carrot, potato and squash.", "deck"),
    ("CANH CẢI THỊT BẰM", "Mustard leaf soup with ground pork",
     "Mustard leaf soup with ground pork.", "deck"),
    ("CANH BÍ ĐAO NẤU THỊT BẰM", "Winter melon soup with ground pork",
     "Winter melon soup with ground pork.", "deck-variant"),
    ("CANH KHỔ QUA NHỒI THỊT", "Bitter melon soup stuffed with pork",
     "Bitter melon stuffed with pork, in clear soup.", "deck"),
    ("CANH GÀ LÁ GIANG", "Chicken soup with sour-sop creeper leaf",
     "Chicken soup with sour-sop creeper leaf.", "deck"),
    ("CANH CHUA CÁ BÔNG LAU", "Sweet and sour catfish soup",
     "Sweet and sour Vietnamese catfish soup.", "deck"),
    ("CANH CÀ ĐẮNG CÁ CƠM", "Wild eggplant soup with anchovies",
     "Wild eggplant soup with anchovies.", "deck"),
    ("CANH CUA TẬP TÀNG", "Garden vegetable soup with field crab",
     "Mixed garden vegetable soup with ground field crab.", "deck"),
    ("CANH TÔM TẬP TÀNG", "Garden vegetable soup with shrimp",
     "Mixed garden vegetable soup with ground shrimp.", "deck"),
    ("CANH SƯỜN HEO NẤU ĐU ĐỦ", "Papaya soup with pork ribs",
     "Green papaya soup with pork ribs.", "deck"),
    ("CANH SƯỜN HEO NẤU MĂNG", "Bamboo shoot soup with pork ribs",
     "Young bamboo shoot soup with pork ribs. Seasonal.", "deck"),
    ("CANH CHẢ CÁ THÁC LÁC NẤU MĂNG", "Sour bamboo shoot soup with fishcake",
     "Sour soup of wild bamboo shoot with featherback fishcake.", "deck-variant"),
    ("CANH CHẢ CÁ NẤU MƯỚP ĐẮNG", "Wild bitter melon soup with fishcake",
     "Wild bitter melon soup with featherback fishcake.", "deck-variant"),
    ("CANH CHUA CÁ LĂNG", "Sweet and sour Hemibagrus catfish soup",
     "Sweet and sour Hemibagrus catfish soup.", "deck"),

    # ---------------------------------------------------------------- hotpots
    ("LẨU NẤU CHAO", "Fermented tofu hotpot",
     "Mixed vegetables with tofu, taro and fermented soya cheese.", "deck"),
    ("LẨU CHAY THẬP CẨM", "Mixed vegetarian hotpot",
     "Hotpot of mixed vegetables, tofu and mushrooms.", "inferred"),
    ("LẨU CÁ LĂNG ĐỒNG NẤU MĂNG CHUA", "Sour catfish & bamboo shoot hotpot",
     "Sweet and sour Vietnamese hotpot with catfish and bamboo shoot.", "deck"),
    ("LẨU CÁ THÁC LÁC NẤU MƯỚP ĐẮNG", "Featherback fishcake & bitter melon hotpot",
     "Wild bitter melon hotpot with featherback fishcake.", "deck-variant"),
    ("LẨU GÀ LÁ GIANG/ LÁ É", "Chicken hotpot with sour leaf or basil",
     "Braised chicken and hot chilli hotpot with sour-sop creeper or basil leaf.", "deck-variant"),

    # ---------------------------------------------------------------- desserts
    ("CHÈ CHUỐI", "Banana sweet custard", "Banana sweet custard.", "deck"),
    ("CHÈ HẠT SEN LONG NHÃN", "Lotus seed & longan sweet custard",
     "Lotus seed and longan sweet custard.", "deck-variant"),
    ("TRÁI CÂY THEO MÙA", "Seasonal fruit platter", "Seasonal fruit platter.", "deck"),
    ("BÁNH CHUỐI NƯỚNG DÙNG KÈM KEM VANILLA", "Baked banana cake with vanilla ice cream",
     "Baked banana cake served with vanilla ice cream.", "deck"),
    ("BÁNH CHUỐI NƯỚNG", "Baked banana cake", "Baked banana cake.", "deck-variant"),
    ("KEM SÔ CÔ LA", "Chocolate ice cream", "Chocolate ice cream.", "deck"),
    ("KEM VANI", "Vanilla ice cream", "Vanilla ice cream.", "deck"),

    # ------------------------------------------------------------- local food
    ("TEMPURA CỦ QUẢ", "Vegetable tempura",
     "Tempura of eggplant, onion, carrot and okra.", "deck"),
    ("BÁNH TÔM HỒ CHIÊN KHOAI LANG", "Lak lake shrimp & sweet potato fritters",
     "Lak lake shrimp fried with sweet potato.", "deck-variant"),
    ("KHOAI LANG CHIÊN", "Sweet potato fries", "Sweet potato fries.", "deck"),
    ("KHOAI TÂY CHIÊN", "French fries", "French fries.", "deck"),

    # -------------------------------------------------------------- set menus
    ("COMBO SET LUNCH 01 245000", "Set Menu 1 (245,000 per person)",
     "Banana flower salad with chicken; Lak lake shrimp with star fruit; sautéed bep "
     "leaves with garlic; chicken soup with sour-sop creeper leaf; steamed rice; "
     "lotus seed and longan sweet custard. Minimum 2 guests.", "combo"),
    ("COMBO SET LUNCH 02 245000", "Set Menu 2 (245,000 per person)",
     "Green papaya salad with pork & shrimp; stir-fried local pork with lemongrass; "
     "fried duck egg with minced pork; wild eggplant soup with anchovies; steamed rice; "
     "banana sweet custard. Minimum 2 guests.", "combo"),
    ("COMBO SET DINNER 01 295000", "Set Menu 3 (295,000 per person)",
     "Wild eggplant salad with dried anchovy; grilled beef in betel leaf; crispy tilapia "
     "with green mango fish sauce; sautéed wild vegetables with garlic; garden vegetable "
     "soup with shrimp; steamed rice; lotus seed and longan sweet custard. "
     "Minimum 2 guests.", "combo"),
    ("COMBO SET DINNER 02 295000", "Set Menu 4 (295,000 per person)",
     "Morning glory salad with Lak lake shrimp; Lak lake fishcake; caramelised pork "
     "belly; steamed wild vegetables with caramelised dip; garden vegetable soup with "
     "field crab; steamed rice; banana sweet custard. Minimum 2 guests.", "combo"),
    ("COMBO SET DINNER 01 375000", "Set Menu 5 (375,000 per person)",
     "Wild eggplant salad with dried anchovy; M'Nong charcoal chicken with bamboo sticky "
     "rice; caramelised gobies with black pepper; steamed wild vegetables with "
     "caramelised dip; sour bamboo shoot soup with featherback fishcake; steamed rice; "
     "lotus seed and longan sweet custard. Minimum 2 guests.", "combo"),
    ("COMBO SET DINNER 02 375000", "Set Menu 6 (375,000 per person)",
     "Morning glory salad with Lak lake shrimp; charcoal pork in bamboo with sticky "
     "rice; chicken hotpot with sour-sop creeper leaf; banana sweet custard. "
     "Minimum 2 guests.", "combo"),
    ("COMBO SET DINNER 01 455000", "Set Menu 7 (455,000 per person)",
     "Y Lak appetiser platter; M'Nong charcoal chicken with bamboo sticky rice; sour "
     "catfish and bamboo shoot hotpot; fruit yogurt. Minimum 2 guests.", "combo"),
    ("COMBO SET DINNER 02 455000", "Set Menu 8 (455,000 per person)",
     "Y Lak appetiser platter; roast duck with black pepper and honey; wild bitter melon "
     "hotpot with featherback fishcake; seasonal fruit platter. Minimum 2 guests.", "combo"),
    # The deck prints these two on its VEGETARIAN page, but neither combo is
    # vegetarian as it stands on prod: set 1 serves RAU CỦ XÀO THẬP CẨM, which
    # the deck itself describes as sautéed with oyster sauce, and set 2 serves
    # the SHRIMP morning-glory salad where the deck lists the tofu one. A
    # dietary claim that is wrong is worse than no claim, and the Vietnamese
    # name never made one, so neither does the English. Owner to decide whether
    # the courses or the deck are what is wrong.
    ("COMBO SET MENU 01 195000", "Set Menu 1 (195,000 per person)",
     "Lettuce rolls and corn fritters; vegetarian spring rolls; caramelised eggplant in "
     "claypot; sautéed mixed vegetables with oyster sauce; pumpkin soup with peanut; "
     "lotus seed and longan sweet custard. Minimum 2 guests.", "combo"),
    ("COMBO SET MENU 02 195000", "Set Menu 2 (195,000 per person)",
     "Morning glory salad with Lak lake shrimp; caramelised mushrooms in claypot; "
     "charcoal eggplant with spring onion oil; sautéed green beans with garlic; "
     "vegetarian sour soup; banana sweet custard. Minimum 2 guests.", "combo"),
    # Every course here is chay, so the label is safe.
    ("COMBO SET MENU 01 255000", "Vegetarian Set Menu 3 (255,000 per person)",
     "Young jackfruit salad; fried tofu with lemongrass; caramelised mushrooms in "
     "claypot. Minimum 2 guests.", "combo"),
    ("COMBO SET MENU 02 255000", "Vegetarian Set Menu 4 (255,000 per person)",
     "Vegetarian appetiser platter; mixed vegetarian hotpot. Minimum 2 guests.", "combo"),

    # Courses that only ever appear INSIDE a combo -- unpriced, so hidden from
    # the till grid, but the guest still reads them on the combo choice screen.
    ("CANH CÁ THÁC LÁC MĂNG CHUA", "Sour bamboo shoot soup with fishcake",
     "Sour soup of wild bamboo shoot with featherback fishcake.", "deck-variant"),
    ("LẨU CÁ THÁC LÁC MƯỚP ĐẮNG RỪNG", "Featherback fishcake & wild bitter melon hotpot",
     "Wild bitter melon hotpot with featherback fishcake.", "deck-variant"),
    ("ĐẬU COVE XÀO TỎI", "Sautéed green beans with garlic",
     "Cove beans sautéed with garlic.", "deck-variant"),
    ("SỮA CHUA", "Fruit yogurt", "Yogurt with seasonal fruit.", "deck-variant"),

    # ------------------------------------------------------------------ other
    ("BUFFET / PAX (CHƯA CÓ GIÁ)", "Buffet per person (price to be confirmed)",
     "Buffet, charged per person. Price not yet set.", "inferred"),
    ("KHÁCH THAM QUAN", "Day visitor charge",
     "Entrance charge for a day visitor.", "inferred"),

    # ------------------------------------------------- soft drinks and coffee
    ("CÀ PHÊ ĐEN", "Vietnamese black coffee", "Vietnamese drip black coffee.", "inferred"),
    ("CÀ PHÊ SỮA", "Vietnamese coffee with condensed milk",
     "Vietnamese drip coffee with condensed milk.", "inferred"),
    ("CACAO SỮA", "Cocoa with milk", "Hot cocoa made with milk.", "inferred"),
    ("TRÀ XANH", "Green tea", "Pot of green tea.", "inferred"),
    ("TRÀ ĐÁ", "Iced tea", "Glass of iced tea.", "inferred"),
    ("TRÀ SẢ GỪNG MẬT ONG", "Lemongrass, ginger & honey tea",
     "Hot tea of lemongrass, ginger and honey.", "inferred"),
    ("NƯỚC SUỐI", "Still water", "Bottled still water.", "inferred"),
    ("NƯỚC SUỐI 1,5LIT", "Still water 1.5 L", "Bottled still water, 1.5 litre.", "inferred"),
    ("NƯỚC SODA", "Soda water", "Soda water.", "inferred"),
    ("NƯỚC TONIC", "Tonic water", "Tonic water.", "inferred"),
    ("PEPSI", None, "Pepsi cola.", "inferred"),
    ("PEPSI ZERO", None, "Pepsi Zero, sugar free.", "inferred"),
    ("MIRINDA", None, "Mirinda orange soft drink.", "inferred"),
    ("7UP", None, "7Up lemon-lime soft drink.", "inferred"),

    # ------------------------------------------------- juices and smoothies
    ("NƯỚC CAM", "Fresh orange juice", "Freshly squeezed orange juice.", "inferred"),
    ("NƯỚC CHANH", "Fresh lime juice", "Freshly squeezed lime juice.", "inferred"),
    ("NƯỚC THƠM", "Pineapple juice", "Freshly pressed pineapple juice.", "inferred"),
    ("NƯỚC DƯA HẤU", "Watermelon juice", "Freshly pressed watermelon juice.", "inferred"),
    ("NƯỚC CÀ RỐT", "Carrot juice", "Freshly pressed carrot juice.", "inferred"),
    ("NƯỚC CHANH DÂY", "Passion fruit juice", "Fresh passion fruit juice.", "inferred"),
    ("NƯỚC CAM CÀ RỐT", "Orange & carrot juice",
     "Freshly pressed orange and carrot juice.", "inferred"),
    ("NƯỚC CAM CHANH DÂY", "Orange & passion fruit juice",
     "Freshly pressed orange and passion fruit juice.", "inferred"),
    ("NƯỚC CAM THƠM", "Orange & pineapple juice",
     "Freshly pressed orange and pineapple juice.", "inferred"),
    ("NƯỚC THƠM CHANH DÂY", "Pineapple & passion fruit juice",
     "Freshly pressed pineapple and passion fruit juice.", "inferred"),
    ("SINH TỐ BƠ", "Avocado smoothie", "Avocado smoothie.", "inferred"),
    ("SINH TỐ CHUỐI", "Banana smoothie", "Banana smoothie.", "inferred"),
    ("SINH TỐ CÀ CHUA", "Tomato smoothie", "Tomato smoothie.", "inferred"),
    ("SINH TỐ CHANH DÂY", "Passion fruit smoothie", "Passion fruit smoothie.", "inferred"),

    # ------------------------------------------------------ beer, spirits, bar
    ("BIA SAIGON", "Saigon beer", "Saigon lager.", "inferred"),
    ("BIA LAURE", "Larue beer", "Larue lager.", "inferred"),
    ("RƯỢU ỔI", "Guava liquor", "House guava liquor.", "inferred"),
    ("RƯỢU NẾP CẨM", "Black sticky rice wine", "House black sticky rice wine.", "inferred"),
    ("BACARDI", None, "Bacardi white rum.", "inferred"),
    ("SMINOFF VODKA", None, "Smirnoff vodka.", "inferred"),
    ("GORDON GIN", None, "Gordon's London dry gin.", "inferred"),
    ("TEQUILA", None, "Tequila.", "inferred"),
    ("BAILEY", None, "Baileys Irish cream liqueur.", "inferred"),
    ("KAHKUA", None, "Kahlúa coffee liqueur.", "inferred"),
    ("COINTREAU", None, "Cointreau orange liqueur.", "inferred"),
    ("REMY MARTIN", None, "Rémy Martin cognac.", "inferred"),
    ("B52", None, "B52 layered shot: coffee liqueur, Irish cream and orange liqueur.",
     "inferred"),
    ("MARGARITA", None, "Margarita: tequila, orange liqueur and lime.", "inferred"),
    ("MOJITO", None, "Mojito: white rum, lime, mint and soda.", "inferred"),
    ("TEQUILA SINRISE", None, "Tequila sunrise: tequila, orange juice and grenadine.",
     "inferred"),
    ("DAIQUIRI", None, "Daiquiri: white rum, lime and sugar.", "inferred"),
    ("LAKTINI", None, "Laktini, the house signature cocktail.", "inferred"),
    ("PASSIONATE VODKA", None, "Vodka with fresh passion fruit.", "inferred"),
    ("PASSIONFRUITJITO", None, "Passion fruit mojito: white rum, passion fruit, mint "
     "and soda.", "inferred"),
    ("VIRGIN SUNRISE", None, "Virgin sunrise: orange juice and grenadine, alcohol free.",
     "inferred"),

    # -------------------------------------------------------------------- wine
    ("VANG LY ( ĐỎ)", "Red wine by the glass", "House red wine, by the glass.", "inferred"),
    ("VANG LY ( TRẮNG)", "White wine by the glass",
     "House white wine, by the glass.", "inferred"),
    ("VANG DALAT ( ĐỎ)", "Dalat red wine (bottle)",
     "Dalat red wine, Vietnam. Bottle.", "inferred"),
    ("VANG DALAT ( TRẮNG)", "Dalat white wine (bottle)",
     "Dalat white wine, Vietnam. Bottle.", "inferred"),
    ("POL REMY DEMI ( SPARLING WINE - FRANCE)", None,
     "Demi-sec sparkling wine, France. Bottle.", "inferred"),
    ("CHATEAU FONCROSE CABERNET SAUVIGNON", None,
     "Cabernet Sauvignon red wine, France. Bottle.", "inferred"),
    ("CHATEAU FONCROSE SAUVIGNON BLANC", None,
     "Sauvignon Blanc white wine, France. Bottle.", "inferred"),
    ("TARAPACA COSHECHA CABERNET SAUVIGNON", None,
     "Cabernet Sauvignon red wine, Chile. Bottle.", "inferred"),
    ("TARAPACA COSHECHA SAUVIGNON BLANC", None,
     "Sauvignon Blanc white wine, Chile. Bottle.", "inferred"),

    # ------------------------------------------------------------------ retail
    ("MẬT ONG", "Honey", "Jar of local honey, to take away.", "inferred"),
    ("BỘT CACAO", "Cocoa powder", "Pack of local cocoa powder, to take away.", "inferred"),
    ("CÀ PHÊ BỘT", "Ground coffee", "Pack of local ground coffee, to take away.", "inferred"),
]

# Fast lookup, and a guard: a duplicated Vietnamese key would silently make the
# second entry unreachable.
BY_VN = {}
for _vn, _en, _desc, _src in ENGLISH:
    if _vn in BY_VN:
        raise RuntimeError("duplicate Vietnamese key in ENGLISH: %r" % _vn)
    BY_VN[_vn] = (_en, _desc, _src)
