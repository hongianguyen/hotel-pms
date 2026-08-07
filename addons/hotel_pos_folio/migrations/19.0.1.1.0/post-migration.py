# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api
from odoo.addons.hotel_pos_folio import backfill_in_house_flags


def migrate(cr, version):
    """Guests checked in before the create/write hooks existed have no flags."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    backfill_in_house_flags(env)
