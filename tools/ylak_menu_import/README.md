# Y Lak menu, recipes and stock → Odoo

Loads the Y Lak restaurant's à-la-carte menu, set menus, buffet and all seven
department stock-counts into `hotel_pms_test`, from the owner's workbooks.

**There is no production target, deliberately.** `run.sh` only ever talks to
the test server. The buffet and 34 dishes are still unpriced, and two buffet
ingredients have contradictory source figures — see *Still open* below. Putting
a 0 VND product on a live till is worse than not having the button.

```bash
./run.sh extract              # offline: sources/*.md -> *.json
./run.sh load [host]          # push and load
./run.sh verify [host]        # 29 read-only assertions, non-zero on failure
./run.sh smoke  [host]        # ring a POS order, assert kits explode, roll back
```

## The shape of it

Extraction is offline and produces reviewable JSON; loading reads only that
JSON. So a source change shows up as a JSON diff you can read in a pull
request before anything touches a database.

```
sources/cost_of_places_rvd.md ──> extract_menu.py       ──> menu_data.json
sources/extra_cost.md         ──> extract_extra.py      ──┘ (merges IN)
                              ┌─> extract_sets.py       ──> sets_data.json
sources/cost_of_places_rvd.md ┘
sources/kho_no_duplicate.md   ──> extract_inventory.py  ──> inventory_data.json

load_00_precision.py   decimal precision + groups   (own process, exits 2)
load_10_catalog.py     UoM, categories, products, kit BoMs
load_20_sets.py        set combos, buffet, visitor charge
load_30_inventory.py   7 stock locations + opening count
load_40_orderpoints.py reorder rules -- no-op until the owner fills the CSV
load_15_prune.py       archives what the extracts no longer produce  <- LAST
```

The numbering is historical; **`run.sh` is the authority on run order**, and
prune runs last despite its number.

## What ends up in Odoo

| | |
|---|---|
| Dishes | 135, of which 100 priced and visible in POS |
| Kit BoMs | 135 dish + 1 buffet, all `type='phantom'` |
| Set menus | 12 POS combos |
| Wine & retail goods | 5 bottles + 3 packs, own product/POS categories |
| Ingredients + stock items | ~1,180 products across 7 store categories |
| Stock locations | 7 internal children of `WH/Stock` |
| Opening count | 1,081 quant lines, dated 24/08/2026 |

Set menus are **POS combos**, not nested kit BoMs. Both deduct stock
correctly, but a combo puts each course on the ticket as its own order line,
so the six dishes reach the kitchen display; a nested kit prints one opaque
`SET LUNCH` line. A choice holding exactly one item auto-confirms, so a fixed
set is still one tap for the cashier.

### Set naming, and why one combo is not one choice

The owner's format (30 Aug 2026) is `COMBO SET LUNCH 01 245000` — course type,
set number zero-padded, price with no separators. Every course choice is
prefixed with it, so a single search returns the set and all of its courses:

```
COMBO SET LUNCH 01 245000                        245,000
  COMBO SET LUNCH 01 245000 — GỎI GÀ HOA CHUỐI
  COMBO SET LUNCH 01 245000 — TÉP HỒ LAK RAM VỚI KHẾ/ RAM MẶN
  ... four more, all always served
```

**A `product.combo` is a choice point, not a container.** It has no quantity
field, its item field is labelled "Options", and the cashier takes exactly one
item from each. So a fixed six-course set is six choices of one item each —
which is why all six are served, no configurator appears, and a sale deducts
all six dishes. Collapsing them into one combo of six items would turn the set
into "pick one dish for 245,000" and deduct only that dish. The owner confirmed
all six are served.

**The external id deliberately did NOT change.** `slug()` is meant to be fed a
stable source string; feeding it the display name means a rename mints a fresh
id, orphans the existing product and has the prune archive it — losing the
link, the order history, and the prune's keep-list, which derives from the same
formula. `legacy_key()` keeps the old string as the id and only the label
changes. `verify.py` checks the label separately, because every other check
resolves by id and would pass on a set still carrying its old name.

The 2-pax minimum used to live in the product name and has no field in Odoo.
The owner's format has no room for it, so it moved to `description_sale`
("Tối thiểu 2 khách.") rather than being dropped.

