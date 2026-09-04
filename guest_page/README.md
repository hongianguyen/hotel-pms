# Guest page — Lak Tented Camp

A single self-contained page for Cloudflare Pages. Guests read the camp
information, build an order from the **live** POS menu, give their room, name
and dining time, and press Book. The order lands on the restaurant till as an
**unpaid** order for reception to confirm.

```
guest_page/
  original_24aug.html            the owner's live page. NEVER EDIT -- only copy
  order/ui.css  ui.html  ui.js   the ordering layer, added on top of it
  menu_link.py                   hand-curated page dish -> till product map
  build_link.py                  menu_link.py + the till -> menu_link.json
  build_page.py                  original + order/ + link  -> index.html
  build_worker.py                index.html                -> worker.js
  index.html                     GENERATED -- do not edit
  worker.js                      GENERATED -- deploy this
  wrangler.toml                  npx wrangler deploy
  menu_link_audit.csv            every dish, the product it maps to, and how
  test_page_dom.cjs              runs the PAGE's js in a DOM (translation+order)
  test_worker.mjs                runs the WORKER against a real Odoo
  superseded_posfeed_page.html   earlier rebuild that drove the menu straight
                                 from the POS feed; kept only because it is
                                 where the drinks/bar handling lives
  functions/api/lak/[[path]].js  only needed if you use Pages instead
```

Rebuild after any change:

```
python3 build_link.py && python3 build_page.py && python3 build_worker.py
```

## Deploying (Cloudflare Worker)

1. `python3 build_worker.py` — regenerates `worker.js` from `index.html`.
   **Edit `index.html`, never `worker.js`**; the next build overwrites it.
2. Cloudflare dashboard → Workers → create a Worker → paste `worker.js` →
   Deploy. One file, no build step, no dependencies.
3. On the Worker: Settings → Variables and Secrets → add
   `ODOO_ORIGIN = https://pms.laktentedcamp.com` (see the caveat below).
4. Install `lak_guest_order` on the Odoo server and fill in its parameters
   (Settings → Technical → System Parameters):

   | key | value |
   |---|---|
   | `lak_guest_order.enabled` | `1` |
   | `lak_guest_order.pos_access_token` | the Y Lak Restaurant POS access token |
   | `lak_guest_order.allowed_origins` | the Pages URL, only if the page ever calls Odoo directly |
   | `lak_guest_order.manager_email` | who gets the alert |
   | `lak_guest_order.telegram_bot_token` / `.telegram_chat_id` | optional second alert |

## The two things that will bite

**Mixed content.** The Worker is served over HTTPS, and a browser will not
let an HTTPS page call `http://14.225.192.16`. It fails silently — no error
the guest sees, just a menu that never loads. That is the entire reason the
Worker serves the page *and* proxies the API: every request the browser makes
is same-origin, and the hop to Odoo happens server-side where the rule does
not apply. Do not "simplify" it by pointing `LAK_API` at the raw address.

**The Cloudflare managed challenge.** `https://pms.laktentedcamp.com`
currently answers `403` with `cf-mitigated: challenge` on every path — a bot
rule, not an origin fault. Until a WAF skip rule exists for `/api/lak/*`, the
Worker's own subrequest is challenged and the page reports that it cannot
reach the kitchen. Either add that rule, or set `ODOO_ORIGIN` to
`http://14.225.192.16` as a stopgap and accept that the edge→camp hop is
unencrypted — it carries guest names and room numbers.

## Checking it before you trust it

`test_worker.mjs` drives the real `worker.js` against a real Odoo: page,
menu, rooms, a live order, and the rejections (unknown room, unlisted path,
wrong method, missing config). Point it at the **test** server — it places
real orders on whichever till it reaches.

```
cp worker.js /tmp/w.mjs && node test_worker.mjs
```

## Languages

Four: EN, VI, FR, HE (right-to-left handled).

**Dish names come from Odoo, in Vietnamese and English**, and they change with
the switcher — that was the bug being fixed. Product names on `hotel_db` are
stored bilingual (`GỎI GÀ HOA CHUỐI / Banana flower salad with chicken`); the
API splits them on ` / ` and the page shows the chosen language large and the
other one underneath.

The interface, headings, ordering flow and every error message are complete in
all four languages. The long descriptive paragraphs are written in English and
Vietnamese; French and Hebrew fall back to English for those, deliberately —
inventing several thousand words of guest-facing French and Hebrew that nobody
at the camp can check is worse than an honest fallback. Add them to `LONG_VI`'s
siblings when the camp has reviewed a translation.

## What the guest cannot do

Pay, charge a folio, or prove who they are. The room number is a claim typed
into a public page. The order is created `draft`, nothing is invoiced, and the
cashier sees `TENT07 · Astrid Haerens · 19:30` on the order so reception can
check it against who is actually in that room.

