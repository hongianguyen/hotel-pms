# 🏨 Internal Hotel PMS v1.0

**Odoo 19 Community** custom addons for property management.  
1 property · 30 rooms · 2 roles (Admin / Reception)

## Modules

| Module | Description |
|---|---|
| `hotel_core` | Rooms, room types, rate plans, security groups |
| `hotel_frontdesk` | Reservations, check-in/out, folios, invoicing |
| `hotel_housekeeping` | Room status kanban board |
| `hotel_revenue_basic` | Season pricing, rate engine |
| `hotel_services` | Tours, F&B, extra charges |
| `hotel_reporting` | Reception + Admin dashboards (OWL) |
| `hotel_night_audit` | Automated nightly audit (02:00 AM cron) |

## Installation

### 1. Copy addons to Odoo

```bash
cp -r addons/hotel_* /path/to/odoo/addons/
```

### 2. Update addons list

Go to **Apps** → **Update Apps List** → Search "Hotel"

### 3. Install hotel_core first

Install `hotel_core`, then install remaining modules.

Or via CLI:

```bash
odoo -d hotel_db \
  --init hotel_core,hotel_frontdesk,hotel_housekeeping,hotel_revenue_basic,hotel_services,hotel_reporting,hotel_night_audit \
  --stop-after-init
```

## Demo Data

**30 rooms** across 4 types:
- T01-T08: Tent (300,000đ/night)
- B01-B10: Bungalow (800,000đ/night)
- D01-D06: Dorm (150,000đ/night)
- K01-K06: Kpan Tiny House (600,000đ/night)

**8 services**: Breakfast, Lunch, Dinner, 3 Tours, Laundry, Airport Transfer

**2 rate plans**: Standard Rate, Weekend Rate

## Roles

- **Admin**: Full access to all modules, accounting, rate plans, night audit
- **Reception**: Reservations, check-in/out, charges, dashboards (read-only rate plans & accounting)

## Night Audit

- Runs automatically at **02:00 AM** daily via `ir.cron`
- Posts draft invoices
- Flags unpaid folios
- Generates KPI snapshot (Occupancy %, ADR, RevPAR, revenue split)
- Locks previous day edits
- Emails summary to all Admin users

## Requirements

- Odoo 19 Community
- PostgreSQL 14+
- Python 3.12+
- VPS: 4 vCPU / 8 GB RAM (recommended)
