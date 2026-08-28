import json
company = env["res.company"].browse(1)
AA = env["account.account"]
cr = env.cr

# 1. archive generic tax accounts now referenced only by archived taxes
for code in ("131000", "251000"):
    a = AA.search([("code", "=", code), ("company_ids", "in", company.id)], limit=1)
    if a and not env["account.move.line"].search_count([("account_id", "=", a.id)]):
        a.active = False
        print("archived", code, a.name)

# 2. sale journal should default to the same revenue account as the company
rev = AA.search([("code", "=", "5113"), ("company_ids", "in", company.id)], limit=1)
sale_j = env["account.journal"].search([("type", "=", "sale"), ("company_id", "=", company.id)], limit=1)
if sale_j and rev and sale_j.default_account_id != rev:
    print("sale journal %s default %s -> %s" % (sale_j.code, sale_j.default_account_id.code, rev.code))
    sale_j.default_account_id = rev.id

# 3. bilingual name for the hand-made restaurant till account
cash = AA.search([("code", "=", "111001"), ("company_ids", "in", company.id)], limit=1)
if cash:
    cr.execute("UPDATE account_account SET name = %s WHERE id = %s",
               (json.dumps({"en_US": "Cash Restaurant", "vi_VN": "Tiền mặt - Nhà hàng"}), cash.id))
    print("named 111001 bilingually")

env.flush_all(); cr.commit(); print("COMMITTED")