---

## What the Cloudflare account actually contains (04 Sep 2026)

Connected with an owner-supplied API token and looked before deploying.
Findings, in order of how much they matter:

### 1. The zone is in "I'm Under Attack" mode

`laktentedcamp.com` has `security_level = under_attack`. That is a **zone-wide**
setting, not a WAF rule, and it is why *both* `pms.laktentedcamp.com` and
`hi.laktentedcamp.com` answer `403 cf-mitigated: challenge` on every path.

An earlier note in this repo said the fix was "a WAF skip rule for
`/api/lak/*`". That was wrong -- a path-scoped skip does not lift IUAM, and
the guest page itself is being challenged, not just the API. Page JavaScript
cannot solve an interstitial, so ordering would fail even once the page loaded.

### 2. There was already a Worker, and it is better than this one

`dawn-mud-cfaa` -> `https://hi.laktentedcamp.com` (custom domain, live).
That is the 24 Aug guest page. It is 108 KB and contains:

  - 97 prose elements, each with `data-vi` / `data-fr` / `data-he` -- **0%
    fall back to English**
  - 86 menu items, every one carrying `vi` / `en` / `fr` / `he`
  - diet filters (no pork / no shellfish ...) in 4 languages
  - set menus with separate French and Hebrew descriptions (`dfr`, `dhe`)
  - an activity schedule fetched live from a Google Sheet CSV
  - camp-time phasing (dawn/day/dusk/night) rather than phone time

`index.html` in this directory is 38 KB and has none of that. Deploying it
over `dawn-mud-cfaa` would be a large regression on a live custom domain.
**Do not.** `original_24aug.html` here is a fetched copy -- the Workers API
refuses script download to an API token (`10405`), so it is the only backup.

### 3. The reported translation bug is not where anyone thought

Running the 24 Aug page in a DOM (`jsdom`) and calling `setLang()`: dish names
change correctly in all four languages and Hebrew sets `dir="rtl"`. The bug
the owner reported is **not reproducible** on that page's menu.

Running *this* directory's `index.html` the same way (`test_page_dom.cjs`)
reproduces it exactly: EN, FR and HE all render identical English dish names,
because the POS feed carries only `VIETNAMESE / English`. So the rebuild has
the reported bug and the 24 Aug page does not.

### 4. Workers cannot fetch a bare IP

`ODOO_ORIGIN = http://103.200.20.13:8070` returns `error code 1003`
("Direct IP Access Not Allowed") from inside the Worker. The origin must be a
hostname. No hostname currently points at the test server, so the deployed
`lak-guest-page` renders but its menu is empty.

### Consequence for the merge

The base should be `original_24aug.html`, with the ordering UI ported *into*
it -- not the reverse. Joining the live POS names to the 24 Aug FR/HE strings
on the Vietnamese name gives **50% exact, 72% including close matches** of the
86 food dishes (the fuzzy pairs are real -- prod has `CHẢ CÁ HỒ LĂK` where the
page has `Chả cá hồ Lắk`). The remaining food items and all ~104 drinks/bar
items have no French or Hebrew anywhere. That gap is the owner's call.


---

## The merge (04 Sep 2026)

The ordering layer was added **to** the 24 Aug page rather than replacing it,
because that page was better than the rebuild in every respect except
ordering: 97 prose elements and 86 dishes, each carrying Vietnamese, English,
French and Hebrew, with 0% falling back.

So the page keeps its own curated, fully translated menu, and the till is
asked only three things: does this dish exist right now, what does it cost
today, and which product id goes on the order. The link between the two is
`menu_link.py`, curated by hand because the automatic join makes mistakes a
machine cannot see -- it matched *Gà nướng dùng kèm cơm lam* (grilled chicken
**with** bamboo rice) to plain `CƠM LAM` (bamboo rice) purely because the
shorter string sits inside the longer one.

Of the 86 dishes: 85 resolve to a till product, 16 of them are groups the
till split into separate products (`Mì xào bò / heo / gà / hải sản` is four
buttons on the till) and get a variant picker whose labels stay Vietnamese --
that is what the guest says to the kitchen. One dish, *Cơm chiên cá mặn /
trứng tỏi / muối ớt*, is on the printed menu but not sold on the till, and
shows "Ask us" instead of a quantity control. All 12 set menus map 1:1 to the
`COMBO SET` products by price. `menu_link_audit.csv` lists every decision.

Prices come from the till, not from the page, so the printed 24 Aug prices no
longer drift.

### Verified 04 Sep 2026

`test_page_dom.cjs` -- runs the real page's JavaScript against live test Odoo:

