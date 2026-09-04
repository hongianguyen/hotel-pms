# Source data

## Provenance

All three `.md` files are verbatim text exports of Google Sheets in the owner's
Drive folder `170YrcuDACmwHPT7htwDm6zJhnD5jGVOB`, taken 30 Aug 2026. `extra_cost.md`
was added by the owner later that day, after the first load. They are
committed so extraction is reproducible without Drive access, and so a later
re-export can be diffed against what the current JSON was actually built from.

| File | Drive title | Drive file id |
|---|---|---|
| `kho_no_duplicate.md` | KHO- no duplicate | `1tKQyXzM77B84u1nHHFT47ByeOvK5JgcqDJnB7xqk9hM` |
| `cost_of_places_rvd.md` | cost of places rvd | `1CrMbukIkEVjs7r55XZGYQAlX2a3FTrlpFtiMhidqKvY` |
| `extra_cost.md` | extra Cost_ingredients | `1NV7c98nM6UtKy-3aQPfhATzaICNH948LAWjvYTdFOH0` |

`COST.xlsx` (one level up) is the older workbook the first import used. It is
kept because the seven `CORRECTIONS` in `mapping.py` describe row shifts in
*that* file and must only be applied to it.

## Format

Each sheet renders as a markdown table. Sheets are separated by a blank line
followed by an all-empty header row and a `| :-: |` alignment row. A cell that
was part of a merged range is rendered as `\[merged\] <value>`, repeated across
every column the merge spanned — which is how section and dish headers are
recognised.

## Shapes

### `kho_no_duplicate.md` — 3 sheets, 10 stock tables, 1,081 rows

All are stock counts dated 24/08/2026 with columns
`Hàng hoá | Nhóm hàng hoá | Đơn vị tính | Tồn cuối kỳ`, except the department
tables in sheet 3, which vary — several use `STT | TÊN | ĐVT | SL` and some put
the item name in the second column.

| Sheet | Table | Rows | Store |
|---|---|---|---|
| 1 | KHO BẾP | 263 | Bếp |
| 2 | KHO NHÀ HÀNG / BAR | 70 | Nhà hàng |
| 3 | *(untitled)* office & general | 69 | Bảo trì |
| 3 | CÔNG CỤ DỤNG CỤ BỘ PHẬN BẢO TRÌ | 182 | Bảo trì |
| 3 | CÔNG CỤ DỤNG CỤ BUỒNG PHÒNG | 140 | Buồng phòng |
| 3 | CÔNG CỤ DỤNG CỤ NHÀ HÀNG | 158 | Nhà hàng |
| 3 | ĐỒ LƯU NIỆM – LỄ TÂN | 13 | Lễ tân |
| 3 | CÔNG CỤ DỤNG CỤ BẾP | 148 | Bếp |
| 3 | ĐỒ TOUR | 32 | Tour |
| 3 | ĐỒ CÂY XANH | 6 | Cây xanh |

Verified 30 Aug 2026: **1,081 rows, 1,081 distinct names, zero collisions
across tables.** The title's "no duplicate" is global, not per-sheet. The
extractor re-checks, because the owner edits these by hand.

### `cost_of_places_rvd.md` — 5 sheets

| Sheet | Offset | Content |
|---|---|---|
| 0 | 0 | À-la-carte costing **with selling price + cost%** — partial, stops mid-CANH |
| 1 | 21739 | Full recipe costing, 110 dishes incl. drinks, no prices |
| 2 | 60045 | **SET MENU** — 6 tiers × SET 1/SET 2, side by side (SET 1 cols A–E, SET 2 cols G–K) |
| 3 | 89647 | `ĐỊNH LƯỢNG` recipe quantities — the sheet the first import parsed |
| 4 | 112413 | **COST BUFFET (20 Pax)**, 38 lines = 2,367,159 VND, + SET UP BUNGALOW |

Recipe rows are `ingredient | unit | unit_price | qty | line_cost`, and each
dish ends with a `Tỷ lệ gia vị 10%+ 20% hao hụt` row charged at 30%.

**The owner directed 10%, not 30%** — the 20% waste is treated as operational
loss, not recipe cost — and the uplift is cost-only: it is never a BoM line.

### `extra_cost.md` — 1 sheet, 28 costed blocks

Same block format as `cost_of_places_rvd` sheet 0 — dish header (merged across
its span), ingredient rows, a `Tỷ lệ gia vị 10%+ 20% hao hụt` row at 30%, then
a `TỔNG` row — and unlike sheet 1 it carries **selling prices**, which is most
of what it is here for. Parsed by `extract_extra.py`, which merges it into
`menu_data.json` rather than writing its own file.

Three traps, all visible in the file:

- **`TRÀ XANH` shows qty `0.00`** against a line cost of 60 at 59,800/kg. The
  real quantity is 0.001 and the sheet rounds it away in display, so the
  quantity is recovered from the line cost, which is not rounded.
- **The `TỔNG` selling price moves column.** It sits in column 6 for most
  blocks and column 7 for the whole MIẾN / MÌ / CƠM CHIÊN group. The extractor
  scans both and **aborts** if a block that should have a price has none —
  a silently missing price would load the dish hidden from POS, which is the
  exact problem this sheet was supplied to fix.
- **The file disagrees with itself.** `Bánh phồng tôm` is 86,400 in the
  KHAI VỊ CHAY block and 92,880 in GỎI NGÓ SEN; `Rau muống` is 12,960 and
  16,200. First-seen wins, and every disagreement is printed.
- **`CACAO`'s own TỔNG is wrong.** Its lines come to 15,185 and its 30% row
  (4,556) agrees with that, but the total says 13,261. The extractor compares
  every computed cost against the sheet's own line costs and says which side
  is at fault; CACAO is the only block where the sheet cannot add up its own
  column, and `KHAI VỊ CHAY` the only one that diverges for a real reason
  (ingredient-cost precedence). That comparison is the one check that is not
  circular — everything in `verify.py` compares two numbers that both come
  out of this parser.

| Block group | Count | Treatment |
|---|---|---|
| New à-la-carte dishes | 16 | new products, priced |
| Wines (bottle) | 5 | `kind: wine` → own product + POS category |
| Honey / cocoa / coffee packs | 3 | `kind: retail`, same |
| Green tea | 1 | `kind: drink` |
| Already in `menu_data` under another name | 3 | price only, recipe untouched |
| `CUỐN DIẾP & RAM BẮP` | 1 | set course, no price — see below |

The last block carries `trong set menu` ("in the set menu") in its own header
row and has no selling price. It is read as the missing `CUỐN DIẾP CHAY`
recipe, which completes the 195,000 vegetarian SET 1.
