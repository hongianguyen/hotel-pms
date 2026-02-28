# CLAUDE.md - Odoo 19 Hotel PMS

This file provides autonomous instructions and commands for Claude Code to manage, build, and deploy the Internal Hotel PMS project. 

## 🏗️ Project Setup & Architecture
- **Tech Stack:** Python 3.12+, Odoo 19 Community Edition, PostgreSQL 16.
- **Framework:** Odoo Native ORM, XML Views, OWL 2.0 (Dashboards).
- **Primary Server:** `103.200.20.13` (User: `root`).
- **Test Environment:** `/opt/hotel-pms-test/` (Port 8070, DB: `hotel_pms_test`).
- **Production Environment:** `/opt/odoo/custom_addons/` (Port 8069, DB: `hotel_db`).

## 🚀 Autonomous Execution Commands



## 📝 Coding Guidelines & Conventions (Sourced from Odoo 19 / Master Branch)
*Note: Since Odoo 19 documentation is still in development, these rules were empirically derived by reverse-engineering the core Odoo framework on the VPS (e.g., `/opt/odoo/odoo/orm/table_objects.py`, `/opt/odoo/addons/base/models/res_groups.py`).*

1. **Odoo 19 Compatibility:** 
   - Replace `_sql_constraints` with `_name = models.Constraint('...sql...', 'msg')` as class-level attributes starting with an underscore.
   - For `res.groups`, the users field is `user_ids`. NEVER use the `users` or `category_id` fields, they are deprecated.
   - In Search views XML (`<search>`), `<group>` elements CANNOT have `expand="0"` or `string="..."` attributes. Use a bare `<group>` tag.
2. **Python Formatting:** Standard PEP 8. Use standard Odoo decorators (`@api.depends`, `@api.model`, `@api.onchange`). Always include `# -*- coding: utf-8 -*-` at the top of Python files.
3. **XML Formatting:** 4 spaces indentation. Follow Odoo element hierarchy strictly. Use `invisible="expr"` instead of the old `attrs="{'invisible': ...}"` syntax (Odoo 17+ standard).
4. **Action:** Once a command is triggered, proceed autonomously to the next step without prompting the user, checking the logs contextually to guide fixes.
