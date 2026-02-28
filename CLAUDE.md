# CLAUDE.md - Odoo 19 Hotel PMS

This file provides, Bllueprint, contract, autonomous instructions and commands for Claude Code to manage, build, and deploy the Internal Hotel PMS project. 

## 🎭 VAI TRÒ

Bạn là THỢ XÂY trong hệ thống Vibecode Kit v4.0.

Kiến trúc sư và Chủ nhà đã THỐNG NHẤT bản vẽ dưới đây.
Nhiệm vụ của bạn: CODE CHÍNH XÁC theo Blueprint.

### QUY TẮC TUYỆT ĐỐI:
1. KHÔNG thay đổi kiến trúc / layout
2. KHÔNG thêm features không có trong Blueprint
3. KHÔNG đổi tech stack
4. NẾU gặp conflict kỹ thuật → BÁO CÁO, không tự quyết định

---

## 🚀 BẮT ĐẦU

Hỏi DUY NHẤT 1 câu:
> "Bạn muốn lưu dự án ở đâu? (VD: ~/projects/ten-app)"

Sau khi có câu trả lời → TIẾN HÀNH NGAY, không hỏi thêm.
📘 BLUEPRINT: INTERNAL HOTEL PMS v1.0
Odoo 19 Community – 30 Rooms
📋 PROJECT INFO
Field	Value
Dự án	Internal Hotel Operating System
Loại	Enterprise PMS (Internal Use)
Property	1
Rooms	30
Staff	20
Roles	Admin / Reception
Night Audit	Auto
Reporting	Dashboard
🎯 MỤC TIÊU

Primary Goal:
Vận hành khách sạn 30 phòng ổn định, nhanh, chính xác kế toán.

Secondary Goal:
Chuẩn hóa data để sau này có thể productize thành SaaS.

📐 SYSTEM STRUCTURE
MODULE ARCHITECTURE
hotel_core
hotel_frontdesk
hotel_housekeeping
hotel_revenue_basic
hotel_services
hotel_reporting
hotel_night_audit

Linked Native:

account
pos_restaurant
crm
contacts
mail
🧱 DATA MODEL (CỐT LÕI)
1️⃣ hotel.room.type

name

capacity

base_rate

description

2️⃣ hotel.room

name

room_type_id

status (available / occupied / dirty / maintenance)

floor

active

3️⃣ hotel.reservation

reservation_number

guest_id (res.partner)

checkin_date

checkout_date

room_id

rate_plan_id

state (draft / confirmed / checked_in / checked_out / cancelled)

total_amount

folio_id

4️⃣ hotel.folio

reservation_id

line_ids

total_amount

invoice_id

payment_state

5️⃣ hotel.rate.plan

name

season_id

day_of_week_rule

min_stay

stop_sell

🖥 CORE WORKFLOWS
🛎 BOOKING FLOW

Create reservation
→ Check availability
→ Assign room
→ Confirm
→ Auto email confirmation

(No deposit logic)

🏨 CHECK-IN FLOW

Reservation → Click "Check-in"

System:

Validate room availability

Create folio

Change room status → Occupied

State → checked_in

🧾 CHARGE FLOW

Sources:

POS restaurant

Tours/services

Manual charge

All charges → auto add to folio lines.

🏁 CHECK-OUT FLOW

Click "Check-out":

System:

Pull all folio lines

Generate invoice (account.move)

Register payment

Post journal entry

Change room → Dirty

State → checked_out

🌙 NIGHT AUDIT (AUTO)

Module: hotel_night_audit

Scheduled Action: Daily 02:00 AM

Process:

Close all checked-out folios

Auto post invoices draft → posted

Validate no open folio without payment

Update room status (Occupied stays continue)

Generate Daily Summary Snapshot

Lock previous day edits

Night Audit Report Stored:

Occupancy %

Revenue per category

ADR

RevPAR

Payment method split

Admin receives auto email summary.

🧹 HOUSEKEEPING

Room states:

Available
Occupied
Dirty
Cleaning
Maintenance

Reception can:

Change status manually

Block room

Mark cleaned

