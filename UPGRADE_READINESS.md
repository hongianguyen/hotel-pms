# Odoo Upgrade Readiness — Hotel PMS custom addons

**Audit date:** 09 Aug 2026 · **Current:** Odoo 19 CE · **Target:** Odoo 20 (expected ~Oct 2026)

**Stated assumption:** self-managed Community Edition (Odoo 19 CE on `14.225.192.16`, custom
addons in `/opt/odoo/custom_addons`, OCA repos in `/opt/odoo/oca`). That means **there is no
upgrade service doing this for you** — you run `odoo-bin -u all` against the v20 codebase
yourself, and your `migrations/<version>/pre|post-migrate.py` scripts are the entire
data-migration mechanism. OpenUpgrade covers the core-side deltas. *If you are actually on
Odoo.sh or Enterprise, the platform handles core and this plan changes at the edges — the
module-side findings below stay identical either way.*

---

## The short version

The Python business logic in `hotel_core` / `hotel_frontdesk` / `hotel_housekeeping` /
`hotel_services` / `hotel_night_audit` / `hotel_revenue_basic` is clean, self-contained ORM
code. It will most likely come across with only manifest-version bumps.

**Essentially all of your upgrade risk is concentrated in one module — `hotel_pos_folio` —
plus three view anchors and one deprecated ORM call.** That is good news: the blast radius
is small and nameable. The problem is that most of it fails *silently*, and you have **zero
automated tests**, so nothing would tell you.

Two pieces of good news confirmed during the audit:

- `hotel_core/data/hotel_demo_data.xml` is `noupdate="1"`, so your real 23-room Lak Tented
  Camp inventory **will not be stomped** by an `-u hotel_core`. No data-loss risk there.
- No `attrs=`, no `states=`, no `_sql_constraints`, no `name_get` overrides anywhere. The
  Odoo 19 migration cleanup was done properly and left nothing rotting.

---

## Findings, ranked

Severity is about **how you'd find out**: *Loud* = it raises on install/boot, you cannot miss
it. *Silent* = the module loads fine and a feature just stops working, possibly for weeks.

