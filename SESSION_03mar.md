# Session Summary — 03 March 2026

## What Was Done This Session

### 1. Dashboard Status Colors Applied (`hotel_reporting`)
**Request:** Apply specific status colors to Gantt bars and Room Board cards.

| Status | Color |
|---|---|
| Past date / Checked Out | `#9DA2A8` |
| Confirmed | `#799DC7` |
| Dirty (after checkout) | `#DD9200` |
| Active / Checked In | `#E87C09` |
| Maintenance / Out of order | `#F79D2D` |

**Files changed:**
- `hotel_dashboard.py` — added `is_past: current < date.today()` to gantt date data
- `hotel_dashboard.css` — added CSS vars for all status colors; fixed dirty, maintenance, checked_out colors; added `.past-date` column shading
- `reception_dashboard.js` — pass `is_past` through both reservation and empty gantt segments
- `reception_dashboard.xml` — add `past-date` class to gantt `<th>` and `<td>`; updated legend

---

### 2. Dashboard Full Redesign — Modern Light Horizontal Layout
**Request:** Modern style, light mode, horizontal layout.

**New layout structure:**
```
┌─────────────────────────────────────────────────────┐
│  Reception Dashboard    [Date]             [Refresh] │  ← Header
├──────────┬──────────┬──────────┬──────────┬─────────┤
│ ✈ Arr    │ ⬆ Dep    │ ◎ Occ%   │ ⊘ Dirty  │ $ Rev   │  ← 5 KPI cards horizontal
│  (blue)  │ (orange) │  (green) │  (amber) │ (indigo)│
├─────────────────────────────────────────────────────┤
│  Booking Calendar  [Legend]   [‹ Prev] [Date] [Next]│  ← Gantt full width
├─────────────────────────────────────────────────────┤
│  Room Status Board  [Avail: N] [Occ: N] [Dirty: N]  │  ← Room board full width
│  [R101] [R102] [R103] ...                           │
└─────────────────────────────────────────────────────┘
```

**Key design decisions:**
- CSS vars: `--hd-*` prefix for new design system
- KPI cards: colored top border (3px) + icon in colored badge + big number
- All sections use `.hd-card` wrapper with shadow
- Room cards: colored top bar (4px) per status + status label text
- Count badges in room board header (Available / Occupied / Dirty)
- `getCurrentDate()` method in JS for live date in header

---

## Full Project Structure

```
hotel-pms/
├── CLAUDE.md                          # Project blueprint & rules
├── AI_HANDOVER.md                     # Handover notes & Odoo 19 learnings
├── SESSION_03mar.md                   # This file
├── deploy.sh                          # Deploy to PRODUCTION (do not run carelessly)
├── reset_db.sh                        # Reset hotel_pms_test DB on server
├── docker-compose.yml
└── addons/
    ├── hotel_core/                    # Foundation
    │   ├── models/
    │   │   ├── hotel_room.py          # HotelRoom, HotelRoomType models
    │   │   └── hotel_rate_plan.py     # Rate plan with date/day rules
    │   ├── views/
    │   │   ├── hotel_room_views.xml
    │   │   ├── hotel_rate_plan_views.xml
    │   │   └── hotel_core_menu.xml
    │   ├── data/
    │   │   ├── hotel_demo_data.xml    # 30 demo rooms
    │   │   └── hotel_sequence.xml
    │   └── security/hotel_security.xml  # Admin / Reception groups
    │
    ├── hotel_frontdesk/               # Core operations
    │   ├── models/
    │   │   ├── hotel_reservation.py   # Full reservation + state machine
    │   │   ├── hotel_folio.py         # Folio + FolioLine + invoice generation
    │   │   └── hotel_booking_source.py # Booking source model (Walk-in, OTA, etc.)
    │   ├── wizards/
    │   │   ├── hotel_add_charge_wizard.py          # Add charge to folio
    │   │   ├── hotel_group_booking_wizard.py       # Group booking (multi-room, random assign)
    │   │   └── hotel_reservation_email_wizard.py   # Preview/edit email before send
    │   ├── views/
    │   │   ├── hotel_reservation_views.xml  # List, form, calendar, search
    │   │   ├── hotel_folio_views.xml
    │   │   └── hotel_frontdesk_menu.xml
    │   └── data/
    │       ├── hotel_frontdesk_sequence.xml
    │       └── hotel_mail_template.xml      # Confirmation email template
    │
    ├── hotel_housekeeping/            # Kanban board for room status
    │   └── views/hotel_housekeeping_views.xml
    │
    ├── hotel_revenue_basic/           # Pricing engine
    │   └── models/hotel_season.py    # Season model with rate multipliers
    │
    ├── hotel_services/                # F&B / Tours / Extra charges catalog
    │   └── models/hotel_service.py
    │
    ├── hotel_reporting/               # OWL Dashboards
    │   ├── models/hotel_dashboard.py  # Python KPI/data providers
    │   └── static/src/
    │       ├── css/hotel_dashboard.css       # Full design system (hd-* classes)
    │       ├── js/
    │       │   ├── reception_dashboard.js    # OWL component (gantt, drag-drop, nav)
    │       │   └── admin_dashboard.js        # Admin OWL component
    │       └── xml/
    │           ├── reception_dashboard.xml   # Reception template (horizontal layout)
    │           └── admin_dashboard.xml       # Admin template
    │
    └── hotel_night_audit/             # Auto nightly cron at 02:00 AM
        ├── models/hotel_night_audit.py
        └── data/ir_cron_night_audit.xml
```

