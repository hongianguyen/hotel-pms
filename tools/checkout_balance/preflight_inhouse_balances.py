"""Pre-flight for the check-out balance guard. Read-only.

Run BEFORE deploying the guard to a live database:

    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo-bin shell \
        -c <conf> -d <db> --no-http --logfile=/dev/null \
        < preflight_inhouse_balances.py

Every in-house reservation listed here would be barred from checking out
once the guard is live. That is the intended behaviour for a guest who
genuinely still owes money, but a folio imported from the old PMS without
its payments would be blocked for no real reason. Settle or write those
off first, or plan to use Check Out Anyway (Hotel Administrator).
"""

reservations = env['hotel.reservation'].search([('state', '=', 'checked_in')])
print('In-house reservations: %s' % len(reservations))

blocked = []
for res in reservations:
    for folio in res._folios_settling_on_departure():
        due = folio.amount_due_at_checkout()
        currency = folio.currency_id or env.company.currency_id
        if currency.compare_amounts(due, 0) > 0:
            blocked.append((res, folio, due))

print('Departures the guard would bar: %s' % len({r.id for r, _f, _d in blocked}))
for res, folio, due in blocked:
    print('  %-14s %-10s %-14s guest=%-28s due=%s' % (
        res.reservation_number,
        res.room_id.name or '-',
        folio.name,
        (res.guest_id.name or '')[:28],
        due,
    ))
