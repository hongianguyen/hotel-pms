# CLAUDE.md - Odoo 19 Hotel PMS

This file provides, Bllueprint, contract, autonomous instructions and commands for Claude Code to manage, build, and deploy the Internal Hotel PMS project. 

## 🏗️ Project Setup & Architecture
- **Tech Stack:** Python 3.12+, Odoo 19 Community Edition, PostgreSQL 16.
- **Framework:** Odoo Native ORM, XML Views, OWL 2.0 (Dashboards).
- **Production Server:** `14.225.192.16` (User: `root`, key auth only).
  DB `hotel_db`, addons `/opt/odoo/custom_addons/`, conf `/etc/odoo.conf`,
  binary `/opt/odoo/odoo/odoo-bin`. Odoo binds `127.0.0.1:8069`; nginx on :80
  is the only public entry point. Chart of accounts is VN TT200 (VND).
- **Test Server:** `103.200.20.13` (User: `root`).
  DB `hotel_pms_test`, addons `/opt/hotel-pms-test/addons/`,
  conf `/opt/hotel-pms-test/odoo-test.conf`, binary `/opt/odoo/odoo-bin`.
  Odoo binds `127.0.0.1:8075`; nginx serves it on :8070.
  🚨 Kill port **8075**, never 8070 — 8070 is nginx, and killing it takes the
  separate Ferntree HR site down with it. Port 8069 on this host is Ferntree
  HR's own database; there is no `hotel_db` here.
  After any `--stop-after-init` run, restart the instance or the test site
  stays down (it has no systemd unit).

## 📝 Coding Guidelines & Conventions (Sourced from Odoo 19 / Master Branch)
*Note: Since Odoo 19 documentation is still in development, these rules were empirically derived by reverse-engineering the core Odoo framework on the VPS (e.g., `/opt/odoo/odoo/orm/table_objects.py`, `/opt/odoo/addons/base/models/res_groups.py`).*

1. **Odoo 19 Compatibility:** 
   - Replace `_sql_constraints` with `_name = models.Constraint('...sql...', 'msg')` as class-level attributes starting with an underscore.
   - For `res.groups`, the users field is `user_ids`. NEVER use the `users` or `category_id` fields, they are deprecated.
   - In Search views XML (`<search>`), `<group>` elements CANNOT have `expand="0"` or `string="..."` attributes. Use a bare `<group>` tag.
2. **Python Formatting:** Standard PEP 8. Use standard Odoo decorators (`@api.depends`, `@api.model`, `@api.onchange`). Always include `# -*- coding: utf-8 -*-` at the top of Python files.
3. **XML Formatting:** 4 spaces indentation. Follow Odoo element hierarchy strictly. Use `invisible="expr"` instead of the old `attrs="{'invisible': ...}"` syntax (Odoo 17+ standard).
4. **Action:** Once a command is triggered, proceed autonomously to the next step without prompting the user, checking the logs contextually to guide fixes.