| # | Where | What breaks | Fails |
|---|-------|-------------|-------|
| 1 | `addons/hotel_pos_folio/models/res_partner.py:87` `_extract_search_term` | Reverse-engineers POS's search domain by grabbing the first 3-element leaf it finds. Nothing about that shape is contractual. If v20 builds its OR-domain differently, this returns the wrong term or `None` and room-number search silently stops matching. | **Silent** |
| 2 | `addons/hotel_pos_folio/static/src/app/screens/partner_list/partner_line/partner_line.xml:8,13` | Two xpaths anchored on **Bootstrap utility classes** in a core POS template — `hasclass('justify-content-between')`, `hasclass('text-break')`. Any POS restyle in v20 drops the match. The room number vanishes from the cashier's guest list and no error is raised. | **Silent** |
| 3 | `addons/hotel_pos_folio/models/res_partner.py:55,67` `_load_pos_data_domain(self, data, config)`, `_load_pos_data_fields(self, config)` | Underscore-private POS loader API. These signatures have already churned across 17→18→19 (they were `_loader_params_*` two versions ago). Best case a `TypeError` on POS open; worst case v20 calls them differently and the in-house partner filter loads nothing. | Loud *or* Silent |
| 4 | `addons/hotel_pos_folio/models/res_partner.py:71` `get_new_partner(config_id, domain, offset)` | Same class of problem — cashier-side search API, three positional args, no stability guarantee. | Loud |
| 5 | `addons/hotel_frontdesk/models/res_partner.py:37,42` `read_group()` | Deprecated since Odoo 17 in favour of `_read_group`, which returns **tuples, not dicts**. The `g['guest_id'][0]` and `g['guest_id_count']` accesses are exactly the pattern that breaks. Likely removed outright in v20 — and this runs on every partner form open. | Loud |
| 6 | `addons/hotel_pos_folio/views/pos_config_views.xml:14` | `xpath expr="//setting[@id='other_devices']"`. Settings views are the single most-rewritten view family in Odoo — this exact class of anchor already bit you once in v19 (see MEMORY rule 8). | Loud |
| 7 | `addons/hotel_pos_folio/models/pos_order.py:26` `_process_order(self, order, existing_order)` | Private POS order-creation hook. The signature gained `existing_order` relatively recently; it can move again. If it does, **POS orders stop posting to folios** while POS itself keeps working. | Loud *or* Silent |
| 8 | `addons/hotel_frontdesk/views/res_partner_views.xml:12` | `xpath expr="//field[@name='category_id'][1]"` — positional predicate into a core form. The `[1]` is almost certainly unnecessary; drop it and the anchor gets much more durable. | Loud |
| 9 | `addons/hotel_core/data/hotel_maintenance_cron.xml` (no `noupdate`) | Record is rewritten on **every** `-u hotel_core`, upgrade included. If anyone has disabled or retuned that cron in the UI, the upgrade silently re-enables it at `active=True`, 1 day. | **Silent** |
| 10 | `addons/hotel_core/data/hotel_sequence.xml` (no `noupdate`) | Same rewrite-on-update behaviour. Lower risk than #9 because the XML doesn't set `number_next`, so the counter isn't reset — but prefix/padding edits made in the UI would be reverted. | **Silent** |
| 11 | `hotel_reporting` — 2 OWL client actions, 295 lines JS | `registry.category("actions")` is stable and `useService("orm")` is a public surface, so this is medium-low risk. But `@odoo/owl` imports and hook signatures do shift between majors, and the whole reception dashboard is one component. | Loud |
| 12 | `partner_line.xml:10,15` | `t-esc` is superseded by `t-out` in OWL 2. Still works today; free to modernise while you're in the file. | Cosmetic |
| 13 | **Whole repo** | **No tests.** Nothing in the repo can tell you whether an upgrade broke the reservation state machine, the group cascade, or POS→folio posting. This is what turns a 10-minute verification into a two-day click-through. | — |
| 14 | External | v20 requires: OCA repos to have published `20.0` branches (12 modules on prod), and `hr_zkteco_attendance` to work on v20 — that one already needed a hand-written v19 settings-view fix. | Loud |

---

## Plan

### Phase 1 — harden now, before v20 exists — ✅ **DONE 09 Aug 2026**

Everything here was a v19-safe change that reduces v20 surface area. None of it needed the
v20 source to be released. All of it is applied, deployed to the test server, and verified.

- [x] **Fixed `read_group` → `_read_group`** (`hotel_frontdesk/models/res_partner.py:34-51`).
      Groups now unpack as `(recordset, *aggregates)` tuples. Covered by
      `test_partner_stay_statistics`.
- [x] **Dropped the `[1]` predicate** in `hotel_frontdesk/views/res_partner_views.xml:12`.
- [x] **Added `noupdate="1"`** to `hotel_core/data/hotel_maintenance_cron.xml` and
      `hotel_core/data/hotel_sequence.xml`.
- [x] **`t-esc` → `t-out`** in `partner_line.xml`, plus an inline upgrade warning on the
      two fragile xpaths.
- [x] **Wrote the regression suite** — 29 tests, all passing (see below).
- [x] **Added `addons/hotel_pos_folio/README.md`** listing every private POS API the module
      overrides, so the next person knows it is version-coupled by design.

### Phase 2 — when the v20 source drops (~Oct 2026)

- [ ] Diff `point_of_sale`'s `res.partner` / `pos.order` loader methods against the four
      overrides in findings #1, #3, #4, #7. **Check signatures first, behaviour second.**
- [ ] Re-anchor the two `partner_line.xml` xpaths against the real v20 template. Prefer a
      semantic anchor (a `t-name`, a named field, a stable id) over Bootstrap classes.
- [ ] Re-anchor `pos_config_views.xml` against the v20 settings view.
- [ ] Confirm OCA `20.0` branches exist for all 12 installed accounting modules. **If they
      don't, that alone can hold the whole upgrade** — check this early, it's out of your hands.
