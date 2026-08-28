company = env["res.company"].browse(1)
env = env(context=dict(env.context, allowed_company_ids=[company.id]))
partner = env["res.partner"].search([("customer_rank", ">", 0)], limit=1) or env["res.partner"].search([], limit=1)

# 1. create + post an invoice with VN 10% VAT
tax = env["account.tax"].search([("type_tax_use", "=", "sale"), ("amount", "=", 10.0), ("active", "=", True)], limit=1)
inv = env["account.move"].create({
    "move_type": "out_invoice", "partner_id": partner.id,
    "invoice_line_ids": [(0, 0, {"name": "Smoke test room night", "quantity": 1,
                                 "price_unit": 1000000, "tax_ids": [(6, 0, tax.ids)]})],
})
inv.action_post()
print("posted:", inv.name, "total:", inv.amount_total, "tax:", tax.name)
for l in inv.line_ids:
    print("   %-8s %-40s dr=%s cr=%s" % (l.account_id.code, (l.name or "")[:38], l.debit, l.credit))

# 2. register a payment
from odoo.tests import Form
wiz = env["account.payment.register"].with_context(active_model="account.move", active_ids=inv.ids).create({})
wiz.action_create_payments()
print("payment state:", inv.payment_state, "| residual:", inv.amount_residual)

# 3. trial balance still balanced
env.cr.execute("SELECT sum(debit)-sum(credit) FROM account_move_line WHERE parent_state='posted'")
print("trial balance:", env.cr.fetchone()[0])

# 4. reports render
for xmlid in ("account_reports.balance_sheet", "account_reports.profit_and_loss"):
    try:
        rep = env.ref(xmlid)
        opts = rep.get_options({})
        lines = rep._get_lines(opts)
        print("report OK:", xmlid, "lines:", len(lines))
    except ValueError:
        print("report not installed:", xmlid)
    except Exception as e:
        print("report FAILED:", xmlid, type(e).__name__, e)

# 5. tax report data present
print("VN tax report:", env["account.report"].search_count([("country_id.code", "=", "VN")]))
env.cr.rollback()
print("rolled back smoke test")
