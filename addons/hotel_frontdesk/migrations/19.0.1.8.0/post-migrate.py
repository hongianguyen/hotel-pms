# -*- coding: utf-8 -*-
"""Open folios for bookings already confirmed before folios moved earlier.

Folios now open at confirmation rather than at check-in, so that a deposit
taken before arrival has an account to land on. Bookings confirmed under the
old behaviour still have no folio, and reception cannot register their
prepayment until the guest arrives — which is exactly the case this change
exists to fix. Give them their folio now.

Deliberately bounded to arrivals that have not departed yet: the database
carries ~19k historical reservations from the old-PMS import, and a stay that
is already over has nothing left to prepay. `_ensure_folios` is idempotent
and also opens the company folio where the agency's routing instructions
call for one.
"""

import logging

from odoo import SUPERUSER_ID, api, fields

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    today = fields.Date.context_today(env['hotel.reservation'])
    pending = env['hotel.reservation'].search([
        ('state', '=', 'confirmed'),
        ('folio_id', '=', False),
        ('checkout_date', '>=', today),
    ])
    if not pending:
        return

    _logger.info('Opening folios for %d confirmed bookings', len(pending))
    for reservation in pending:
        reservation._ensure_folios()
    _logger.info('Folio backfill complete')