## Traps, each of which cost a debugging session

**Decimal precision is cached per process.** `Product Unit` must be ≥ 3 digits
before any BoM line is written, and nine recipe lines carry `0.075`. Bumping
the precision and writing BoM lines in the *same* shell process stores `0.08`.
`load_00_precision.py` therefore runs alone and exits 2 when it changed
anything; `run.sh` restarts Odoo and starts over. Every other loader calls
`require_precision()` and hard-aborts rather than warning.

**`slug()` is not `norm()`.** `norm()` drops parenthesised text so aliases
match loosely. The stock counts rely on exactly that text to tell items
apart — `Máy sưởi` from `Máy sưởi (máy khử khuẩn)` — so `slug()` keeps it.
Building `slug()` on `norm()` gave four pairs of distinct products the same
external id and the second of each pair overwrote the first.

**`env.ref()` resolves archived records.** So does a name search. Every
"exists" check stayed green while the buffet and 17 of its ingredients sat
archived. `get_or_create()` now revives an archived record it was asked for,
and `verify.py` asserts that nothing the extract still wants is archived.

**Prune must run last.** It archives every `__ylak__` id the extracts do not
account for, so every creating step has to have run first. Run early, it
archived the sets and buffet, and — because the loaders' diff-only write never
touches `active` — nothing brought them back on the next pass.

**Inventory idempotency is by outcome, not by reference.** The
`inventory_name` context key does not survive onto `stock.move.reference`;
Odoo stamps its own "Product Quantity Confirmed". A reference-based key
matched nothing and re-applied every row on each run. Each row is now compared
to the quantity on hand and skipped when it agrees.

**`product.template` with `type='combo'` cannot exist without a choice.**
`_check_combo_ids_not_empty` fires during `create()`, so the `product.combo`
records are built before the template, not after.

**`uom.uom.relative_factor` is unwritable once products with that unit have
moved**, and re-sending the identical value still triggers the refusal. Hence
`get_or_create(..., create_only=True)` for units, and a diff-only write
everywhere else.

**`pos.config.limit_categories`** hides new POS categories until they are
added to `iface_available_categ_ids`. Done in `load_20_sets.py`; `verify.py`
checks it.

**Paying a POS order moves no stock.** `_process_saved_order()` calls
`action_pos_order_paid()` and *then* `_create_order_picking()`; calling only
the first leaves no picking and no moves, which reads exactly like a kit BoM
that does not explode. `smoke_pos.py` calls both. (Only when the company is on
real-time stock — `point_of_sale_update_stock_quantities = 'real'`, which this
one is. Set to `closing`, the moves appear at session close instead.)

**Product names are case-sensitive, and the sources disagree about case.**
The stock count holds `Ống cơm lam`, `Khoai tây Siêu Thị`, `Cá Lăng`; the
recipe sheets write `ỐNG CƠM LAM`, `Khoai tây siêu thị`, `Cá lăng`. Nine goods
therefore existed twice — the counted copy holding the 30 bamboo tubes and
never moving, and the recipe copy that every BoM line actually deducts sitting
at zero and going negative on the first sale. (An archived twin still shows
`-1` in `WH/Stock` against `+1` in `Customers`: the defect had already
happened.) `extract_extra.py` canonicalises every recipe name to the **stock
count's** spelling — that is what the storekeeper counts and where the quant
lives — and `load_10_catalog.py` repoints the `ing_` external id at the counted
product and archives the twin. `verify.py` asserts no good exists as both.

**Flushing before clearing the registry cache is not optional.** That merge
has to clear the xmlid cache, or `env.ref()` keeps returning the archived twin
and `get_or_create` revives it. But `env.registry.clear_cache()` also
**discards pending ORM writes**, so without `env.flush_all()` first, the
repoint and the archive are thrown away — and the run still prints a cheerful
"7 merged" having changed nothing, every single time.

**A raw good must never carry a kit BoM.** The duck egg
`TRỨNG VỊT HỒ LAK CHIÊN THỊT BẰM` shares its name with the dish, so before
`RENAME_INGREDIENT` existed they were one product; the dish's BoM was written
onto it and stayed on the *ingredient* when the rename split the two. It listed
itself as a component, so selling the dish exploded into a kit that exploded
into itself and the egg was never deducted at all. `load_10_catalog.py`
archives any BoM found on a raw good; `verify.py` asserts there are none.

