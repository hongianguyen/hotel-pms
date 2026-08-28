# Vietnam TT200 chart of accounts migration

Moves an Odoo 19 company from `generic_coa` to `l10n_vn` — the VAS chart under
**Circular 200/2014/TT-BTC**. Applied to production `hotel_db`
(14.225.192.16) on 25 Aug 2026.

## Order

```bash
systemctl stop odoo
sudo -u postgres pg_dump -Fc hotel_db -f /root/backups/pre_tt200.dump

cd /opt/odoo/odoo
sudo -u odoo /opt/odoo/venv/bin/python3 odoo-bin shell -c /etc/odoo.conf \
    -d hotel_db --no-http --logfile=/dev/stdout < load_vn.py

DRY=1 REVENUE_MODE=sub5113 sudo -u odoo -E ... < cleanup_vn.py   # review first
DRY=0 REVENUE_MODE=sub5113 sudo -u odoo -E ... < cleanup_vn.py

sudo -u odoo /opt/odoo/venv/bin/python3 odoo-bin shell ... < finish.py
systemctl start odoo
```

`smoke.py` posts an invoice + payment and rolls back — run it on a **restored
copy**, never on production.

## Rehearse first

The whole thing was validated by restoring the prod dump into a scratch DB on
the same box and running it there. Do that again rather than trusting the test
server, which has diverged from prod.

## Traps found the hard way

- **`point_of_sale._check_type`** fires on *any* write touching
  `account.journal.type`, even a no-op one, when the journal has a POS payment
  method. It vetoes the template load. See the docstring in `load_vn.py`.
- **An open POS session** blocks `pos.payment.method.write()` entirely, so the
  detach has to be raw SQL. Lak's session `Y Lak Restaurant/00003` had been
  open since 17 Aug with zero orders; the SQL route avoids disturbing it.
- **Assigning a dict to a translated field** (`account.code = {...}`) stores the
  *stringified dict* into `en_US`. Write the `name` jsonb column directly.
- **`_action_merge` picks the surviving code non-deterministically** — it builds
  `code_by_company` with `jsonb_object_agg` over both accounts, so either code
  can win. Always re-write `code_store` explicitly afterwards.
- Odoo keeps functional accounts (outstanding receipts/payments, suspense) under
  `account.1_account_journal_*` xmlids and **renumbers them into the new prefix
  range**. They look like generic leftovers but must never be archived.
- `reflect_code_prefix_change` only touches `asset_cash` /
  `liability_credit_card` accounts, so the blast radius of the
  1014→112 / 1015→111 prefix switch is small.