```
fr: Assortiment Y Lak — salade d'aubergine aux anchois, salade d'oeufs, ...
he: מגש י' לאק — סלט חציל ואנשובי, סלט ביצים, קציצת דגים ועוף בגריל
PASS French differs from English   <- the bug the owner reported
PASS Hebrew renders in Hebrew, dir=rtl
PASS 74 dishes orderable, 12 set menus, room picker filled
PASS the order reached the till    (S6)
```

`test_worker.mjs` -- 15/15, order S8. And end-to-end through the **deployed**
worker: order S7, `BUN03 · Worker Merge Test · 20:15`, lang `he`.

### Two traps this cost

- **The ordering markup must go in before the page's `<script>`, not before
  `</body>`.** That script is the last element in the body and wires up its
  own handlers as it runs; markup added after it makes every
  `getElementById` return null, and the whole ordering layer dies silently
  with one `addEventListener` of null.
- **A Worker cannot `fetch()` a bare IP** -- `http://103.200.20.13:8070`
  returns `error code 1003`. Staging therefore points at
  `103-200-20-13.nip.io`, a public wildcard DNS that resolves to that IP and
  carries no traffic itself. Production wants a real hostname.

---

## On production (04 Sep 2026)

`lak_guest_order` is **installed and enabled on `hotel_db`**. Pre-install dump:
`/root/backups/hotel_db-pre-guestorder-20260904-2040.dump` (16 MB).

Verified over public HTTPS at `https://pms.laktentedcamp.com`: `/api/lak/menu`
returns 189 items in **VND**, `/api/lak/rooms` returns 25 rooms. Orders S4 and
S5 were placed and the manager alert reached `sent`. Against that live catalogue the curated link resolves
**84 of 86 dishes and 12 of 12 set menus**. The two that do not: *Cơm chiên
cá mặn / trứng tỏi / muối ớt* (not sold) and *Sữa chua trái cây theo mùa*
(`SỮA CHUA` exists but is not on the till feed). Both show "Ask us".

### Parameters as set

| key | value |
|---|---|
| `lak_guest_order.enabled` | `1` |
| `lak_guest_order.pos_access_token` | copied from `pos_config` 1, *Y Lak Restaurant* |
| `lak_guest_order.from_email` | `noreply@hi.laktentedcamp.com` |
| `lak_guest_order.manager_email` | `res@laktentedcamp.com` |
| `lak_guest_order.allowed_origins` | the Worker + `hi.laktentedcamp.com` |
| `lak_guest_order.telegram_*` | blank (off) |

### Email — and the trap that cost two orders to find

Alerts now go **from** `noreply@hi.laktentedcamp.com` (mail server 7, *Lak
noreply (mxroute)*, `chocobo.mxrouting.net:465` SSL) **to**
`res@laktentedcamp.com`. `manager_email` takes a comma-separated list.
Verified: `mail.mail` 142 reached `sent` on 04 Sep 2026.

🚨 **Setting the From address is not enough, and failing to know that looks
exactly like a working system.** Odoo groups the outgoing queue by
`mail_server_id` and opens ONE SMTP session per group. Mail that names no
server goes in the *default* group — lowest `sequence`, then lowest id — and
`from_filter` is never consulted. All three Outlook servers here are
sequence 10, so the default is the `giang@` account. An alert saying
`From: res@` was therefore pushed down `giang@`'s session, and Outlook
answered:

```
554 5.2.252 SendAsDenied;
giang@laktentedcamp.com not allowed to send as res@laktentedcamp.com
```

So the module resolves `ir.mail_server` by `from_filter` and pins
`mail_server_id` on the message. Without that pin, any From you configure is
advisory.

**The mxroute server is deliberately `sequence = 20`, not lower.** The
lowest-sequence server is Odoo's default for every mail that names no server.
Promoting it would silently re-route booking confirmations and every other
template through a mailbox not allowed to send as `giang@`/`sales@`/`res@`,
turning all of them into SendAsDenied. Leave it last.

### Not yet done

**No order has ever been placed against production's Odoo build.** The two
servers run different point releases, and this module was written to be
portable across them, but portable-by-construction is not the same as tested.
One order needs to go through before the page is given to guests.

**`hi.laktentedcamp.com` still serves the old page.** Everything else is
ready: Under Attack mode came off the zone on 04 Sep 2026 (the setting had
stood since 8 July and was cleared via the API — the dashboard save had not
taken), `pms.laktentedcamp.com/api/lak/*` now answers 200 over public HTTPS,
and the staging Worker is pointed at production. Against the real catalogue
the page resolves **84 of 86 dishes and 12 of 12 set menus**, with French and
Hebrew names and the named room picker. Only the custom-domain flip is left,
and it is reversible: `original_24aug.html` is a byte-exact copy of what
`dawn-mud-cfaa` serves today.