**A differing unit label is not by itself a conflict.** The buffet sheet writes
"Kg" against 25 `Trứng gà` for 20 pax at 3,996 each — plainly 25 eggs, and the
product's per-`Trái` cost matches to the đồng. The check fires only when the
unit *and* the price of one unit both disagree.

**`uom.uom.rounding` is computed in Odoo 19** — all units share the global
`Product Unit` precision — so it is never set per unit.

## Re-running

The whole chain is idempotent. Proven by running `./run.sh load` three times
and comparing, on top of `./run.sh verify`:

```
products 1333 | boms 136 | bom lines 673 | combos 65 | combo items 72
quants 1822 | stock moves 2593 | orderpoints 0 | __ylak__ xmlids 1588
```

`stock_move` is the count that matters: unchanged means no second inventory
adjustment was written. (Combos exceed combo items by 6 because Odoo's three
POS demo combos — Burgers, Sushi, Drinks — hold 2, 4 and 4 items; the 62 Y Lak
ones hold exactly one course each.)

Idempotency rests on external ids in the `__ylak__` namespace, derived from
the **source spreadsheet name**, never from the record's current name in Odoo —
so the owner can rename a dish in the UI and the next load still finds it.
Renaming it *in the spreadsheet* creates a second product; the extractor
reports are the guard.

Nothing is ever deleted. `load_15_prune.py` archives, so stock moves, past
orders and history stay intact and the owner can restore anything from the
product list by filtering on Archived.

The prune can only see records carrying a `__ylak__` id, so a product from the
first import that lost its id is invisible to it — `Canh Tập Tàng`, a live
150,000 VND POS button from the superseded 73-dish version, was exactly that.
It is named in the prune's `ORPHANS` set rather than caught by a rule, because
an unowned product is not this toolchain's to retire and any rule loose enough
to catch it also catches Odoo's demo data. Everything else sellable that the
toolchain does not own is **reported and left alone** — 26 Odoo POS demo
products (Bacon Burger, Sushi Lunch Combo), which the owner should retire
before the till goes live.

## The `extra Cost_ingredients` sheet (30 Aug 2026)

The owner added a second costing sheet after the first load. It carries
**selling prices**, which is most of what it supplies, and it closed three
things that were blocking:

- **25 new products** — 16 à-la-carte dishes (miến/mì/cơm chiên variants,
  LẨU NẤU CHAO, GỎI NGÓ SEN TÔM THỊT, CƠM LAM, CÁ BÔNG LAU KHO TỘ, the two
  fried potatoes), 5 wines, 3 packaged retail goods, and green tea.
- **2 existing dishes got their price** — CACAO SỮA and
  TRỨNG VỊT HỒ LAK CHIÊN THỊT BẰM, both 45,000.
- **The 12th set menu** — see below.

It merges into `menu_data.json` rather than writing a sibling file, and that
is load-bearing rather than tidy: `load_15_prune.py` builds its keep-list from
`MENU["dishes"]`, so anything in a separate file would be archived on the next
prune, and the dish/BoM/price/cost-reconciliation checks in `verify.py` would
silently stop covering it.

### Three blocks were not new dishes

Checked against the loaded data, not guessed from the name. Creating any of
them fresh would have put a second button on the till for a dish already
there:

| Sheet block | Is really | Evidence |
|---|---|---|
| `KHAI VỊ CHAY` | `KHAI VỊ CHAY HỒ LAK`, already 185,000 | the menu deck spells it the short way |
| `TRỨNG VỊT HỒ LAK CHIÊN` | `TRỨNG VỊT HỒ LAK CHIÊN THỊT BẰM` | the block's only component carries the **long** name at 2,484/quả — it is the duck egg, and the existing ingredient sits at 2,732 = 2,484 × 1.10 |
| `CACAO` | `CACAO SỮA` | the recipe contains `Sữa tươi`, so it is the milk cocoa; the deck has no cocoa line at all |

All three also carry a **different recipe** from the established one. The
established recipe was kept and the difference printed: rewriting it would
change what a sale deducts from stock, silently, from a sheet whose
quantities disagree with the one already loaded. Listed under *Still open*.