No separate role needed.

📊 DASHBOARD DESIGN
Reception Dashboard

Top KPI Cards:

Today Arrivals

Today Departures

Occupancy %

Dirty Rooms

Revenue Today

Main Section:

Gantt Calendar (full width)

Room Status Board

Admin Dashboard

KPI:

Monthly Occupancy

ADR

RevPAR

Room Revenue

F&B Revenue

Service Revenue

Charts:

Revenue by day (30 days)

Occupancy trend

Revenue breakdown pie

No Excel export needed.

🔐 ACCESS CONTROL
ROLE: Reception

Can:

Create reservation

Check-in/out

Modify booking

Add charges

View dashboard

Cannot:

Change accounting settings

Modify rate engine rules

Delete posted invoices

ROLE: Admin

Full access:

All modules

Night audit config

Accounting

Reports

Rate plans

💰 ACCOUNTING INTEGRATION

Invoice Type: Customer Invoice
Journal: Hotel Sales Journal

Revenue Mapping:

Room → 4000 Room Revenue

F&B → POS Revenue Account

Tours → 4020 Service Revenue

Tax → Odoo tax engine

Payment:

Cash

Card

Bank transfer

Reconciliation auto handled by Odoo.

🎨 DESIGN SYSTEM

Primary: #2563EB
Success: #22C55E
Warning: #F97316
Danger: #EF4444

Clean Odoo native UI.
No heavy custom frontend.

🚀 DEPLOYMENT ARCHITECTURE

Single Odoo 19 Instance
Hosted on:

VPS (recommended 4 vCPU / 8GB RAM minimum)

Daily backup required.

✅ CHECKPOINT

Chủ nhà xác nhận:

 Structure đúng mong muốn

 2 roles đủ dùng

 Night audit logic OK

 Không thiếu tính năng quan trọng
-------------

## 🎨 DESIGN TOKENS

```typescript
const colors = {
  primary: '#2563EB',
  secondary: '#64748B',
  success: '#22C55E',
  warning: '#F59E0B',
  error: '#EF4444',
  background: '#F8FAFC',
  card: '#FFFFFF',
  text: '#0F172A',
}
```

---

## 📦 COMPONENT PATTERNS

### Button Hierarchy
```tsx
// Primary - main action
<button className="bg-primary text-white px-4 py-2 rounded-lg hover:bg-primary/90 transition">
  Primary Action
</button>

// Secondary
<button className="border border-gray-300 px-4 py-2 rounded-lg hover:bg-gray-50 transition">
  Secondary
</button>

// Ghost
<button className="text-gray-600 hover:text-gray-900 transition">
  Cancel
</button>
```

### Form Inputs
```tsx
<input className="
  w-full px-4 py-2
  border border-gray-300 rounded-lg
  focus:ring-2 focus:ring-primary/50 focus:border-primary
  placeholder:text-gray-400
"/>
```

### Cards
```tsx
<div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
  {/* Content */}
</div>
```

### Empty State (BẮT BUỘC)
```tsx
<div className="text-center py-12">
  <Icon className="w-12 h-12 text-gray-300 mx-auto" />
  <h3 className="mt-4 text-lg font-medium text-gray-900">No items yet</h3>
  <p className="mt-2 text-gray-500">Get started by creating your first item.</p>
  <button className="mt-4 btn-primary">Create Item</button>
</div>
```

### Loading State (BẮT BUỘC)
```tsx
<div className="animate-pulse">
  <div className="h-4 bg-gray-200 rounded w-3/4"></div>
  <div className="h-4 bg-gray-200 rounded w-1/2 mt-2"></div>
</div>
```

---

## ✅ SAU KHI HOÀN THÀNH

Output:
```
✅ Đã tạo xong [số] files
📁 Location: [path]

Để chạy:
1. cd [path]
2. npm install
3. npm run dev
4. Mở http://localhost:3000

Báo cáo hoàn thành. Chủ nhà có thể test và yêu cầu REFINE nếu cần.
```

---
# ═══════════════════════════════════════════════════════════════
#                      END OF CODER PACK
# ══════════════════════════


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
