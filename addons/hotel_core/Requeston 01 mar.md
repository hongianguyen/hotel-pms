🔐 Authorization & Decision Policy
Claude is fully authorized to:

Add new fields, methods, and computed functions without asking for approval
Refactor existing methods for clarity, consistency, or Odoo best practices
Add or extend _inherit models where it makes sense
Reorganize internal logic (e.g. extract helpers, consolidate onchange/compute methods)
Improve ORM usage (e.g. replace loops with recordset operations, use sudo() correctly)
Add inline comments where refactored code benefits from explanation

Claude should stop and ask only if:

A refactor would change the behavior of an existing public method or field that other modules may depend on
Two fundamentally different architectural approaches apply (e.g. new model vs extending existing one) and the choice has long-term consequences
A required piece of information is missing and cannot be inferred (e.g. which model to inherit, an expected domain, a missing field name)

For everything else — make a judgment call, leave a brief comment if non-obvious, and keep going.

📦 Module Overview
Module technical name:Hotel-pms
Odoo version: 19.0 Community 
Purpose: Hotel Management 


🧠 Current State

What already works. Claude treats this as ground truth and will not break it.

Known issues or tech debt to address during refactor:

Rate plan of room is not override the based price


➕ New Functions / Fields to Add

Save and exit,  Discard Button,  on Booking screen and other screen
Group Booking, which can generate randomize rooms in same room type at once for same period-> Create one booking -> one folio 
New variances in Configuration: "Source"
Generate custom Reservation Confirmation, option to send email.


🔧 Refactoring Instructions

Dashboard

1. Status color on dashboard

Set status color:
Past date: 9DA2A8
Confirmed: 799DC7
Dirty: D9200 (after checked out)
Active: (Checked in): E87C09
Out of order (Blocked for maintenance): F79D2D

2. Dashboard
Click on active room-> display folio Screen

3.Dashboard Design
Resize KPI report to 30%, Dashboard at 65% of screen
15 days displayed on Dashboard includes: From current date -1 to current date + 13
Add Start Date Selection to display 15 Days after
Add Next and Back Button to display Next 15 days, Back 15 Day



Environment notes:
test Environment

🚫 Do Not Touch

Claude will leave these completely unchanged.

Production Environment



✅ Definition of Done
Each change is complete when:

 New fields/methods follow Odoo ORM patterns correctly
 No direct SQL unless explicitly requested
 Refactored code is behaviorally identical to what it replaced
 _constraints, @api.constrains, or @api.onchange are used appropriately
 User-facing strings are wrapped in _() if translations are in scope
 __manifest__.py and __init__.py updated if new files were added
 [Any other condition — upgrade script needed, view updated, access rights added, etc.]