### Ingredient costs: fill zeros, otherwise keep the older figure

A product carries one cost, so a figure written here changes the
`standard_cost` of every existing dish using it. The rule is deterministic —
fill a missing or zero cost, otherwise keep what `menu_data.json` already has
— which is why all 135 dishes still reconcile against their own BoM
explosion. Six ingredients disagree between the sheets (and `Bánh phồng tôm`
and `Rau muống` disagree *within* the new sheet); every one is printed on
each run.

### The 12th set menu is now built

`CUỐN DIẾP & RAM BẮP` appears in the new sheet with **no selling price** and
`trong set menu` ("in the set menu") written in its own header row, and it is
entirely vegetarian. Read as the missing `CUỐN DIẾP CHAY` recipe — the one
course that was holding back the 195,000 vegetarian SET 1 — via a
`COURSE_ALIASES` entry in `extract_sets.py`. **Flagged for the owner** in
case it is a different dish; it is the only inference in the merge.

## Still open — owner input needed

1. **Buffet selling price.** Cost is **177,666 VND/pax** — the BoM explosion,
   which is what `pos_mrp` reports as COGS. The buffet sheet's own total comes
   to 130,194 (118,358 + 10%); the 47,472 gap is items 2 and 3 below. The
   product is on the till at 0 VND named `BUFFET / PAX (CHƯA CÓ GIÁ)` so a
   0 VND ring-up on test is self-evidently wrong rather than quietly
   plausible. Do not carry it to production until it is priced.
2. **`Sandwich` — is the buffet's 3 for 20 pax loaves or slices?** The buffet
   sheet says 68,680 per `Cây` (loaf); the recipe sheet says 6,868 per `miếng`
   (slice). Exactly 10×, so 10 slices to a loaf is nearly certain — but then
   the sheet's 0.15/pax means 1.5 slices, not 0.15. Loaded as 0.15 `miếng`
   pending confirmation, which under-costs and under-deducts it.
3. **`Sữa chua` — one of the two prices is wrong.** The buffet sheet says
   6,763 per Kg; the recipe sheet says 84,334 per `hủ` (pot). No conversion
   reconciles those. Loaded at the recipe figure, which is what pushes the
   buffet cost up; if 84,334 is the error, the buffet cost drops by ~57,700.
4. **Price for `LẨU CHAY THẬP CẨM`** — a new dish the owner added, absent from
   the menu deck. (Its recipe is loaded; only the price is missing.)
5. **Are the 5 wines and 3 retail packs meant for the restaurant till?** They
   are loaded into their own `Rượu vang` / `Hàng bán lẻ` product and POS
   categories rather than sitting among the food.
6. **Confirm `CUỐN DIẾP & RAM BẮP` is the `CUỐN DIẾP CHAY` course** of the
   195,000 vegetarian set. The 12th set is built on that reading.
7. **Three recipes now disagree between the two sheets.** The established one
   was kept in each case; the new sheet says: `KHAI VỊ CHAY HỒ LAK` đậu khuôn
   1.5 not 1.0, rau muống 1 bó not 0.1, bắp trái 0.1 not 0.3, and no cà rốt
   bếp; `CACAO SỮA` sugar instead of condensed milk; `TRỨNG VỊT HỒ LAK CHIÊN`
   without the minced pork. Which is current?
8. **Prices for the remaining 34.** Still mostly the bar: the fresh juices
   (nước cam, chanh dây, dưa hấu, cà rốt), CÀ PHÊ ĐEN/SỮA, TRÀ GỪNG MẬT ONG,
   SỮA CHUA, KEM CHOCOLATE — the new sheet priced green tea and cocoa but not
   these — plus a dozen canh/lẩu and LẨU CHAY THẬP CẨM. They switch themselves
   on as soon as a price arrives and this runs again.
9. **Buồng phòng is a store the owner never named.** The data contains
   `CÔNG CỤ DỤNG CỤ BUỒNG PHÒNG` (140 housekeeping items), so it was given its
   own location. It is the one structural decision taken without them.
10. **Souvenirs (Lễ tân, 13 items) are saleable goods**, not equipment. They
   could be POS products in their own right. Out of scope here.

