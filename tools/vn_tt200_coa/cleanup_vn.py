import os, json
DRY = os.environ.get("DRY", "1") == "1"
# REVENUE_MODE: "sub5113" -> create/user 5113 Doanh thu cung cap dich vu ; "parent" -> template 511/5110
REVENUE_MODE = os.environ.get("REVENUE_MODE", "sub5113")
company = env["res.company"].browse(1)
AA = env["account.account"]
cr = env.cr

def by_code(code):
    return AA.search([("code", "=", code), ("company_ids", "in", company.id)], limit=1)

def merge(keep, drop, final_code, final_name):
    if not (keep and drop) or keep == drop:
        print("  skip merge (missing/same)"); return keep
    print("  merge keep=%s(id=%s) <- drop=%s(id=%s)" % (keep.code, keep.id, drop.code, drop.id))
    if DRY:
        return keep
    env["account.merge.wizard"]._action_merge(keep + drop)
    # Write code + translated name as raw jsonb: assigning a dict to a translated
    # field stores the stringified dict into en_US.
    cr.execute("UPDATE account_account SET code_store = %s, name = %s WHERE id = %s",
               (json.dumps({"1": final_code}), json.dumps(final_name), keep.id))
    env.invalidate_all()
    return AA.browse(keep.id)

print("--- 1. receivable 121000 -> 1311 ---")
merge(env.ref("account.1_chart1311"), by_code("121000"), "1311",
      {"en_US": "Trade receivables - short term",
       "vi_VN": "Phải thu của khách hàng - ngắn hạn"})

print("--- 2. revenue 400000 -> (%s) ---" % REVENUE_MODE)
if REVENUE_MODE == "sub5113":
    rev = by_code("5113")
    if not rev:
        print("  creating 5113")
        if not DRY:
            rev = AA.create({
                "code": "5113",
                "name": "Revenue from services rendered",
                "account_type": "income",
                "company_ids": [(6, 0, [company.id])],
            })
    rev_code, rev_name = "5113", {"en_US": "Revenue from services rendered",
                                 "vi_VN": "Doanh thu cung cấp dịch vụ"}
else:
    rev = env.ref("account.1_chart5111")
    rev_code, rev_name = rev.code, rev.name
rev = merge(rev, by_code("400000"), rev_code, rev_name)
if not DRY and rev:
    company.income_account_id = rev.id
    print("  company.income_account_id ->", rev.code)

print("--- 3. archive junk pre-existing taxes ---")
junk = env["account.tax"].browse([1, 2, 3, 4, 5, 6, 7, 8]).exists()
junk = junk.filtered(lambda t: not env["account.move.line"].search_count([("tax_ids", "in", t.id)]))
print("  archiving:", [(t.id, t.name) for t in junk])
if not DRY:
    junk.active = False

print("--- 4. archive duplicate cash journal created by the load ---")
cash_js = env["account.journal"].search([("type", "=", "cash"), ("company_id", "=", company.id)])
dupes = cash_js.filtered(lambda j: not j.pos_payment_method_ids
                         and not env["account.move.line"].search_count([("journal_id", "=", j.id)]))
dupes = dupes if len(dupes) < len(cash_js) else dupes[1:]
print("  archiving journals:", [(j.code, j.name) for j in dupes])
if not DRY:
    dupes.active = False

print("--- 5. archive unused generic-CoA accounts ---")
protected = set()
for f in company._fields:
    v = company[f]
    if getattr(v, "_name", None) == "account.account":
        protected |= set(v.ids)
scan = [("account.journal", None), ("pos.payment.method", None),
        ("account.payment.method.line", None), ("account.tax.repartition.line", None),
        ("product.category", None), ("account.fiscal.position.account", None)]
for model, _f in scan:
    if model not in env:
        continue
    for rec in env[model].with_context(active_test=False).search([]):
        for f in rec._fields:
            if f.endswith(("account_id", "account_dest_id", "account_src_id")):
                val = rec[f]
                if getattr(val, "_name", None) == "account.account":
                    protected |= set(val.ids)
# Odoo's own functional accounts (outstanding receipts/payments, suspense, ...) keep an
# `account.1_account_journal_*` xmlid even after the prefix rewrite -- never archive them.
functional = env["ir.model.data"].search([
    ("model", "=", "account.account"), ("module", "=", "account"),
    "|", ("name", "like", "1_account_journal_%"), ("name", "like", "1_%_journal_default_account_%")])
protected |= set(functional.mapped("res_id"))
vn_ids = set(env["ir.model.data"].search([
    ("model", "=", "account.account"), ("module", "=", "account"),
    ("name", "like", "1_chart%")]).mapped("res_id"))

candidates = AA.search([("company_ids", "in", company.id), ("active", "=", True)])
to_archive = candidates.filtered(
    lambda a: a.id not in protected and a.id not in vn_ids and a.code != "101950"
    and not env["account.move.line"].search_count([("account_id", "=", a.id)]))
print("  protected=%d  vn_template=%d  candidates=%d" % (len(protected), len(vn_ids), len(candidates)))
print("  archiving %d:" % len(to_archive))
for a in to_archive:
    print("     %-8s %s" % (a.code, a.name.get("en_US") if isinstance(a.name, dict) else a.name))
if not DRY:
    to_archive.active = False

if not DRY:
    env.flush_all(); cr.commit(); print("COMMITTED")
else:
    print("DRY RUN - nothing written")
