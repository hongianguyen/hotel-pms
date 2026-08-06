# -*- coding: utf-8 -*-
import logging

from . import models

_logger = logging.getLogger(__name__)

CLEARING_CODE = '101950'
CLEARING_NAME = 'Room Charge Clearing (POS)'
METHOD_NAME = 'Charge to Room'


def post_init_hook(env):
    """Create the room-charge clearing account and POS payment method.

    Done in Python rather than XML data because both records are per-company
    and depend on a chart of accounts already being loaded.
    """
    for company in env['res.company'].search([]):
        if not env['account.account'].search_count(
                [('company_ids', 'in', company.id)]):
            _logger.info(
                'hotel_pos_folio: company %s has no chart of accounts, '
                'skipping room-charge setup', company.name)
            continue

        account = env['account.account'].search([
            ('code', '=', CLEARING_CODE),
            ('company_ids', 'in', company.id),
        ], limit=1)
        if not account:
            account = env['account.account'].create({
                'code': CLEARING_CODE,
                'name': CLEARING_NAME,
                'account_type': 'asset_current',
                'reconcile': True,
                'company_ids': [(6, 0, [company.id])],
            })
            _logger.info('hotel_pos_folio: created clearing account %s for %s',
                         CLEARING_CODE, company.name)

        method = env['pos.payment.method'].search([
            ('is_hotel_folio', '=', True),
            ('company_id', '=', company.id),
        ], limit=1)
        if not method:
            env['pos.payment.method'].create({
                'name': METHOD_NAME,
                'is_hotel_folio': True,
                'company_id': company.id,
                'receivable_account_id': account.id,
            })
            _logger.info('hotel_pos_folio: created "%s" payment method for %s',
                         METHOD_NAME, company.name)