Also outstanding, and not owner input: **26 Odoo POS demo products** (Sushi
Lunch Combo, Pasta Bolognese) should be archived before real use — the prune
lists them on every run. What remains
untested is the till *interface* — that a SET LUNCH rings at 245,000 rather
than 490,000 and raises no configurator popup. The stock half is proven; see
below.

## Replenishment

Following works: every item is counted in its store. **Refilling needs minimum
levels, and no workbook contains one** — every sheet is a single count dated
24/08/2026, with no min/max, no reorder quantity and no supplier lead time.
Nothing here guesses one.

What is provided is `reorder_levels.csv`, generated by `make_reorder_csv.py`:
all 1,081 items with store, unit and current count, `min` and `max` blank,
sorted by store then descending count so the fast-moving goods are at the top
of each section. The owner fills in only the lines they care about — the ~80
kitchen consumables that actually run out, not the 168 dinner plates — and
`load_40_orderpoints.py` turns filled rows into `stock.warehouse.orderpoint`
records. Blank rows get no orderpoint, so a half-filled file is a valid file.
Emptying a row later deletes the rule: an orderpoint is a live instruction to
buy, not a record of anything, so a stale one keeps ordering.

333 of the 1,081 are consumables; the other 748 are equipment, in their own
category so they never enter a reorder report.

**The copy in this directory is the file of record.** `run.sh push` extracts
`*.csv` over `/opt/ylak/`, so a copy filled in on the server is overwritten by
the repo's on the next `./run.sh load`. Fill in the repo copy and commit it.
Regenerating is safe — `make_reorder_csv.py` reads existing levels back and
carries them forward, and keeps (flagged, at the end) any level whose product
has left the inventory, which is what a rename upstream looks like.

Rules are created with **`trigger = 'manual'`**, not Odoo's `auto` default,
because `purchase` is not installed here: an auto rule has nothing to
replenish with, so the nightly scheduler would raise a procurement exception
per rule and buy nothing. Manual rules instead appear in **Inventory →
Operations → Replenishment** with a suggested order quantity — a shopping
list. Install `purchase` and they can be switched to `auto` to raise real POs.

All four paths are exercised, not just the parse: two scratch rows were
loaded (one kitchen consumable, one housekeeping item), confirmed against the
right sub-location and warehouse, re-run twice with no change, updated, then
blanked out and confirmed to delete both the rule and its `ir.model.data` row.

## Kit explosion on a POS sale — confirmed

The one load-bearing assumption, and nobody had ever checked it, including for
the 73 BoMs of the first import. `./run.sh smoke` sells the most complex dish
in the catalogue (`KHAI VỊ Y LAK`, 12 component lines) and one 6-course set,
then asserts the stock moves land on the **raw ingredients** and that neither
the dish nor any course product is itself moved. Both pass. It rolls the
session back, so it leaves nothing behind and can be run any time.

Sets are combos rather than nested kits, so course lines explode individually
and the SET → dish → ingredient recursion question never arises.

## Files

| Path | |
|---|---|
| `run.sh` | entry point; owns the run order |
| `ylak_common.py` | xmlid plumbing, `get_or_create`, precision guard |
| `extract_menu.py` | recipes + prices → `menu_data.json` |
| `extract_extra.py` | the later `extra Cost_ingredients` sheet, merged in |
| `extract_sets.py` | set menus + buffet → `sets_data.json` |
| `extract_inventory.py` | 10 department tables → `inventory_data.json` |
| `mapping.py` | `RVD_ALIASES`, `AMBIGUOUS` — hand-checked name mappings |
| `deck_prices.py` | menu deck prices, transcribed |
| `extract.py` | superseded extractor, kept only for its 45 `ALIASES` |
| `backfill_xmlids.py` | one-off: stamped `__ylak__` ids onto the first import |
| `verify.py` | 29 assertions |
| `smoke_pos.py` | sells a dish and a set, asserts kits explode, rolls back |
| `make_reorder_csv.py` | generates `reorder_levels.csv` for the owner |
| `load_40_orderpoints.py` | reads it back into reorder rules |
| `sources/README.md` | sheet offsets and provenance |

## Production (deployed 01 Sep 2026)

`./run.sh <cmd> prod` targets `14.225.192.16` / `hotel_db`. What differs from
test, and why each difference bit:

