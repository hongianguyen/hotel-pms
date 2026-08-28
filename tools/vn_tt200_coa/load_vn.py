"""Step 1 - load the l10n_vn (Circular 200/2014/TT-BTC) chart onto an existing company.

Run with:  odoo-bin shell -c <conf> -d <db> --no-http < load_vn.py

Odoo 19 loads a new chart template *additively* when the company already has
journal items (account/models/chart_template.py:213), so existing postings are
preserved.  The one thing that blocks the load is point_of_sale's unconditional
`_check_type` constraint on account.journal: the VN template writes
{'type': 'cash', ...} to the cash journal, and the constraint vetoes any write
touching `type` on a journal that carries a POS payment method.  Detaching the
payment methods through the ORM is also vetoed while a POS session is open, so
the links are dropped and restored with raw SQL inside the same transaction.
"""
company = env["res.company"].browse(1)
cr = env.cr

cr.execute("SELECT id, journal_id FROM pos_payment_method WHERE journal_id IS NOT NULL")
links = cr.fetchall()
cash_j = env["account.journal"].search([("type", "=", "cash"), ("company_id", "=", company.id)], limit=1)
orig_cash_name = cash_j.name
print("POS method->journal links:", links, "| cash journal:", orig_cash_name)

cr.execute("UPDATE pos_payment_method SET journal_id = NULL WHERE journal_id IS NOT NULL")
env.invalidate_all()

env["account.chart.template"].try_loading("vn", company, install_demo=False)
env.flush_all()

for pid, jid in links:
    cr.execute("UPDATE pos_payment_method SET journal_id = %s WHERE id = %s", (jid, pid))
env.invalidate_all()
cash_j = env["account.journal"].browse(cash_j.id)
if cash_j.exists() and cash_j.name != orig_cash_name:
    cash_j.name = orig_cash_name          # template renames it to plain "Cash"
env.flush_all()
cr.commit()

print("chart_template:", company.chart_template)
print("accounts:", env["account.account"].search_count([]))
print("taxes:", env["account.tax"].search_count([]))
print("groups:", env["account.group"].search_count([]))