---

## Key Technical Notes (Odoo 19)

1. `_sql_constraints` → `models.Constraint('SQL', 'msg')` as class attribute
2. `res.groups` uses `user_ids` (not `users`), no `category_id`
3. `<search>` view `<group>` tags: no `expand="0"` or `string="..."` attributes
4. `invisible="expr"` syntax (not old `attrs={}`)
5. `ir.cron` has no `numbercall` field in Odoo 19
6. Always use `@api.model_create_multi` for `create()`

---

## Deployment Info

| Environment | Path | Port | DB | Command |
|---|---|---|---|---|
| **Test** | `/opt/hotel-pms-test/addons/` | 8070 | `hotel_pms_test` | Manual start |
| **Production** | `/opt/odoo/custom_addons/` | 8069 | `hotel_db` | `systemctl restart odoo` |

**Server:** `root@103.200.20.13`
**SSH Key:** Added `~/.ssh/id_ed25519` (hotel-pms-server) to `/root/.ssh/authorized_keys`

**Deploy to test (from claude-worker):**
```bash
tar czf /tmp/hotel-pms-addons.tar.gz -C addons hotel_core hotel_frontdesk hotel_housekeeping hotel_revenue_basic hotel_services hotel_reporting hotel_night_audit
scp -i ~/.ssh/id_ed25519 /tmp/hotel-pms-addons.tar.gz root@103.200.20.13:/root/
ssh -i ~/.ssh/id_ed25519 root@103.200.20.13 'tar xzf /root/hotel-pms-addons.tar.gz -C /opt/hotel-pms-test/addons/'
ssh -i ~/.ssh/id_ed25519 root@103.200.20.13 'sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo-bin -c /opt/hotel-pms-test/odoo-test.conf -u hotel_reporting --stop-after-init'
ssh -i ~/.ssh/id_ed25519 root@103.200.20.13 'nohup sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo-bin -c /opt/hotel-pms-test/odoo-test.conf > /dev/null 2>&1 &'
```

---

## Pending / Next Session

- [ ] Adapt dashboard design to Hotelogix reference (user shared image, not yet applied)
- [ ] Fix group booking: currently creates N separate reservations — should be 1 booking → 1 folio
- [ ] Verify rate plan override base price end-to-end (logic exists, untested)
- [ ] Test night audit cron manually
- [ ] QA: OWL dashboard runtime in browser (JS errors, bundle issues)