* **Restart is `systemctl restart odoo`.** Prod runs under a systemd unit; test
  has none. The old restart branch was hardcoded to test's `fuser -k 8075` +
  `nohup`, which on prod kills nothing (Odoo is on 8069) and then starts a
  SECOND worker set beside the live one -- two cron runners against live books.
* **`odoo-bin` is `/opt/odoo/odoo/odoo-bin`**, not test's `/opt/odoo/odoo-bin`.
* **`smoke` is refused on prod** -- it writes real POS orders. Test carries the
  same module set (`mrp`, `pos_mrp`, `stock_account`, `hotel_pos_folio`), so
  the kit-explosion proof transfers.
* **The warehouse is resolved by code `WH`.** Prod has two warehouses, `WH`
  ("Bảo Trì-Maintenance") and `HK` ("Housekeeping"); the old
  `search([], limit=1)` would have let an arbitrary row decide where 1,081
  counted items live. Override with `YLAK_WAREHOUSE`.
* **The 8% VAT is resolved by shape, not by name.** Test calls it `VAT 8%`;
  prod runs the VN TT200 chart where `l10n_vn` calls it `8%`. Both are 8% sale
  tax-included. External id wins, then name, then shape -- and it refuses to
  guess when more than one active 8% sale tax matches, rather than silently
  taxing the menu wrong. The TT200 migration left archived 8% leftovers behind,
  which is why the shape search filters on `active`.

### `prod_05_purge.py` -- run ONCE, before the first load

Prod carried 34 hand-keyed POS products (`Gỏi gà hoa chuối`) that are the same
dishes this toolchain imports in the workbook's caps (`GỎI GÀ HOA CHUỐI`). Odoo
names are case-sensitive, so loading on top gives every dish twice -- once with
a kit BoM that deducts stock, once without. The prune cannot help: those
products carry no `__ylak__` id, and an unowned product is not ours to retire.

It **refuses to run once any product carries a `__ylak__` id**, because after
`load_10` the whole menu is `available_in_pos` and a second run would delete
exactly what the first made room for. Verified: it correctly refused on test,
which holds 1,312 such products.

### `load_25_valuation_gate.py` -- between steps 20 and 30

`load_30` applies a 1,081-line inventory adjustment. With `stock_account`
installed, a category valued `real_time` posts a journal entry per line into
the live TT200 books, and there is no clean undo. `load_10` deliberately leaves
`property_valuation` unset so categories inherit the database default, which on
`hotel_db` resolves to `periodic` -- but "inherits a safe default" is a claim
about configuration that can change without touching this code. The gate reads
the effective value on all 17 owned categories and exits 3 before step 30.

### Prod baseline after the first load

    products 1303 | in POS 114 | boms 136 | quants 1780 | __ylak__ xmlids 1578
    combos 62 | precision 3 | account_move 70 (unchanged -- no valuation entries)

Lower than test's counts because test also carries Odoo demo data, the
superseded first import, and 10 archived duplicate twins. The check that
matters is name parity: **1,302 active imported products on both, zero
differences in either direction.**

### Purchase installed on prod (01 Sep 2026)

`purchase` was installed on `hotel_db` so the Replenishment screen can raise
real POs. It pulled in `purchase_stock`, `purchase_mrp` and
`purchase_edi_ubl_bis3`; `sale_purchase` stayed out because `sale` is not
installed. The **Buy** route now exists and both warehouses have
`buy_to_resupply`. The purchase journal (`BILL`) already existed from the TT200
chart, and 27 vendors were already on file from the input-invoice module.

Install method: `systemctl stop odoo` → `odoo-bin -c /etc/odoo.conf -d hotel_db
-i purchase --stop-after-init` → `systemctl start odoo`. About 25 seconds of
downtime. Do NOT install by starting a second process while the service runs.

**Reorder rules still load as `trigger='manual'`**, for a reason that survived
the install: auto procurement needs a vendor on the product, and
`product.supplierinfo` is empty (0 seller lines). An auto rule with no seller
raises a procurement exception per orderpoint, nightly, and buys nothing. Once
products carry vendors, load with `YLAK_ORDERPOINT_TRIGGER=auto`.

## English on the POS (04 Sep 2026)

