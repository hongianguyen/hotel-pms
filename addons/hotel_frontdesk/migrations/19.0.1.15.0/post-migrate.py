# -*- coding: utf-8 -*-
"""Account Type moves from a fixed list to editable records.

Agencies kept their type in the `hotel_agency_type` selection column
(travel_agent / corporate, and ota on servers that had 19.0.1.14.0); rate
plans on such servers in `account_type`. Point both at the matching
hotel.account.type record by its code, then recompute every booking's
account type, which was computed before these records existed.

The old columns are left in place: dropping data is not this migration's
job, and they are what this mapping reads.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def _has_column(cr, table, column):
    cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
               (table, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Type = env['hotel.account.type']

    if _has_column(cr, 'res_partner', 'hotel_agency_type'):
        cr.execute("""
            UPDATE res_partner p
               SET hotel_account_type_id = t.id
              FROM hotel_account_type t
             WHERE t.code = p.hotel_agency_type
               AND p.hotel_account_type_id IS NULL
        """)
        _logger.info('Account types copied onto %s partners', cr.rowcount)
    # Agencies with no type at all were Travel Agents by default.
    agent = Type.by_code('travel_agent')
    if agent:
        cr.execute("""
            UPDATE res_partner SET hotel_account_type_id = %s
             WHERE is_hotel_agency AND hotel_account_type_id IS NULL
        """, (agent.id,))

    if _has_column(cr, 'hotel_rate_plan', 'account_type'):
        cr.execute("""
            UPDATE hotel_rate_plan p
               SET account_type_id = t.id
              FROM hotel_account_type t
             WHERE t.code = p.account_type
               AND p.account_type_id IS NULL
        """)

    # Every booking, not only agency ones: the column was filled when the
    # module loaded, before the Direct Guest record existed, so direct
    # bookings were left without a type too.
    env.invalidate_all()
    reservations = env['hotel.reservation'].with_context(active_test=False).search([])
    env.add_to_compute(reservations._fields['account_type_id'], reservations)
    reservations.flush_recordset(['account_type_id'])
    _logger.info('Account type recomputed on %s bookings', len(reservations))
