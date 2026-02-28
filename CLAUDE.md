# CLAUDE.md - Odoo 19 Hotel PMS

This file provides autonomous instructions and commands for Claude Code to manage, build, and deploy the Internal Hotel PMS project. 

## 🏗️ Project Setup & Architecture
- **Tech Stack:** Python 3.12+, Odoo 19 Community Edition, PostgreSQL 16.
- **Framework:** Odoo Native ORM, XML Views, OWL 2.0 (Dashboards).
- **Primary Server:** `103.200.20.13` (User: `root`).
- **Test Environment:** `/opt/hotel-pms-test/` (Port 8070, DB: `hotel_pms_test`).
- **Production Environment:** `/opt/odoo/custom_addons/` (Port 8069, DB: `hotel_db`).

## 🚀 Autonomous Execution Commands

### 1. Sync Code to Test Server (Upload)
Use this command to push local addon changes to the test environment:
```bash
scp -r addons/hotel_* root@103.200.20.13:/opt/hotel-pms-test/addons/
```

### 2. Reset Database & Restart Test Server (Fast Iteration)
When module XML/Python is heavily refactored or corrupted, use this chain to reset the DB and re-initialize all modules autonomously:
```bash
ssh root@103.200.20.13 "pkill -f 'odoo-test.conf'; sleep 1; bash /opt/hotel-pms-test/reset_db.sh; truncate -s 0 /var/log/odoo/odoo-test.log; nohup sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo-bin -c /opt/hotel-pms-test/odoo-test.conf -d hotel_pms_test -i hotel_core,hotel_frontdesk,hotel_housekeeping,hotel_revenue_basic,hotel_services,hotel_reporting,hotel_night_audit > /dev/null 2>&1 &"
```

### 3. Check Server Logs (Debugging)
To autonomously debug crashes or `ParseError`s during module initialization:
```bash
ssh root@103.200.20.13 "tail -50 /var/log/odoo/odoo-test.log | grep -E 'ERROR|CRITICAL|ParseError|odoo.tools.convert'"
```

### 4. Deploy to Production
Use the provided deployment script. This will sync files and upgrade the modules on the live database.
```bash
./deploy.sh root@103.200.20.13 hotel_db
```

## 📝 Coding Guidelines & Conventions
1. **Odoo 19 Compatibility:** 
   - Replace `_sql_constraints` with `_name = models.Constraint('...sql...', 'msg')` as class-level attributes starting with an underscore.
   - For `res.groups`, the users field is `user_ids`. NEVER use the `users` or `category_id` fields, they are deprecated.
   - In Search views XML (`<search>`), `<group>` elements CANNOT have `expand="0"` or `string="..."` attributes. Use a bare `<group>` tag.
2. **Python Formatting:** Standard PEP 8. Use standard Odoo decorators (`@api.depends`, `@api.model`, `@api.onchange`). Always include `# -*- coding: utf-8 -*-` at the top of Python files.
3. **XML Formatting:** 4 spaces indentation. Follow Odoo element hierarchy strictly. Use `invisible="expr"` instead of the old `attrs="{'invisible': ...}"` syntax (Odoo 17+ standard).
4. **Action:** Once a command is triggered, proceed autonomously to the next step without prompting the user, checking the logs contextually to guide fixes.