`./run.sh english [test|prod]` runs `load_50_english.py`, which turns every
till button bilingual — `GỎI GÀ HOA CHUỐI / Banana flower salad with chicken` —
and fills `description_sale` with the English line from the owner's menu deck.
The full-load path runs it automatically, last, after `load_15_prune.py`.

The table is `english_names.py`, 194 hand-checked rows keyed on the product's
**exact** Vietnamese name as it stands on prod (doubled space in
`GỎI  BÒ BÓP THẤU`, spaced parens in `VANG DALAT ( ĐỎ)` and all). Every row
carries a `source`: `deck` / `deck-variant` / `combo` / `inferred`.
`english_review.csv` is the same table flattened for the owner to read.

Facts worth not rediscovering:

- **Translations are not an option on this database.** Every product name lives
  in the `en_US` jsonb key and all nine users are `en_US`, so an `en_US`
  translation would replace the Vietnamese for the kitchen and a `vi_VN` one
  would be seen by nobody. The name is also the only field POS renders on the
  button and on the receipt, which is why the English goes there.
- **It must run after `load_10_catalog.py`**, which writes `name` from
  `menu_data.json` on every dish it owns and would otherwise strip the English
  half back off. `slug()` reads the *source* name from the JSON, not the
  record's name, so the bilingual rename does not move any external id.
- **Scope is the till, not the catalogue.** Matching by name across all
  products collides with the kitchen ingredients — `SỮA CHUA` is both a buffet
  ingredient and a set-menu course. Only `available_in_pos` products and the
  courses reachable through a POS combo are touched.
- **Idempotent**: a product is found under either its bare Vietnamese name or
  the bilingual name a previous run gave it, and the English half is recomputed
  rather than appended. The owner's own `description_sale` (the combos'
  `Tối thiểu 2 khách.`) is kept as the first line.
- **`english_backup.json`** is written into `/opt/ylak` on the first run only,
  and holds the pre-English name and description of all 196 records. That is
  the revert. A copy is checked in as `english_backup.prod.json`.
- **The deck is food only.** 76 of the 190 POS products (all the drinks, bar
  and wine) were hand-added by the owner after the 01 Sep import — they carry
  no `__ylak__` external id, so `load_15_prune.py` leaves them alone. Their
  English is `inferred` and needs the owner's eye.
- **Two names are held by two live products each**: `CUỐN DIẾP & RAM BẮP`
  (1396 priced/on the till, no xmlid — 1336 unpriced, import-owned, served
  inside `COMBO SET MENU 01 195000`) and `LẨU CHAY THẬP CẨM` (1370 / 1219, same
  shape). Both copies get the same English; merging them changes which product
  the combo deducts, so it stays the owner's call.
- **An open POS session caches its product list.** Staff must refresh the POS
  tab before the new names appear on the buttons.

### Two more traps found while applying it (04 Sep 2026)

- **The backup file is load-bearing, not just an undo.** `description_sale` has
  to keep whatever the owner wrote above the English line, and the only
  reliable record of that is `english_backup.json` from the first run.
  Deriving it from the current value works only while the English text never
  changes: edit a wording in `english_names.py` and the previous paragraph is
  no longer recognisable as ours, so it survives as "owner text" and the new
  one stacks under it. Two paragraphs reached the live combo that way before
  the script was changed to read the backup.
- **Editing an English name orphans its product** unless the lookup also
  matches on the Vietnamese half alone. A product renamed by an earlier run is
  called `<vn> / <old English>`, which matches neither the bare key nor the new
  bilingual name. Hence the `by_prefix` fallback.
- **`backfill_xmlids.py` matches by name** and will no longer find the renamed
  dishes. If an external id is ever lost, `get_or_create`'s name fallback then
  creates a duplicate instead of adopting the existing product — teach it the
  bilingual form before running it again.
- **The two 195,000 set menus are not vegetarian as built.** The deck prints
  them on its VEGETARIAN page, but `COMBO SET MENU 02 195000` serves
  `GỎI RAU MUỐNG TÉP RAM HỒ LĂK` (shrimp) where the deck lists the tofu salad,
  and `COMBO SET MENU 01 195000` serves `RAU CỦ XÀO THẬP CẨM`, which the deck
  itself describes as sautéed with oyster sauce. Their English deliberately
  makes no dietary claim. The 255,000 pair is chay throughout and keeps the
  label.
