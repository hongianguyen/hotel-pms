# AI Handover: Odoo 19 Hotel PMS

**Target Agent:** You are taking over the development and maintenance of the "Internal Hotel PMS v1.0" project. This is a comprehensive Hotel Management System built purely as custom modules for **Odoo 19 Community Edition**.

## 🚀 Current Status (As of Transfer)
- **Status:** All 7 custom modules have been completed, refactored for Odoo 19 compatibility, and successfully installed in the test environment without layout errors or schema errors.
- **Last Action Performed:** Fixed a dependency issue where `hotel_frontdesk` needed `hotel_services` in its `depends` list since the `hotel.add.charge.wizard` references the `hotel.service` model. Successfully deployed and tested DB recreation and module initialization via CLI, yielding an `Exit code: 0`.

## 🛠 Tech Stack
- **Core:** Odoo 19 Community Edition
- **Database:** PostgreSQL 16
- **Language:** Python 3.12+ 
- **UI:** Odoo native XML views, OWL components (for Dashboards), Kanban/List/Form/Gantt Views.
- **Server:** Ubuntu VPS (`103.200.20.13`), User `root`.

## 📁 Repository & Architecture
- **Local Path:** `d:\LakManagement\hotel-pms`
- **GitHub:** `https://github.com/hongianguyen/hotel-pms` (Branch: `main`)
- **Server Production Addons Path:** `/opt/odoo/custom_addons/` (Service runs as systemd `odoo.service` on port 8069).
- **Server Testing Path:** `/opt/hotel-pms-test/` (Testing runs manually on port 8070, db: `hotel_pms_test`).

### Modules Overview (7 Modules)
1. **`hotel_core`**: Foundation base. Manages Room Types, Rooms (30 demo rooms), Rate Plans, and Security Roles (Admin/Reception).
2. **`hotel_frontdesk`**: Core operations. Manages Reservations, state machine (Draft > Confirmed > Checked-in > Checked-out > Cancelled), Folios, Billing, and Check-in/out workflows.
3. **`hotel_housekeeping`**: Housekeeping operations. Provides a Kanban board for room status tracking (Available, Dirty, Cleaning, Maintenance).
4. **`hotel_revenue_basic`**: Pricing engine. Manages Seasons (Standard/Weekend rates) with rate multipliers.
5. **`hotel_services`**: F&B, Tours, Extra charges setup.
6. **`hotel_reporting`**: Dashboard views. Features **OWL-based Dashboards** for Reception (Gantt calendar, check-ins/outs) and Admin (Revenue trends, Occupancy).
7. **`hotel_night_audit`**: Automated nightly audit. Runs at 2:00 AM via cron job. Processes draft invoices, flags unpaid folios, logs KPI snapshots, and sends emails to the Admin group.

## 🐛 Odoo 19 Specific Learnings & Fixes (CRITICAL)
*Source Note: As Odoo 19 is the cutting-edge Master branch, official documentation is sparse. These architectural changes were directly sourced by reverse-engineering the Odoo source code on the VPS (tracing `odoo.tools.convert.ParseError` logs into `/opt/odoo/odoo/orm/table_objects.py` and `sale` native modules).*

If you ever need to refactor or add to this code, stick to these Odoo 19 patterns discovered during development:
1. **Model Constraints:** `_sql_constraints = [...]` is **deprecated** in Odoo 19. It **MUST** use the new syntax: `_name_uniq = models.Constraint('UNIQUE(name)', 'Room type name must be unique!')`.
2. **`res.groups` Fields:** The old `users` field is now `user_ids`. Field `category_id` was removed.
3. **Search View `group` tags:** Odoo 19 XML validation strictly forbids `expand="0"` and `string="..."` inside `<group>` blocks nested under `<search>`. Only `<group>` is allowed. Example context group-by must look like: 
   ```xml
   <group>
       <filter string="Room Type" name="group_type" context="{'group_by': 'room_type_id'}"/>
   </group>
   ```

## ⚠️ Scripts & Deployment
- **`deploy.sh`**: A bash script in the root directory that `rsync`s all addons to `/opt/odoo/custom_addons` on the VPS, updates Odoo `-u hotel_core,...` and restarts the systemd service. Usage: `./deploy.sh root@103.200.20.13 hotel_db`.
- **`reset_db.sh`**: Found inside `/opt/hotel-pms-test/reset_db.sh` on the server. Used to disconnect connections, drop `hotel_pms_test`, and recreate it during heavy iterative testing.

## ✔️ Next Steps For The New Agent
1. The project has been completely pushed to GitHub.
2. The testing server was just verified and modules installed perfectly via CLI. You may want to restart the test server in the background:
   ```bash
   nohup sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo-bin -c /opt/hotel-pms-test/odoo-test.conf > /dev/null 2>&1 &
   ```
3. Ask the user if they'd like to perform any frontend QA on the running Odoo 19 instance at `http://103.200.20.13:8070`.
4. If testing looks perfect, deploy the code to the production instance using `./deploy.sh root@103.200.20.13 <production_db_name>`.

## 🐛 Existing Bugs / Unverified Features (To-Do List)
While the modules compile and install via CLI (Exit Code 0), the following areas require immediate verification by the next agent:

1. **OWL Dashboards Runtime Validation:** The `hotel_reporting` module includes custom OWL components for the Gantt chart and KPI dashboards. Odoo 19 introduces strict OWL 2.0 changes. **Bug/Risk:** The dashboards have not been opened in the browser yet; there may be JavaScript runtime errors, missing bundle includes, or OWL component mounting issues.
2. **UI Activation Quirks:** We resolved `ParseError` exceptions during CLI initialization (related to old `res.groups` fields and search view `<group>` tags). **Risk:** If you click "Activate" directly from the Odoo Apps UI, check the logs (`/var/log/odoo/odoo-test.log`) to ensure no further XML parsing issues block the UI flow.
3. **Automated Night Audit Cron:** The `ir.cron` job for Night Audit is configured to run at 02:00 AM. **Risk:** The Python logic executing `Folio -> account.move` posting and email generation needs to be manually triggered once to ensure it doesn't hit any unhandled exceptions with Odoo 19's `account.move` posting API.
4. **Rate Plan / Seasonal Multiplier Calculation:** The logic extending `base_rate` with `season.rate_multiplier` needs an end-to-end booking test to verify the calculated folio charges match expected values.
