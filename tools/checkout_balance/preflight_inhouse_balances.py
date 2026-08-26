"""Pre-flight for the check-out balance guard. READ-ONLY — writes nothing.

Run BEFORE deploying the guard to a live database:

    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo-bin shell \
        -c <conf> -d <db> --no-http --logfile=/dev/null \
        < preflight_inhouse_balances.py

Every in-house reservation listed here would be barred from checking out
once the guard is live. That is the intended behaviour for a guest who
genuinely still owes money, but a folio imported from the old PMS without
its payments would be blocked for no real reason. Settle or write those
off first, or plan to use Check Out Anyway (Hotel Administrator).

Deliberately reimplements the guard's rules instead of calling it, so it
runs against a database that does NOT have the guard installed yet.
Keep the two in step if the rules change.
"""

from odoo import fields

Reservation = env['hotel.reservation']
today = fields.Date.context_today(Reservation)

reservations = Reservation.search([('state', '=', 'checked_in')])
print('In-house reservations: %s' % len(reservations))

blocked = {}
for res in reservations:
    # Late-checkout nights the departure would raise but that are not on
    # the folio yet — the guard counts these as due.
    late_nights = max((today - res.checkout_date).days, 0)
    late_amount = late_nights * res.nightly_rate
    late_folio = res._folio_for_charge_type('room') if late_amount else None

    for folio in (res.folio_id | res.folio_id.linked_folio_id):
        if not folio:
            continue
        # A company account on credit terms is collected later, not at the desk.
        if folio.folio_type == 'company' and folio.agency_credit_term:
            continue
        # Judge a folio only once no other room can still charge it.
        if folio._pending_reservations() - res:
            continue
        due = folio.balance + (late_amount if folio == late_folio else 0.0)
        currency = folio.currency_id or env.company.currency_id
        if currency.compare_amounts(due, 0) > 0:
            blocked.setdefault(res.id, []).append((res, folio, due, late_amount))

print('Departures the guard would bar: %s of %s' % (
    len(blocked), len(reservations)))
total = 0.0
for rows in blocked.values():
    for res, folio, due, late_amount in rows:
        total += due
        print('  %-14s %-10s %-16s %-26s due=%15.0f%s' % (
            res.reservation_number,
            res.room_id.name or '-',
            folio.name,
            (res.guest_id.name or '')[:26],
            due,
            '  (incl. late-checkout %.0f)' % late_amount if late_amount else '',
        ))
if blocked:
    print('  %s' % ('-' * 78))
    print('  TOTAL OUTSTANDING: %.0f' % total)

admins = env['res.users'].search([
    ('group_ids', 'in', env.ref('hotel_core.group_hotel_admin').id),
    ('active', '=', True),
])
print('Hotel Administrators who could override: %s%s' % (
    len(admins), (' — %s' % ', '.join(admins.mapped('login'))) if admins else ''))