- [ ] Bump all 8 manifests `19.0.x` → `20.0.1.0.0`. Migration script directories are named
      for the **target** version, so new ones go in `migrations/20.0.1.0.0/`. The two existing
      dirs (`hotel_frontdesk/migrations/19.0.1.1.0/`, `hotel_pos_folio/migrations/`) stay put —
      they're historical and still needed by any DB coming from further back.

### Phase 3 — the actual upgrade

- [ ] Restore a **fresh production dump** into a scratch DB. Never rehearse on prod.
- [ ] Run OpenUpgrade for the core-side v19→v20 deltas.
- [ ] `-u all` with custom addons in the path; fix loudly-failing items until it boots.
- [ ] **Run the test suite** (`--test-enable --test-tags /hotel_frontdesk,/hotel_pos_folio`).
      This is where the Phase 1 investment pays for itself — it catches the silent findings
      (#1, #2, #7) that booting successfully will not.
- [ ] Manual pass on the three things tests can't see: the reception Gantt renders and
      drag-drop works; a real POS ticket charges to a real folio; the night-audit cron fires.
- [ ] Only then schedule the production window.

---

## The test suite — 29 tests, all green

Built on `AccountTestInvoicingCommon` (so a chart of accounts and a sales journal always
exist), tagged `post_install`. Deliberately **not** broad coverage — targeted at the state
transitions and the money paths, i.e. the things that fail silently and cost real money.

**`addons/hotel_frontdesk/tests/`** — 19 tests
- `test_reservation_lifecycle.py` — full `draft → confirmed → checked_in → checked_out →
  invoice` path with folio lines and room status; the guards (no early check-in, no confirm
  without a room, no cancelling in-house, no double-booking); the `checkin < checkout` DB
  CHECK constraint; late-checkout auto-charging; and the `_read_group` partner statistics.
- `test_group_booking.py` — master folio shared by children, state cascade, invoicing only
  when the **last** room departs, date amendments reaching draft children but not in-house
  ones, and the refusal to cancel a group with rooms occupied.

**`addons/hotel_pos_folio/tests/`** — 18 tests
- `test_pos_api_surface.py` — **the upgrade canaries.** Calls each private POS API this
  module overrides with its current signature, so a v20 signature change fails here loudly
  instead of silently emptying the cashier's customer list. Also pins the clearing-account
  constraint (current asset, reconcilable, never receivable).
- `test_pos_folio_charge.py` — end to end over a real POS session: a room-charged order
  posts an F&B folio line carrying the clearing account, replays idempotently, reaches the
  check-out invoice, and is refused for walk-ins, customerless orders, and unpaid orders.

```
odoo-bin -c <conf> -d <db> -u hotel_frontdesk,hotel_pos_folio --test-enable --stop-after-init
```

Last run 09 Aug 2026 against a scratch copy of `hotel_pms_test`:
`0 failed, 0 error(s) of 29 tests`, exit 0.

**Run these on a scratch copy, never on `hotel_pms_test` itself** — `-u` is a real schema
write even though the test transactions roll back:

```bash
sudo -u postgres createdb -T hotel_pms_test -O odoo hotel_upgrade_test
```

One environmental note for whoever runs them next: the hotel sequences are bound to
`company_id = 1`, while `AccountTestInvoicingCommon` runs in a throwaway company. The fixture
in `tests/common.py` unbinds them for the duration of the transaction — that is a test-harness
concession, not a production bug.

---

## What is *not* a risk

Worth recording so nobody re-audits it: the real room inventory is `noupdate`-protected; the
Python models use `@api.model_create_multi` consistently on all 5 `create()` overrides; there
are no `attrs=`/`states=` leftovers, no `_sql_constraints`, no `name_get`. The single raw SQL
statement outside migrations (`hotel_frontdesk/wizards/hotel_group_booking_wizard.py:98`) is a
deliberate `SELECT ... FOR UPDATE` row lock against your own table — no core schema
dependency, safe across versions.
